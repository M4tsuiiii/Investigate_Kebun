"""Sprint 15S.2 — Port-Scoped Command Runtime & USSD Cek Nomor.

End-to-end tests covering:
1. Per-port factory dependency resolution
2. CekNomorSkill: AT+CNUM → USSD fallback
3. command_id propagation GUI→Controller→Engine→Runner→Skill
4. COMMAND ACCEPTED vs COMMAND RESULT split
5. SkillDependencyResolver port binding
6. Event subscriptions (CEK_STATUS, RESTART_PORT)
7. Configurable USSD code
8. Context menu event mapping
9. Mass action command_id propagation
10. WorkflowRunner factory resolution
11. SystemBootstrap factory registration
12. Log verification with _CaptureLogs
"""
import logging
import sys
import os
import unittest
import time

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
    def subscribe(self, event, handler):
        self._subs.setdefault(event, []).append(handler)
    def publish(self, event, payload=None):
        for h in self._subs.get(event, []):
            h(payload or {})


# --- Fake classes for testing ---

class FakeAtResponse:
    def __init__(self, success=True, raw=""):
        self.success = success
        self.raw = raw

class FakeAtClient:
    def __init__(self, response=None):
        self._response = response or FakeAtResponse()
    def send_command(self, cmd, timeout=5.0):
        return self._response

class FakeUssdRuntime:
    def __init__(self, response=None):
        self._response = response
        self._last_code = None
    def dial(self, code, timeout=30.0):
        self._last_code = code
        return self._response

class FakeWorkerManager:
    def __init__(self):
        self._workers = {}
    def get_worker(self, port):
        return self._workers.get(port)
    def get_port_state(self, port):
        from app.domain.enums import PortState
        return PortState.ACTIVE
    def get_active_ports(self):
        return list(self._workers.keys())

class FakeWorker:
    def __init__(self):
        self.is_alive = True
        self.modem_online = True
        self.is_connected = True
        self._cpin_state = None
        self._at_client = FakeAtClient()
        self._ussd_runtime = FakeUssdRuntime()
        self._serial = None
        self._cpin_runtime = None
    def get_cpin_state(self):
        return self._cpin_state

    @property
    def cpin_state(self):
        return self._cpin_state

class FakeAutoRunConfig:
    def __init__(self):
        self.auto_run_enabled = False

class FakePortStateProvider:
    def get_port_state(self, port):
        from app.domain.enums import PortState
        return PortState.ACTIVE

class FakeAutomationEngine:
    def __init__(self):
        self.enqueued = []
    def enqueue_workflow(self, port, workflow, priority=10, trigger_id=0):
        self.enqueued.append((port, workflow, priority, trigger_id))
    def handle_trigger(self, trigger, port, *a, **kw):
        pass
    def set_mode_from_name(self, name):
        pass
    def stop(self):
        pass

class FakeDbLookup:
    pass


# ======================================================================
# Category 1: Per-port factory dependency resolution
# ======================================================================

