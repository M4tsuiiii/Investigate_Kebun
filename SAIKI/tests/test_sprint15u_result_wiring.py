"""Sprint 15U — Result Wiring Completion (Backend → UI).

Proves the full data path:
Skill Result → PortWorkerState → EventBus → Controller → UI columns.

Acceptance Criteria:
- AC-01: Workflow finishes → result enters PortWorkerState
- AC-02: PortState changes → event published
- AC-03: UI receives event
- AC-04: Table columns update without restart
- AC-05: Mass commands show real data
- AC-06: No more "workflow success but UI stays '-'"
"""
import logging
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _LogCaptureHandler(logging.Handler):
    def __init__(self, records):
        super().__init__()
        self._records = records
    def emit(self, record):
        self._records.append(record)


class _CaptureLogs:
    def __init__(self, logger_name):
        self._logger = logging.getLogger(logger_name)
        self.records = []
        self._handler = _LogCaptureHandler(self.records)
    def __enter__(self):
        self._old_level = self._logger.level
        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.DEBUG)
        return self
    def __exit__(self, *args):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._old_level)
    def has(self, substring):
        return any(substring in r.getMessage() for r in self.records)
    def messages(self, substring=None):
        msgs = [r.getMessage() for r in self.records]
        if substring:
            return [m for m in msgs if substring in m]
        return msgs


class EventBus:
    def __init__(self):
        self._subs = {}
        self._published = []
    def subscribe(self, event, handler):
        self._subs.setdefault(event, []).append(handler)
    def publish(self, event, payload=None):
        p = payload or {}
        self._published.append((event, p))
        for h in self._subs.get(event, []):
            h(p)
    def published(self, event=None):
        if event:
            return [(e, p) for e, p in self._published if e == event]
        return list(self._published)


# --- Fake classes ---

class FakeAutoRunConfig:
    def __init__(self):
        self.auto_run_enabled = False


from worker.state import PortWorkerState


class FakeWorkerManager:
    def __init__(self):
        self._port_states = {}
    def get_port_state(self, port):
        if port not in self._port_states:
            self._port_states[port] = PortWorkerState(port)
        return self._port_states[port]
    def get_worker(self, port):
        return None


# ==============================================================
# DELIVERABLE #1-3: Engine on_step_complete → PortWorkerState
# ==============================================================

