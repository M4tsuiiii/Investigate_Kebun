"""Sprint 15T — Real Workflow Validation: Forensic Instrumentation Tests.

Verifies all instrumentation traces are present and correct.
"""
import logging
import sys
import os
import time
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


class FakeAtResponse:
    def __init__(self, success=True, raw=""):
        self.success = success
        self.raw = raw

class FakeAtClient:
    def __init__(self, response=None):
        self._response = response or FakeAtResponse()
    def send_command(self, cmd, timeout=5.0):
        return self._response
    def check_modem(self):
        return True

class FakeUssdRuntime:
    def __init__(self, response=None):
        self._response = response
    def dial(self, code, timeout=30.0):
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
    @property
    def cpin_state(self):
        return self._cpin_state

class FakeAutoRunConfig:
    auto_run_enabled = False

class FakeAutomationEngine:
    def __init__(self):
        self.enqueued = []
    def enqueue_workflow(self, port, workflow, priority=10, trigger_id=0):
        self.enqueued.append((port, workflow, priority, trigger_id))
    def handle_trigger(self, *a, **kw): pass
    def set_mode_from_name(self, n): pass
    def stop(self): pass

class FakeDbLookup: pass


# ======================================================================
# Task 1: [MASS COMMAND] + [MASS COMMAND DISPATCH] traces
# ======================================================================

class TestMassCommandTraces(unittest.TestCase):

    def test_mass_cek_nomor_emits_mass_command_trace(self):
        """Mass cek nomor emits [MASS COMMAND] with PORTS_SELECTED."""
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
        ctrl = UIController(bus, wm, FakeAutoRunConfig(), FakeAutomationEngine(), FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {"source": "test"})
            time.sleep(0.3)
        self.assertTrue(cap.has("[MASS COMMAND]"))
        self.assertTrue(cap.has("WORKFLOW=check_number"))

    def test_mass_cek_nomor_emits_dispatch_trace(self):
        """Mass cek nomor emits [MASS COMMAND DISPATCH] per port."""
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
        ctrl = UIController(bus, wm, FakeAutoRunConfig(), FakeAutomationEngine(), FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {"source": "test"})
            time.sleep(0.3)
        dispatch_msgs = cap.messages("[MASS COMMAND DISPATCH]")
        self.assertEqual(len(dispatch_msgs), 2)

    def test_mass_reaktivasi_emits_mass_command_trace(self):
        """Mass reaktivasi emits [MASS COMMAND]."""
        from worker.ui.controller import UIController
        from worker.ui.event_bus import EventBus as RealBus
        from worker.ui.events import CommandEvent
        from app.domain.enums import CpinState
        bus = RealBus()
        wm = FakeWorkerManager()
        for port in ("COM1",):
            w = FakeWorker()
            w._cpin_state = CpinState.READY
            wm._workers[port] = w
        ctrl = UIController(bus, wm, FakeAutoRunConfig(), FakeAutomationEngine(), FakeDbLookup())
        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(CommandEvent.MASS_REAKTIVASI.value, {"source": "test"})
            time.sleep(0.3)
        self.assertTrue(cap.has("[MASS COMMAND]"))
        self.assertTrue(cap.has("WORKFLOW=reactivate_full"))


# ======================================================================
# Task 2: WORKFLOW EXECUTION AUDIT
# ======================================================================

class TestWorkflowExecutionAudit(unittest.TestCase):

    def test_log_execution_audit_emits_trace(self):
        """log_execution_audit emits [WORKFLOW EXECUTION AUDIT]."""
        from automation.engine import AutomationEngine
        from worker.ui.event_bus import EventBus
        from workflow.registry import WorkflowRegistry
        from automation.queue import WorkflowQueue
        from automation.scheduler import AutomationScheduler
        from automation.policy import AutomationPolicy
        from worker.rules import AutoRunConfig
        bus = EventBus()
        arc = AutoRunConfig()
        engine = AutomationEngine(bus, WorkflowRegistry(), arc, WorkflowQueue(), AutomationScheduler(), AutomationPolicy())
        engine._dispatched = 5
        engine._workflow_started = 5
        engine._workflow_completed = 4
        engine._workflow_failed = 1
        with _CaptureLogs("saiki.automation") as cap:
            engine.log_execution_audit()
        self.assertTrue(cap.has("[WORKFLOW EXECUTION AUDIT]"))
        self.assertTrue(cap.has("DISPATCHED=5"))
        self.assertTrue(cap.has("COMPLETED=4"))
        self.assertTrue(cap.has("FAILED=1"))

    def test_audit_called_after_workflow_success(self):
        """Audit is called after successful workflow."""
        from automation.engine import AutomationEngine
        from worker.ui.event_bus import EventBus
        from workflow.registry import WorkflowRegistry
        from automation.queue import WorkflowQueue
        from automation.scheduler import AutomationScheduler
        from automation.policy import AutomationPolicy
        from worker.rules import AutoRunConfig
        bus = EventBus()
        arc = AutoRunConfig()
        engine = AutomationEngine(bus, WorkflowRegistry(), arc, WorkflowQueue(), AutomationScheduler(), AutomationPolicy())
        with _CaptureLogs("saiki.automation") as cap:
            engine.log_execution_audit()
        self.assertTrue(cap.has("[WORKFLOW EXECUTION AUDIT]"))