class TestFactoryResolution(unittest.TestCase):

    def test_factory_registered_in_skill_map(self):
        """_wire_skills_for_worker registers factories, not instances."""
        from worker.system_bootstrap import _SkillFactoryBase, _CekNomorSkillFactory
        self.assertTrue(issubclass(_CekNomorSkillFactory, _SkillFactoryBase))

    def test_factory_resolve_returns_skill_instance(self):
        """Factory.resolve() returns a new CekNomorSkill instance."""
        from worker.system_bootstrap import _CekNomorSkillFactory
        from worker.skills.cek_nomor import CekNomorSkill
        from worker.skills.dependency_resolver import SkillDependencyResolver
        factory = _CekNomorSkillFactory()
        resolver = SkillDependencyResolver.__new__(SkillDependencyResolver)
        resolver._port = "COM1"
        resolver._worker_manager = None
        resolver._worker = None
        skill = factory.resolve(resolver)
        self.assertIsInstance(skill, CekNomorSkill)

    def test_different_ports_get_different_skill_instances(self):
        """Each port gets its own skill instance from factory."""
        from worker.system_bootstrap import _CekNomorSkillFactory
        from worker.skills.dependency_resolver import SkillDependencyResolver
        factory = _CekNomorSkillFactory()
        r1 = SkillDependencyResolver.__new__(SkillDependencyResolver)
        r1._port = "COM1"
        r1._worker_manager = None
        r1._worker = None
        r2 = SkillDependencyResolver.__new__(SkillDependencyResolver)
        r2._port = "COM2"
        r2._worker_manager = None
        r2._worker = None
        s1 = factory.resolve(r1)
        s2 = factory.resolve(r2)
        self.assertIsNot(s1, s2)

    def test_all_factory_classes_defined(self):
        """All 8 factory classes exist in system_bootstrap."""
        from worker.system_bootstrap import (
            _CekNomorSkillFactory, _CekStatusSkillFactory, _CekNikSkillFactory,
            _CekKkSkillFactory, _InjectReaktivasiSkillFactory, _VerifyGraceSkillFactory,
            _RestartHardwareSkillFactory, _ResetHardwareSkillFactory, _SkillFactoryBase
        )
        for cls in [_CekNomorSkillFactory, _CekStatusSkillFactory, _CekNikSkillFactory,
                     _CekKkSkillFactory, _InjectReaktivasiSkillFactory, _VerifyGraceSkillFactory,
                     _RestartHardwareSkillFactory, _ResetHardwareSkillFactory]:
            self.assertTrue(issubclass(cls, _SkillFactoryBase), f"{cls.__name__} is not a _SkillFactoryBase")


# ======================================================================
# Category 2: CekNomorSkill — AT+CNUM → USSD fallback
# ======================================================================

class TestCekNomorSkill(unittest.TestCase):

    def test_cnum_success(self):
        """AT+CNUM returns number → skill returns success."""
        from worker.skills.cek_nomor import CekNomorSkill
        at = FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129'))
        skill = CekNomorSkill(at_client=at)
        result = skill.execute(port="COM1")
        self.assertTrue(result.success)
        self.assertEqual(result.data["number"], "081234567890")

    def test_cnum_failure_ussd_fallback(self):
        """AT+CNUM fails → USSD fallback used."""
        from worker.skills.cek_nomor import CekNomorSkill
        at = FakeAtClient(FakeAtResponse(False, "ERROR"))
        ussd = FakeUssdRuntime("Nomor Anda: 081234567890")
        skill = CekNomorSkill(at_client=at, ussd_runtime=ussd)
        result = skill.execute(port="COM1", settings={"workflow": {"number_ussd_code": "*123#"}})
        self.assertTrue(result.success)
        self.assertEqual(result.data["number"], "081234567890")
        self.assertEqual(ussd._last_code, "*123#")

    def test_cnum_no_number_ussd_no_number(self):
        """Both CNUM and USSD fail → skill returns failure."""
        from worker.skills.cek_nomor import CekNomorSkill
        at = FakeAtClient(FakeAtResponse(True, "+CNUM: \"\",,0"))
        ussd = FakeUssdRuntime("Info tidak tersedia")
        skill = CekNomorSkill(at_client=at, ussd_runtime=ussd)
        result = skill.execute(port="COM1", settings={"workflow": {"number_ussd_code": "*123#"}})
        self.assertFalse(result.success)

    def test_no_at_client(self):
        """No AT client → skill returns failure."""
        from worker.skills.cek_nomor import CekNomorSkill
        skill = CekNomorSkill(at_client=None)
        result = skill.execute(port="COM1")
        self.assertFalse(result.success)

    def test_no_ussd_runtime_no_code(self):
        """AT+CNUM fails, no USSD runtime, no code → failure."""
        from worker.skills.cek_nomor import CekNomorSkill
        at = FakeAtClient(FakeAtResponse(False, "ERROR"))
        skill = CekNomorSkill(at_client=at, ussd_runtime=None)
        result = skill.execute(port="COM1")
        self.assertFalse(result.success)

    def test_cnum_parsing_edge_cases(self):
        """Various CNUM response formats."""
        from worker.skills.cek_nomor import CekNomorSkill
        skill = CekNomorSkill(at_client=FakeAtClient())
        self.assertEqual(skill._parse_cnum('+CNUM: "","1234567890",129'), "1234567890")
        self.assertEqual(skill._parse_cnum('+CNUM: "","081234567890",145'), "081234567890")
        self.assertIsNone(skill._parse_cnum(""))
        self.assertIsNone(skill._parse_cnum("ERROR"))

    def test_ussd_number_parsing(self):
        """USSD response number extraction."""
        from worker.skills.cek_nomor import CekNomorSkill
        skill = CekNomorSkill(at_client=FakeAtClient())
        self.assertEqual(skill._parse_ussd_number("Nomor: 081234567890"), "081234567890")
        self.assertEqual(skill._parse_ussd_number("+6281234567890"), "+6281234567890")
        self.assertIsNone(skill._parse_ussd_number("Info tidak tersedia"))