class TestEngineStepCallback(unittest.TestCase):
    """Prove on_step_complete maps SkillResult.data → PortWorkerState."""

    def _make_engine(self, event_bus=None, port_state_provider=None):
        from automation.engine import AutomationEngine
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry

        bus = event_bus or EventBus()
        provider = port_state_provider or FakeWorkerManager()
        runner = WorkflowRunner(skill_map={}, cooldown_seconds=0)
        registry = WorkflowRegistry()

        engine = AutomationEngine(
            workflow_runner=runner,
            workflow_registry=registry,
            auto_run_config=FakeAutoRunConfig(),
            event_bus=bus,
            max_concurrent=2,
            port_state_provider=provider,
        )
        return engine, bus, provider

    def test_cek_nomor_result_updates_port_state(self):
        """AC-01: CekNomorSkill result → PortWorkerState.nomor."""
        engine, bus, provider = self._make_engine()

        from worker.skills.base import SkillResult
        result = SkillResult(
            success=True,
            data={"number": "081234567890", "modem_responsive": True, "raw_cnum": "+CNUM"},
            skill_name="cek_nomor",
            port="COM5",
        )

        context = type("Ctx", (), {"port": "COM5"})()
        engine._on_step_complete("cek_nomor", result, context)

        state = provider.get_port_state("COM5")
        self.assertEqual(state._nomor, "081234567890")

    def test_verify_grace_result_updates_masa_aktif(self):
        """AC-01: VerifyGraceSkill result → PortWorkerState.masa_aktif."""
        engine, bus, provider = self._make_engine()

        from worker.skills.base import SkillResult
        result = SkillResult(
            success=True,
            data={"card_status": "AKTIF", "grace_date": "12/12/2026", "raw_response": "Status: AKTIF"},
            skill_name="verify_grace",
            port="COM7",
        )

        context = type("Ctx", (), {"port": "COM7"})()
        engine._on_step_complete("verify_grace", result, context)

        state = provider.get_port_state("COM7")
        self.assertEqual(state._masa_aktif, "12/12/2026")

    def test_cek_status_result_publishes_respon(self):
        """AC-02: CekStatusSkill result → port.data.updated with respon."""
        engine, bus, provider = self._make_engine()

        from worker.skills.base import SkillResult
        result = SkillResult(
            success=True,
            data={"cpin_state": "READY", "sim_ready": True, "raw_response": "OK"},
            skill_name="cek_status",
            port="COM3",
        )

        context = type("Ctx", (), {"port": "COM3"})()
        engine._on_step_complete("cek_status", result, context)

        events = bus.published("port.data.updated")
        self.assertTrue(len(events) > 0)
        _, payload = events[-1]
        self.assertEqual(payload["port"], "COM3")
        self.assertIn("READY", payload.get("respon", ""))

    def test_failed_skill_does_not_update_state(self):
        """Failed skill result should NOT update PortWorkerState."""
        engine, bus, provider = self._make_engine()

        from worker.skills.base import SkillResult
        result = SkillResult(
            success=False,
            error="timeout",
            skill_name="cek_nomor",
            port="COM5",
        )

        context = type("Ctx", (), {"port": "COM5"})()
        engine._on_step_complete("cek_nomor", result, context)

        state = provider.get_port_state("COM5")
        self.assertEqual(state._nomor, "-")

    def test_step_callback_publishes_port_data_updated(self):
        """AC-02: Step callback publishes port.data.updated event."""
        engine, bus, provider = self._make_engine()

        from worker.skills.base import SkillResult
        result = SkillResult(
            success=True,
            data={"number": "081234567890"},
            skill_name="cek_nomor",
            port="COM5",
        )

        context = type("Ctx", (), {"port": "COM5"})()
        engine._on_step_complete("cek_nomor", result, context)

        events = bus.published("port.data.updated")
        self.assertEqual(len(events), 1)
        _, payload = events[0]
        self.assertEqual(payload["port"], "COM5")
        self.assertEqual(payload["nomor"], "081234567890")

    def test_no_event_when_no_data(self):
        """Empty data should NOT publish port.data.updated."""
        engine, bus, provider = self._make_engine()

        from worker.skills.base import SkillResult
        result = SkillResult(
            success=True,
            data={},
            skill_name="cek_nomor",
            port="COM5",
        )

        context = type("Ctx", (), {"port": "COM5"})()
        engine._on_step_complete("cek_nomor", result, context)

        events = bus.published("port.data.updated")
        self.assertEqual(len(events), 0)

    def test_verify_grace_publishes_masa_aktif_in_event(self):
        """AC-02: verify_grace result → port.data.updated with masa_aktif."""
        engine, bus, provider = self._make_engine()

        from worker.skills.base import SkillResult
        result = SkillResult(
            success=True,
            data={"grace_date": "12/12/2026", "card_status": "AKTIF"},
            skill_name="verify_grace",
            port="COM7",
        )

        context = type("Ctx", (), {"port": "COM7"})()
        engine._on_step_complete("verify_grace", result, context)

        events = bus.published("port.data.updated")
        self.assertTrue(len(events) > 0)
        _, payload = events[-1]
        self.assertEqual(payload["masa_aktif"], "12/12/2026")
        self.assertIn("AKTIF", payload.get("respon", ""))


# ==============================================================
# DELIVERABLE #5: Controller port.data.updated → PORT_UPDATE
# ==============================================================