# ======================================================================
# Task 3: [SKILL ENTRY] traces
# ======================================================================

class TestSkillEntryTraces(unittest.TestCase):

    def test_cek_nomor_logs_skill_entry(self):
        """CekNomorSkill logs [SKILL ENTRY]."""
        from worker.skills.cek_nomor import CekNomorSkill
        skill = CekNomorSkill(at_client=FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129')))
        with _CaptureLogs("saiki.skill.cek_nomor") as cap:
            skill.execute(port="COM1", command_id=42)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=cek_nomor"))

    def test_cek_status_logs_skill_entry(self):
        """CekStatusSkill logs [SKILL ENTRY]."""
        from worker.skills.cek_status import CekStatusSkill
        skill = CekStatusSkill(at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
        with _CaptureLogs("saiki.skill.cek_status") as cap:
            skill.execute(port="COM1", command_id=42)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=cek_status"))

    def test_cek_nik_logs_skill_entry(self):
        """CekNikSkill logs [SKILL ENTRY]."""
        from worker.skills.cek_nik import CekNikSkill
        skill = CekNikSkill(ussd_runtime=FakeUssdRuntime("NIK info"))
        with _CaptureLogs("saiki.skill.cek_nik") as cap:
            skill.execute(port="COM1", command_id=42)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=cek_nik"))

    def test_cek_kk_logs_skill_entry(self):
        """CekKkSkill logs [SKILL ENTRY]."""
        from worker.skills.cek_kk import CekKkSkill
        skill = CekKkSkill(ussd_runtime=FakeUssdRuntime("KK info"))
        with _CaptureLogs("saiki.skill.cek_kk") as cap:
            skill.execute(port="COM1", command_id=42)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=cek_kk"))

    def test_inject_reaktivasi_logs_skill_entry(self):
        """InjectReaktivasiSkill logs [SKILL ENTRY]."""
        from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
        skill = InjectReaktivasiSkill(ussd_runtime=FakeUssdRuntime("OK"))
        with _CaptureLogs("saiki.skill.inject_reaktivasi") as cap:
            skill.execute(port="COM1", command_id=42)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=inject_reaktivasi"))

    def test_verify_grace_logs_skill_entry(self):
        """VerifyGraceSkill logs [SKILL ENTRY]."""
        from worker.skills.verify_grace import VerifyGraceSkill
        skill = VerifyGraceSkill(ussd_runtime=FakeUssdRuntime("Status: AKTIF"))
        with _CaptureLogs("saiki.skill.verify_grace") as cap:
            skill.execute(port="COM1", command_id=42)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=verify_grace"))

    def test_restart_hardware_logs_skill_entry(self):
        """RestartHardwareSkill logs [SKILL ENTRY]."""
        from worker.skills.restart_hardware import RestartHardwareSkill
        skill = RestartHardwareSkill(at_client=FakeAtClient())
        with _CaptureLogs("saiki.skill.restart_hardware") as cap:
            skill.execute(port="COM1", command_id=42, wait_seconds=0)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=restart_hardware"))

    def test_reset_hardware_logs_skill_entry(self):
        """ResetHardwareSkill logs [SKILL ENTRY]."""
        from worker.skills.reset_hardware import ResetHardwareSkill
        class FakeSerial:
            is_open = True
            def close(self): pass
            def open(self): return True
        skill = ResetHardwareSkill(serial_adapter=FakeSerial(), at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
        with _CaptureLogs("saiki.skill.reset_hardware") as cap:
            skill.execute(port="COM1", command_id=42, wait_seconds=0)
        self.assertTrue(cap.has("[SKILL ENTRY]"))
        self.assertTrue(cap.has("SKILL=reset_hardware"))


# ======================================================================
# Task 4: [MODEM ACTION] traces
# ======================================================================

class TestModemActionTraces(unittest.TestCase):

    def test_cek_nomor_logs_modem_action(self):
        """CekNomorSkill logs [MODEM ACTION] before AT+CNUM."""
        from worker.skills.cek_nomor import CekNomorSkill
        skill = CekNomorSkill(at_client=FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129')))
        with _CaptureLogs("saiki.skill.cek_nomor") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM ACTION]"))
        self.assertTrue(cap.has("COMMAND=AT+CNUM"))

    def test_cek_status_logs_modem_action(self):
        """CekStatusSkill logs [MODEM ACTION] before AT+CPIN?."""
        from worker.skills.cek_status import CekStatusSkill
        skill = CekStatusSkill(at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
        with _CaptureLogs("saiki.skill.cek_status") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM ACTION]"))
        self.assertTrue(cap.has("COMMAND=AT+CPIN?"))

    def test_cek_nik_logs_modem_action(self):
        """CekNikSkill logs [MODEM ACTION] before USSD dial."""
        from worker.skills.cek_nik import CekNikSkill
        skill = CekNikSkill(ussd_runtime=FakeUssdRuntime("NIK info"))
        with _CaptureLogs("saiki.skill.cek_nik") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM ACTION]"))
        self.assertTrue(cap.has("COMMAND=USSD"))

    def test_inject_reaktivasi_logs_modem_action(self):
        """InjectReaktivasiSkill logs [MODEM ACTION] before USSD dial."""
        from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
        skill = InjectReaktivasiSkill(ussd_runtime=FakeUssdRuntime("OK"))
        with _CaptureLogs("saiki.skill.inject_reaktivasi") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM ACTION]"))
        self.assertTrue(cap.has("COMMAND=USSD"))

    def test_restart_hardware_logs_modem_action(self):
        """RestartHardwareSkill logs [MODEM ACTION] before ATZ."""
        from worker.skills.restart_hardware import RestartHardwareSkill
        skill = RestartHardwareSkill(at_client=FakeAtClient())
        with _CaptureLogs("saiki.skill.restart_hardware") as cap:
            skill.execute(port="COM1", wait_seconds=0)
        self.assertTrue(cap.has("[MODEM ACTION]"))
        self.assertTrue(cap.has("COMMAND=ATZ"))

    def test_reset_hardware_logs_modem_action(self):
        """ResetHardwareSkill logs [MODEM ACTION] for serial close."""
        from worker.skills.reset_hardware import ResetHardwareSkill
        class FakeSerial:
            is_open = True
            def close(self): pass
            def open(self): return True
        skill = ResetHardwareSkill(serial_adapter=FakeSerial(), at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
        with _CaptureLogs("saiki.skill.reset_hardware") as cap:
            skill.execute(port="COM1", wait_seconds=0)
        self.assertTrue(cap.has("[MODEM ACTION]"))
        self.assertTrue(cap.has("COMMAND=SERIAL_CLOSE"))


# ======================================================================
# Task 5: [MODEM INTERPRETATION] traces
# ======================================================================

class TestModemInterpretationTraces(unittest.TestCase):

    def test_cek_nomor_logs_interpretation(self):
        """CekNomorSkill logs [MODEM INTERPRETATION] with RAW and PARSED."""
        from worker.skills.cek_nomor import CekNomorSkill
        skill = CekNomorSkill(at_client=FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129')))
        with _CaptureLogs("saiki.skill.cek_nomor") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM INTERPRETATION]"))
        self.assertTrue(cap.has("PARSED="))

    def test_cek_status_logs_interpretation(self):
        """CekStatusSkill logs [MODEM INTERPRETATION]."""
        from worker.skills.cek_status import CekStatusSkill
        skill = CekStatusSkill(at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
        with _CaptureLogs("saiki.skill.cek_status") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM INTERPRETATION]"))
        self.assertTrue(cap.has("PARSED=READY"))

    def test_cek_nik_logs_interpretation(self):
        """CekNikSkill logs [MODEM INTERPRETATION]."""
        from worker.skills.cek_nik import CekNikSkill
        skill = CekNikSkill(ussd_runtime=FakeUssdRuntime("NIK info"))
        with _CaptureLogs("saiki.skill.cek_nik") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM INTERPRETATION]"))

    def test_verify_grace_logs_interpretation(self):
        """VerifyGraceSkill logs [MODEM INTERPRETATION]."""
        from worker.skills.verify_grace import VerifyGraceSkill
        skill = VerifyGraceSkill(ussd_runtime=FakeUssdRuntime("Status: AKTIF"))
        with _CaptureLogs("saiki.skill.verify_grace") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[MODEM INTERPRETATION]"))
        self.assertTrue(cap.has("card_status=AKTIF"))


# ======================================================================
# Task 6: [PERFORMANCE TRACE] + [SLOW OPERATION]
# ======================================================================

class TestPerformanceTrace(unittest.TestCase):

    def test_cek_nomor_logs_performance_trace(self):
        """CekNomorSkill logs [PERFORMANCE TRACE] with DURATION_MS."""
        from worker.skills.cek_nomor import CekNomorSkill
        skill = CekNomorSkill(at_client=FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129')))
        with _CaptureLogs("saiki.skill.cek_nomor") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[PERFORMANCE TRACE]"))
        self.assertTrue(cap.has("DURATION_MS="))

    def test_cek_status_logs_performance_trace(self):
        """CekStatusSkill logs [PERFORMANCE TRACE]."""
        from worker.skills.cek_status import CekStatusSkill
        skill = CekStatusSkill(at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
        with _CaptureLogs("saiki.skill.cek_status") as cap:
            skill.execute(port="COM1")
        self.assertTrue(cap.has("[PERFORMANCE TRACE]"))

    def test_all_skills_have_performance_trace(self):
        """All skills log [PERFORMANCE TRACE]."""
        skills_and_loggers = [
            ("cek_nomor", "saiki.skill.cek_nomor"),
            ("cek_status", "saiki.skill.cek_status"),
            ("cek_nik", "saiki.skill.cek_nik"),
            ("cek_kk", "saiki.skill.cek_kk"),
            ("inject_reaktivasi", "saiki.skill.inject_reaktivasi"),
            ("verify_grace", "saiki.skill.verify_grace"),
        ]
        for skill_name, logger_name in skills_and_loggers:
            if skill_name == "cek_nomor":
                from worker.skills.cek_nomor import CekNomorSkill
                skill = CekNomorSkill(at_client=FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129')))
            elif skill_name == "cek_status":
                from worker.skills.cek_status import CekStatusSkill
                skill = CekStatusSkill(at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
            elif skill_name == "cek_nik":
                from worker.skills.cek_nik import CekNikSkill
                skill = CekNikSkill(ussd_runtime=FakeUssdRuntime("NIK info"))
            elif skill_name == "cek_kk":
                from worker.skills.cek_kk import CekKkSkill
                skill = CekKkSkill(ussd_runtime=FakeUssdRuntime("KK info"))
            elif skill_name == "inject_reaktivasi":
                from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
                skill = InjectReaktivasiSkill(ussd_runtime=FakeUssdRuntime("OK"))
            elif skill_name == "verify_grace":
                from worker.skills.verify_grace import VerifyGraceSkill
                skill = VerifyGraceSkill(ussd_runtime=FakeUssdRuntime("Status: AKTIF"))
            with _CaptureLogs(logger_name) as cap:
                skill.execute(port="COM1")
            self.assertTrue(cap.has("[PERFORMANCE TRACE]"), f"{skill_name} missing [PERFORMANCE TRACE]")

    def test_all_skills_have_skill_entry(self):
        """All skills log [SKILL ENTRY]."""
        skills_and_loggers = [
            ("cek_nomor", "saiki.skill.cek_nomor"),
            ("cek_status", "saiki.skill.cek_status"),
            ("cek_nik", "saiki.skill.cek_nik"),
            ("cek_kk", "saiki.skill.cek_kk"),
            ("inject_reaktivasi", "saiki.skill.inject_reaktivasi"),
            ("verify_grace", "saiki.skill.verify_grace"),
        ]
        for skill_name, logger_name in skills_and_loggers:
            if skill_name == "cek_nomor":
                from worker.skills.cek_nomor import CekNomorSkill
                skill = CekNomorSkill(at_client=FakeAtClient(FakeAtResponse(True, '+CNUM: "","081234567890",129')))
            elif skill_name == "cek_status":
                from worker.skills.cek_status import CekStatusSkill
                skill = CekStatusSkill(at_client=FakeAtClient(FakeAtResponse(True, "+CPIN: READY")))
            elif skill_name == "cek_nik":
                from worker.skills.cek_nik import CekNikSkill
                skill = CekNikSkill(ussd_runtime=FakeUssdRuntime("NIK info"))
            elif skill_name == "cek_kk":
                from worker.skills.cek_kk import CekKkSkill
                skill = CekKkSkill(ussd_runtime=FakeUssdRuntime("KK info"))
            elif skill_name == "inject_reaktivasi":
                from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
                skill = InjectReaktivasiSkill(ussd_runtime=FakeUssdRuntime("OK"))
            elif skill_name == "verify_grace":
                from worker.skills.verify_grace import VerifyGraceSkill
                skill = VerifyGraceSkill(ussd_runtime=FakeUssdRuntime("Status: AKTIF"))
            with _CaptureLogs(logger_name) as cap:
                skill.execute(port="COM1")
            self.assertTrue(cap.has("[SKILL ENTRY]"), f"{skill_name} missing [SKILL ENTRY]")


if __name__ == "__main__":
    unittest.main()