# ======================================================================
# Category 3: command_id propagation GUI→Controller→Engine→Runner→Skill
# ======================================================================

class TestCommandIdPropagation(unittest.TestCase):

    def test_controller_generates_command_id(self):
        """Controller generates incrementing command_id."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        bus = RealBus()
        wm = FakeWorkerManager()
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        cid1 = ctrl._next_command_id()
        cid2 = ctrl._next_command_id()
        self.assertEqual(cid2, cid1 + 1)

    def test_command_id_flows_to_engine(self):
        """Controller passes command_id as trigger_id to engine."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        from worker.ui.events import CommandEvent
        from app.domain.enums import CpinState
        bus = RealBus()
        wm = FakeWorkerManager()
        w = FakeWorker()
        w._cpin_state = CpinState.READY
        wm._workers["COM1"] = w
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        bus.publish(CommandEvent.CEK_NOMOR.value, {"port": "COM1", "source": "test"})
        # Engine should have received the command
        self.assertEqual(len(ae.enqueued), 1)
        _, _, _, trigger_id = ae.enqueued[0]
        self.assertIsInstance(trigger_id, int)
        self.assertGreater(trigger_id, 0)

    def test_command_id_stored_in_command_map(self):
        """command_id is stored in _command_map for result lookup."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        from worker.ui.events import CommandEvent
        from app.domain.enums import CpinState
        bus = RealBus()
        wm = FakeWorkerManager()
        w = FakeWorker()
        w._cpin_state = CpinState.READY
        wm._workers["COM1"] = w
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        bus.publish(CommandEvent.CEK_NOMOR.value, {"port": "COM1", "source": "test"})
        # Should have at least one entry in command_map
        self.assertGreater(len(ctrl._command_map), 0)
        # The command_map entry should match
        _, _, _, trigger_id = ae.enqueued[0]
        entry = ctrl._command_map.get(trigger_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["port"], "COM1")
        self.assertEqual(entry["workflow"], "check_number")


# ======================================================================
# Category 4: COMMAND ACCEPTED vs COMMAND RESULT split
# ======================================================================

class TestAcceptedVsResult(unittest.TestCase):

    def test_accepted_emitted_on_dispatch(self):
        """[COMMAND ACCEPTED] emitted on per-port dispatch, not [COMMAND RESULT]."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        from worker.ui.events import CommandEvent
        from app.domain.enums import CpinState
        bus = RealBus()
        wm = FakeWorkerManager()
        w = FakeWorker()
        w._cpin_state = CpinState.READY
        wm._workers["COM1"] = w
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(CommandEvent.CEK_NOMOR.value, {"port": "COM1", "source": "test"})
        self.assertTrue(cap.has("[COMMAND ACCEPTED]"))
        self.assertFalse(cap.has("[COMMAND RESULT]"))  # not on dispatch

    def test_result_emitted_on_completion(self):
        """[COMMAND RESULT] emitted on workflow completion."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        bus = RealBus()
        wm = FakeWorkerManager()
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            ctrl._on_workflow_completed({"port": "COM1", "workflow": "check_number", "trigger": "manual", "duration": 1.5})
        self.assertTrue(cap.has("[COMMAND RESULT]"))
        self.assertTrue(cap.has("OUTCOME=success"))

    def test_result_emitted_on_failure(self):
        """[COMMAND RESULT] emitted on workflow failure."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        bus = RealBus()
        wm = FakeWorkerManager()
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            ctrl._on_workflow_failed({"port": "COM1", "workflow": "check_number", "error": "timeout"})
        self.assertTrue(cap.has("[COMMAND RESULT]"))
        self.assertTrue(cap.has("OUTCOME=failed"))