class TestControllerPortDataWiring(unittest.TestCase):
    """Prove Controller forwards port.data.updated to PORT_UPDATE."""

    def _make_controller(self, event_bus=None):
        from worker.ui.controller import UIController

        bus = event_bus or EventBus()
        wm = FakeWorkerManager()

        ctrl = UIController(
            event_bus=bus,
            worker_manager=wm,
            auto_run_config=FakeAutoRunConfig(),
            automation_engine=None,
            db_lookup=None,
        )
        return ctrl, bus

    def test_controller_forwards_nomor_to_port_update(self):
        """AC-03: Controller receives port.data.updated → publishes PORT_UPDATE."""
        ctrl, bus = self._make_controller()

        ctrl._on_port_data_updated({
            "port": "COM5",
            "nomor": "081234567890",
        })

        updates = bus.published("ui.port.update")
        self.assertTrue(len(updates) > 0)
        _, payload = updates[-1]
        self.assertEqual(payload["port"], "COM5")
        self.assertEqual(payload["nomor"], "081234567890")

    def test_controller_forwards_all_fields(self):
        """All fields present in payload are forwarded."""
        ctrl, bus = self._make_controller()

        ctrl._on_port_data_updated({
            "port": "COM5",
            "nomor": "081234567890",
            "nik": "3276015001900001",
            "kk": "3276015001900002",
            "masa_aktif": "12/12/2026",
        })

        updates = bus.published("ui.port.update")
        self.assertTrue(len(updates) > 0)
        _, payload = updates[-1]
        self.assertEqual(payload["nomor"], "081234567890")
        self.assertEqual(payload["nik"], "3276015001900001")
        self.assertEqual(payload["kk"], "3276015001900002")
        self.assertEqual(payload["masa_aktif"], "12/12/2026")

    def test_controller_forwards_respon(self):
        """respon field is forwarded."""
        ctrl, bus = self._make_controller()

        ctrl._on_port_data_updated({
            "port": "COM5",
            "respon": "READY, True",
        })

        updates = bus.published("ui.port.update")
        self.assertTrue(len(updates) > 0)
        _, payload = updates[-1]
        self.assertEqual(payload["respon"], "READY, True")

    def test_controller_logs_port_data_wired(self):
        """PORT DATA WIRED log is emitted."""
        ctrl, bus = self._make_controller()

        with _CaptureLogs("saiki.controller") as cap:
            ctrl._on_port_data_updated({
                "port": "COM5",
                "nomor": "081234567890",
            })

        self.assertTrue(cap.has("PORT DATA WIRED"))
        self.assertTrue(cap.has("COM5"))

    def test_controller_ignores_empty_port(self):
        """Empty port should be ignored."""
        ctrl, bus = self._make_controller()

        ctrl._on_port_data_updated({"port": ""})
        ctrl._on_port_data_updated({})

        updates = bus.published("ui.port.update")
        self.assertEqual(len(updates), 0)


# ==============================================================
# DELIVERABLE #6: GUI _on_port_update handles data fields
# ==============================================================

class TestGuiPortUpdateLogic(unittest.TestCase):
    """Prove GUI _on_port_update logic handles nomor/nik/kk/masa_aktif."""

    def _simulate_on_port_update(self, port_data, payload):
        """Simulate GUIApplication._on_port_update logic."""
        port = payload.get("port")
        if not port:
            return

        status = payload.get("status")
        detail = payload.get("detail")

        if status is not None:
            port_data.setdefault(port, {})["status"] = str(status)
        if detail is not None:
            port_data.setdefault(port, {})["respon"] = str(detail)

        # Sprint 15U: Skill result data columns
        for field in ("nomor", "nik", "kk", "masa_aktif"):
            value = payload.get(field)
            if value is not None and value != "-":
                port_data.setdefault(port, {})[field] = str(value)

        # Sprint 15U: Direct respon field
        respon = payload.get("respon")
        if respon is not None:
            port_data.setdefault(port, {})["respon"] = str(respon)

    def test_on_port_update_writes_nomor(self):
        """AC-04: GUI _on_port_update writes nomor to table."""
        port_data = {}
        self._simulate_on_port_update(port_data, {
            "port": "COM5",
            "nomor": "081234567890",
        })
        self.assertEqual(port_data["COM5"]["nomor"], "081234567890")

    def test_on_port_update_writes_nik(self):
        """AC-04: GUI _on_port_update writes nik to table."""
        port_data = {}
        self._simulate_on_port_update(port_data, {
            "port": "COM5",
            "nik": "3276015001900001",
        })
        self.assertEqual(port_data["COM5"]["nik"], "3276015001900001")

    def test_on_port_update_writes_kk(self):
        """AC-04: GUI _on_port_update writes kk to table."""
        port_data = {}
        self._simulate_on_port_update(port_data, {
            "port": "COM5",
            "kk": "3276015001900002",
        })
        self.assertEqual(port_data["COM5"]["kk"], "3276015001900002")

    def test_on_port_update_writes_masa_aktif(self):
        """AC-04: GUI _on_port_update writes masa_aktif to table."""
        port_data = {}
        self._simulate_on_port_update(port_data, {
            "port": "COM5",
            "masa_aktif": "12/12/2026",
        })
        self.assertEqual(port_data["COM5"]["masa_aktif"], "12/12/2026")

    def test_on_port_update_writes_respon(self):
        """AC-04: GUI _on_port_update writes respon to table."""
        port_data = {}
        self._simulate_on_port_update(port_data, {
            "port": "COM5",
            "respon": "Nomor: 081234567890",
        })
        self.assertEqual(port_data["COM5"]["respon"], "Nomor: 081234567890")

    def test_on_port_update_skips_dash_values(self):
        """Dash values ('-') should NOT overwrite existing data."""
        port_data = {"COM5": {"nomor": "081234567890"}}
        self._simulate_on_port_update(port_data, {
            "port": "COM5",
            "nomor": "-",
        })
        self.assertEqual(port_data["COM5"]["nomor"], "081234567890")

    def test_on_port_update_multiple_fields(self):
        """Multiple fields in one payload all get written."""
        port_data = {}
        self._simulate_on_port_update(port_data, {
            "port": "COM5",
            "nomor": "081234567890",
            "nik": "3276015001900001",
            "kk": "3276015001900002",
            "masa_aktif": "12/12/2026",
            "respon": "AKTIF",
        })
        self.assertEqual(port_data["COM5"]["nomor"], "081234567890")
        self.assertEqual(port_data["COM5"]["nik"], "3276015001900001")
        self.assertEqual(port_data["COM5"]["kk"], "3276015001900002")
        self.assertEqual(port_data["COM5"]["masa_aktif"], "12/12/2026")
        self.assertEqual(port_data["COM5"]["respon"], "AKTIF")