# ======================================================================
# Category 5: SkillDependencyResolver port binding
# ======================================================================

class TestSkillDependencyResolver(unittest.TestCase):

    def test_resolver_binds_port(self):
        """Resolver carries port reference."""
        from worker.skills.dependency_resolver import SkillDependencyResolver
        r = SkillDependencyResolver.__new__(SkillDependencyResolver)
        r._port = "COM5"
        r._worker_manager = None
        r._worker = None
        self.assertEqual(r.port, "COM5")

    def test_resolver_logs_binding(self):
        """Resolver logs [SKILL PORT BINDING]."""
        from worker.skills.dependency_resolver import SkillDependencyResolver
        r = SkillDependencyResolver.__new__(SkillDependencyResolver)
        r._port = "COM1"
        r._worker_manager = None
        r._worker = None
        with _CaptureLogs("saiki.skill_resolver") as cap:
            r.log_binding("cek_nomor", "AT_CLIENT", "COM1")
        self.assertTrue(cap.has("[SKILL PORT BINDING]"))
        self.assertTrue(cap.has("SKILL=cek_nomor"))
        self.assertTrue(cap.has("MATCH=YES"))

    def test_resolver_log_binding_no_match(self):
        """Resolver logs MATCH=NO when port differs."""
        from worker.skills.dependency_resolver import SkillDependencyResolver
        r = SkillDependencyResolver.__new__(SkillDependencyResolver)
        r._port = "COM1"
        r._worker_manager = None
        r._worker = None
        with _CaptureLogs("saiki.skill_resolver") as cap:
            r.log_binding("cek_nomor", "AT_CLIENT", "COM2")
        self.assertTrue(cap.has("MATCH=NO"))


# ======================================================================
# Category 6: Event subscriptions
# ======================================================================

class TestEventSubscriptions(unittest.TestCase):

    def test_cek_status_is_in_routes(self):
        """cmd.cek_status is in ROUTE_BY_EVENT."""
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertIn("cmd.cek_status", ROUTE_BY_EVENT)
        self.assertEqual(ROUTE_BY_EVENT["cmd.cek_status"][2], "check_status")

    def test_restart_port_is_in_routes(self):
        """cmd.restart_port is in ROUTE_BY_EVENT."""
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertIn("cmd.restart_port", ROUTE_BY_EVENT)
        self.assertEqual(ROUTE_BY_EVENT["cmd.restart_port"][2], "hardware_restart")

    def test_cek_limit_is_in_routes(self):
        """cmd.cek_limit is in ROUTE_BY_EVENT."""
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertIn("cmd.cek_limit", ROUTE_BY_EVENT)

    def test_all_events_have_routes(self):
        """Every per-port command event has a route."""
        from worker.ui.controller import ROUTE_BY_EVENT
        expected = [
            "cmd.cek_nomor", "cmd.cek_status", "cmd.cek_nik", "cmd.cari_kk",
            "cmd.cek_limit", "cmd.reactivate", "cmd.reset_modem", "cmd.restart_port",
        ]
        for evt in expected:
            self.assertIn(evt, ROUTE_BY_EVENT, f"{evt} missing from routes")


# ======================================================================
# Category 7: Configurable USSD code
# ======================================================================

class TestConfigurableUssd(unittest.TestCase):

    def test_default_ussd_code_empty(self):
        """Settings dialog defaults number_ussd_code to empty."""
        from worker.ui.settings_dialog import load_config
        config = load_config()
        self.assertIn("number_ussd_code", config.get("workflow", {}))

    def test_cek_nomor_reads_ussd_code_from_settings(self):
        """CekNomorSkill reads number_ussd_code from settings."""
        from worker.skills.cek_nomor import CekNomorSkill
        at = FakeAtClient(FakeAtResponse(False, "ERROR"))
        ussd = FakeUssdRuntime("081234567890")
        skill = CekNomorSkill(at_client=at, ussd_runtime=ussd)
        skill.execute(port="COM1", settings={"workflow": {"number_ussd_code": "*999#"}})
        self.assertEqual(ussd._last_code, "*999#")

    def test_cek_nomor_no_ussd_code_when_empty(self):
        """CekNomorSkill returns failure when USSD code is empty and CNUM fails."""
        from worker.skills.cek_nomor import CekNomorSkill
        at = FakeAtClient(FakeAtResponse(False, "ERROR"))
        ussd = FakeUssdRuntime("081234567890")
        skill = CekNomorSkill(at_client=at, ussd_runtime=ussd)
        result = skill.execute(port="COM1", settings={"workflow": {"number_ussd_code": ""}})
        self.assertFalse(result.success)
        self.assertIsNone(ussd._last_code)  # USSD not called


# ======================================================================
# Category 8: Context menu event mapping
# ======================================================================

class TestContextMenuEvents(unittest.TestCase):

    def test_cek_status_in_menu(self):
        """Cek Status SIM mapped to CEK_STATUS."""
        from worker.ui.context_menu import PortContextMenu
        items = {item[0]: item[1] for item in PortContextMenu.MENU_ITEMS if item is not None}
        self.assertIn("Cek Status SIM", items)
        from worker.ui.events import CommandEvent
        self.assertEqual(items["Cek Status SIM"], CommandEvent.CEK_STATUS)

    def test_restart_port_in_menu(self):
        """Restart Port mapped to RESTART_PORT."""
        from worker.ui.context_menu import PortContextMenu
        from worker.ui.events import CommandEvent
        items = {item[0]: item[1] for item in PortContextMenu.MENU_ITEMS if item is not None}
        self.assertEqual(items["Restart Port"], CommandEvent.RESTART_PORT)

    def test_cek_limit_still_in_menu(self):
        """Cek Limit still mapped to CEK_LIMIT."""
        from worker.ui.context_menu import PortContextMenu
        from worker.ui.events import CommandEvent
        items = {item[0]: item[1] for item in PortContextMenu.MENU_ITEMS if item is not None}
        self.assertEqual(items["Cek Limit"], CommandEvent.CEK_LIMIT)

    def test_no_duplicate_events(self):
        """No duplicate CommandEvent values in menu."""
        from worker.ui.context_menu import PortContextMenu
        events = [item[1] for item in PortContextMenu.MENU_ITEMS if item is not None]
        self.assertEqual(len(events), len(set(events)))


# ======================================================================
# Category 9: Mass action command_id propagation
# ======================================================================