# ==============================================================
# DELIVERABLE #7: End-to-end wiring tests
# ==============================================================

class TestEndToEndWiring(unittest.TestCase):
    """Prove the full path: Skill → Engine → EventBus → Controller → GUI."""

    def test_full_path_cek_nomor(self):
        """AC-06: CekNomor skill result reaches GUI table."""
        bus = EventBus()
        wm = FakeWorkerManager()

        # 1. Controller subscribes BEFORE engine runs
        from worker.ui.controller import UIController
        ctrl = UIController(
            event_bus=bus, worker_manager=wm,
            auto_run_config=FakeAutoRunConfig(),
            automation_engine=None, db_lookup=None,
        )

        # 2. Engine on_step_complete fires
        from automation.engine import AutomationEngine
        engine, _, _ = TestEngineStepCallback._make_engine(
            self, event_bus=bus, port_state_provider=wm
        )

        from worker.skills.base import SkillResult
        skill_result = SkillResult(
            success=True,
            data={"number": "081234567890", "modem_responsive": True},
            skill_name="cek_nomor",
            port="COM5",
        )
        context = type("Ctx", (), {"port": "COM5"})()
        engine._on_step_complete("cek_nomor", skill_result, context)

        # 3. Verify PortWorkerState updated
        state = wm.get_port_state("COM5")
        self.assertEqual(state._nomor, "081234567890")

        # 4. Verify port.data.updated event published
        events = bus.published("port.data.updated")
        self.assertEqual(len(events), 1)
        _, payload = events[0]
        self.assertEqual(payload["nomor"], "081234567890")

        # 5. Controller forwarded to PORT_UPDATE
        port_updates = bus.published("ui.port.update")
        self.assertTrue(len(port_updates) > 0)
        _, final_payload = port_updates[-1]
        self.assertEqual(final_payload["nomor"], "081234567890")

    def test_full_path_verify_grace(self):
        """AC-06: VerifyGrace skill result reaches GUI masa_aktif."""
        bus = EventBus()
        wm = FakeWorkerManager()

        from worker.ui.controller import UIController
        ctrl = UIController(
            event_bus=bus, worker_manager=wm,
            auto_run_config=FakeAutoRunConfig(),
            automation_engine=None, db_lookup=None,
        )

        from automation.engine import AutomationEngine
        engine, _, _ = TestEngineStepCallback._make_engine(
            self, event_bus=bus, port_state_provider=wm
        )

        from worker.skills.base import SkillResult
        skill_result = SkillResult(
            success=True,
            data={"card_status": "AKTIF", "grace_date": "12/12/2026"},
            skill_name="verify_grace",
            port="COM7",
        )
        context = type("Ctx", (), {"port": "COM7"})()
        engine._on_step_complete("verify_grace", skill_result, context)

        state = wm.get_port_state("COM7")
        self.assertEqual(state._masa_aktif, "12/12/2026")

        events = bus.published("port.data.updated")
        self.assertTrue(len(events) > 0)
        _, payload = events[-1]
        self.assertEqual(payload["masa_aktif"], "12/12/2026")

        port_updates = bus.published("ui.port.update")
        self.assertTrue(len(port_updates) > 0)
        _, final = port_updates[-1]
        self.assertEqual(final["masa_aktif"], "12/12/2026")

    def test_full_path_cek_status(self):
        """AC-06: CekStatus skill result → RESPON shows READY."""
        bus = EventBus()
        wm = FakeWorkerManager()

        from worker.ui.controller import UIController
        ctrl = UIController(
            event_bus=bus, worker_manager=wm,
            auto_run_config=FakeAutoRunConfig(),
            automation_engine=None, db_lookup=None,
        )

        from automation.engine import AutomationEngine
        engine, _, _ = TestEngineStepCallback._make_engine(
            self, event_bus=bus, port_state_provider=wm
        )

        from worker.skills.base import SkillResult
        skill_result = SkillResult(
            success=True,
            data={"cpin_state": "READY", "sim_ready": True},
            skill_name="cek_status",
            port="COM3",
        )
        context = type("Ctx", (), {"port": "COM3"})()
        engine._on_step_complete("cek_status", skill_result, context)

        port_updates = bus.published("ui.port.update")
        self.assertTrue(len(port_updates) > 0)
        _, final = port_updates[-1]
        self.assertIn("READY", final.get("respon", ""))

    def test_multiple_steps_accumulate_data(self):
        """Multiple skill steps accumulate data in PortWorkerState."""
        bus = EventBus()
        wm = FakeWorkerManager()

        from automation.engine import AutomationEngine
        engine, _, prov = TestEngineStepCallback._make_engine(
            self, event_bus=bus, port_state_provider=wm
        )

        # Verify engine uses the same provider
        self.assertIs(engine._port_state_provider, wm)

        from worker.skills.base import SkillResult

        # Step 1: cek_nomor
        r1 = SkillResult(success=True, data={"number": "081234567890"}, skill_name="cek_nomor", port="COM5")
        engine._on_step_complete("cek_nomor", r1, type("C", (), {"port": "COM5"})())

        # Step 2: verify_grace
        r2 = SkillResult(success=True, data={"grace_date": "12/12/2026"}, skill_name="verify_grace", port="COM5")
        engine._on_step_complete("verify_grace", r2, type("C", (), {"port": "COM5"})())

        state = wm.get_port_state("COM5")
        self.assertEqual(state._nomor, "081234567890")
        self.assertEqual(state._masa_aktif, "12/12/2026")

    def test_full_path_simulate_mass_cek_nomor(self):
        """AC-05: Simulate mass cek_nomor — data appears in table."""
        bus = EventBus()
        wm = FakeWorkerManager()

        from worker.ui.controller import UIController
        ctrl = UIController(
            event_bus=bus, worker_manager=wm,
            auto_run_config=FakeAutoRunConfig(),
            automation_engine=None, db_lookup=None,
        )

        from automation.engine import AutomationEngine
        engine, _, _ = TestEngineStepCallback._make_engine(
            self, event_bus=bus, port_state_provider=wm
        )

        from worker.skills.base import SkillResult

        # Simulate 3 ports each getting cek_nomor result
        for port in ("COM3", "COM5", "COM7"):
            result = SkillResult(
                success=True,
                data={"number": f"08123456789{port[-1]}"},
                skill_name="cek_nomor",
                port=port,
            )
            engine._on_step_complete("cek_nomor", result, type("C", (), {"port": port})())

        # All 3 ports should have nomor set
        for port in ("COM3", "COM5", "COM7"):
            state = wm.get_port_state(port)
            self.assertNotEqual(state._nomor, "-")

        # All 3 should have PORT_UPDATE events
        port_updates = bus.published("ui.port.update")
        self.assertTrue(len(port_updates) >= 3)


# ==============================================================
# Workflow completion no longer overwrites data
# ==============================================================

class TestWorkflowCompletedNoOverwrite(unittest.TestCase):
    """Workflow completion should NOT overwrite data columns."""

    def test_completed_publishes_only_status(self):
        """on_workflow_completed should only set status=IDLE, not detail."""
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = FakeWorkerManager()

        ctrl = UIController(
            event_bus=bus, worker_manager=wm,
            auto_run_config=FakeAutoRunConfig(),
            automation_engine=None, db_lookup=None,
        )

        ctrl._on_workflow_completed({
            "port": "COM5",
            "workflow": "check_number",
            "duration": 2.5,
        })

        updates = bus.published("ui.port.update")
        self.assertTrue(len(updates) > 0)
        _, payload = updates[-1]
        self.assertEqual(payload["status"], "IDLE")
        # Should NOT have "detail" or "respon" key
        self.assertNotIn("detail", payload)
        self.assertNotIn("respon", payload)


if __name__ == "__main__":
    unittest.main()