class TestMassCommandIdPropagation(unittest.TestCase):

    def test_mass_cek_nomor_uses_port_specific_ids(self):
        """Mass cek nomor gives each port its own command_id."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        from worker.ui.events import CommandEvent
        from app.domain.enums import CpinState
        bus = RealBus()
        wm = FakeWorkerManager()
        for port in ("COM1", "COM2"):
            w = FakeWorker()
            w._cpin_state = CpinState.READY
            wm._workers[port] = w
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {"source": "test"})
        time.sleep(0.5)  # let dispatch thread run
        self.assertEqual(len(ae.enqueued), 2)
        ids = [tid for _, _, _, tid in ae.enqueued]
        self.assertEqual(len(set(ids)), 2)  # all unique


# ======================================================================
# Category 10: WorkflowRunner factory resolution
# ======================================================================

class TestWorkflowRunnerFactoryResolution(unittest.TestCase):

    def test_runner_resolves_factory(self):
        """WorkflowRunner resolves factory instances to real skills."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition
        from worker.system_bootstrap import _CekNomorSkillFactory
        factory_map = {"cek_nomor": _CekNomorSkillFactory()}
        runner = WorkflowRunner(skill_map=factory_map)
        wf = WorkflowDefinition(
            name="check_number", steps=["cek_nomor"],
        )
        with _CaptureLogs("saiki.workflow") as cap:
            result = runner.run(wf, "COM1")
        self.assertTrue(cap.has("SKILL_LOOKUP") or cap.has("stage=SKILL_LOOKUP"))

    def test_runner_passes_command_id_to_skill(self):
        """WorkflowRunner passes trigger_id as command_id to skill execute kwargs."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition
        from worker.skills.base import Skill, SkillResult
        class SpySkill(Skill):
            last_kwargs = {}
            @property
            def name(self): return "spy"
            @property
            def description(self): return "spy"
            def execute(self, port, **kwargs):
                SpySkill.last_kwargs = kwargs
                return SkillResult(success=True, data={})
        spy = SpySkill()
        runner = WorkflowRunner(skill_map={"spy": spy})
        wf = WorkflowDefinition(
            name="spy_wf", steps=["spy"],
        )
        runner.run(wf, "COM1", trigger_id=42)
        self.assertEqual(SpySkill.last_kwargs.get("command_id"), 42)

    def test_runner_sets_port_workers(self):
        """WorkflowRunner accepts port_workers dict."""
        from workflow.runner import WorkflowRunner
        runner = WorkflowRunner(skill_map={})
        pw = {"COM1": "worker1", "COM2": "worker2"}
        runner.set_port_workers(pw)
        self.assertEqual(runner._port_workers, pw)


# ======================================================================
# Category 11: SystemBootstrap factory registration
# ======================================================================

class TestSystemBootstrapFactoryRegistration(unittest.TestCase):

    def test_wire_skills_registers_factories(self):
        """_wire_skills_for_worker registers _SkillFactoryBase subclasses."""
        from worker.system_bootstrap import SystemBootstrap, _SkillFactoryBase
        sb = SystemBootstrap()
        wm = FakeWorkerManager()
        w = FakeWorker()
        wm._workers["COM1"] = w
        sb._worker_manager = wm
        sb._skill_map = {}
        sb._wire_skills_for_worker("COM1", w)
        for name, entry in sb._skill_map.items():
            self.assertTrue(hasattr(entry, 'resolve'), f"{name} is not a factory")

    def test_port_workers_registry_stored(self):
        """SystemBootstrap stores _port_workers mapping."""
        from worker.system_bootstrap import SystemBootstrap
        sb = SystemBootstrap()
        wm = FakeWorkerManager()
        w = FakeWorker()
        wm._workers["COM1"] = w
        sb._worker_manager = wm
        sb._skill_map = {}
        sb._wire_skills_for_worker("COM1", w)
        self.assertIn("COM1", sb._port_workers)


# ======================================================================
# Category 12: Log verification
# ======================================================================

class TestLogVerification(unittest.TestCase):

    def test_cek_nomor_logs_command_id(self):
        """CekNomorSkill logs COMMAND_ID throughout."""
        from worker.skills.cek_nomor import CekNomorSkill
        at = FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129'))
        skill = CekNomorSkill(at_client=at)
        with _CaptureLogs("saiki.skill.cek_nomor") as cap:
            skill.execute(port="COM1", command_id=99)
        self.assertTrue(cap.has("COMMAND_ID=99"))
        self.assertTrue(cap.has("[CEK NOMOR START]"))
        self.assertTrue(cap.has("[CEK NOMOR RESULT]"))

    def test_controller_logs_accepted(self):
        """Controller logs [COMMAND ACCEPTED] on per-port command."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        from worker.ui.events import CommandEvent
        from app.domain.enums import CpinState
        bus = RealBus()
        wm = FakeWorkerManager()
        w = FakeWorker()
        w._cpin_state = CpinState.READY
        wm._workers["COM1"] = w
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(CommandEvent.CEK_NOMOR.value, {"port": "COM1", "source": "test"})
        self.assertTrue(cap.has("[COMMAND ACCEPTED]"))
        self.assertTrue(cap.has("[COMMAND CLICK]"))
        self.assertTrue(cap.has("[COMMAND DISPATCH]"))
        self.assertTrue(cap.has("[COMMAND ENQUEUED]"))

    def test_cek_status_event_published(self):
        """Publishing CEK_STATUS event triggers handler."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        from worker.ui.events import CommandEvent
        from app.domain.enums import CpinState
        bus = RealBus()
        wm = FakeWorkerManager()
        w = FakeWorker()
        w._cpin_state = CpinState.READY
        wm._workers["COM1"] = w
        arc = FakeAutoRunConfig()
        ae = FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(CommandEvent.CEK_STATUS.value, {"port": "COM1", "source": "test"})
        self.assertTrue(cap.has("[COMMAND ACCEPTED]") or cap.has("[COMMAND CLICK]"))


if __name__ == "__main__":
    unittest.main()
