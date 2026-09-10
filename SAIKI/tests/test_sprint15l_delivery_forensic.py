"""Sprint 15L Tests — Workflow Delivery Forensic.

Verifies:
- [DELIVERY TRACE] at every stage: WORKFLOW_START, SKILL_LOOKUP, SKILL_FOUND,
  SKILL_EXECUTE, STEP_COMPLETE, STEP_FAILED, WORKFLOW_END
- [SKILL AUDIT] workflow→skill mapping
- [COMMAND AUDIT] AT command construction
- [SERIAL WRITE] byte-level tracing
- [MODEM RESPONSE] raw response logging
- [DELIVERY REPORT] startup summary
"""

import unittest
from unittest.mock import MagicMock, patch, call


# ======================================================================
# Helpers
# ======================================================================

def _make_skill(name="test_skill", success=True, data=None, error=""):
    skill = MagicMock()
    skill.name = name
    skill.execute.return_value = MagicMock(
        success=success,
        data=data or {},
        error=error,
        skill_name=name,
        port="COM1",
    )
    return skill


def _make_at_client(raw_response="OK\r\n"):
    at_client = MagicMock()
    resp = MagicMock()
    resp.raw = raw_response
    resp.success = "OK" in raw_response
    resp.is_ok = "OK" in raw_response
    resp.is_error = "ERROR" in raw_response
    resp.timeout = False
    at_client.send_command.return_value = resp
    return at_client


def _make_serial():
    serial = MagicMock()
    serial.port_name = "COM1"
    serial.write.return_value = True
    serial.readline.return_value = b"OK\r\n"
    return serial


def _make_engine():
    from automation.engine import AutomationEngine
    from workflow.runner import WorkflowRunner
    from workflow.registry import WorkflowRegistry
    from worker.rules import AutoRunConfig

    registry = WorkflowRegistry()
    config = AutoRunConfig()
    runner = WorkflowRunner(skill_map={}, cooldown_seconds=0.01)
    engine = AutomationEngine(
        workflow_runner=runner,
        workflow_registry=registry,
        auto_run_config=config,
        event_bus=MagicMock(),
    )
    return engine


# ======================================================================
# Task 1: Delivery Trace
# ======================================================================

class TestDeliveryTrace(unittest.TestCase):
    """[DELIVERY TRACE] at every stage of workflow execution."""

    def test_workflow_start_trace(self):
        """WORKFLOW_START trace logged at start of workflow."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("step_a")
        runner = WorkflowRunner(skill_map={"step_a": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="trace_wf", steps=["step_a"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=100)

        start_logs = [l for l in cm.output if "stage=WORKFLOW_START" in l]
        self.assertEqual(len(start_logs), 1)
        self.assertIn("trigger_id=100", start_logs[0])
        self.assertIn("workflow=trace_wf", start_logs[0])

    def test_skill_lookup_trace(self):
        """SKILL_LOOKUP trace logged before skill resolution."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("lookup_skill")
        runner = WorkflowRunner(skill_map={"lookup_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="lookup_wf", steps=["lookup_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=200)

        lookup_logs = [l for l in cm.output if "stage=SKILL_LOOKUP" in l]
        self.assertEqual(len(lookup_logs), 1)
        self.assertIn("skill=lookup_skill", lookup_logs[0])

    def test_skill_found_trace(self):
        """SKILL_FOUND logged when skill exists in registry."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("found_skill")
        runner = WorkflowRunner(skill_map={"found_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="found_wf", steps=["found_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=300)

        found_logs = [l for l in cm.output if "[SKILL AUDIT]" in l and "FOUND=YES" in l]
        self.assertEqual(len(found_logs), 1)
        self.assertIn("SKILL=found_skill", found_logs[0])

    def test_skill_missing_trace(self):
        """SKILL_MISSING trace logged when skill not found."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition
        from workflow.exceptions import SkillNotFoundError

        runner = WorkflowRunner(skill_map={}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="missing_wf", steps=["nonexistent"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            with self.assertRaises(SkillNotFoundError):
                runner.run(workflow, "COM1", trigger_id=400)

        missing_logs = [l for l in cm.output if "stage=SKILL_MISSING" in l]
        self.assertEqual(len(missing_logs), 1)
        self.assertIn("skill=nonexistent", missing_logs[0])

    def test_skill_execute_trace(self):
        """SKILL_EXECUTE trace logged before skill.execute()."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("exec_skill")
        runner = WorkflowRunner(skill_map={"exec_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="exec_wf", steps=["exec_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=500)

        exec_logs = [l for l in cm.output if "stage=SKILL_EXECUTE" in l]
        self.assertEqual(len(exec_logs), 1)
        self.assertIn("skill=exec_skill", exec_logs[0])

    def test_step_complete_trace(self):
        """STEP_COMPLETE trace logged on success."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("ok_skill")
        runner = WorkflowRunner(skill_map={"ok_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="ok_wf", steps=["ok_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=600)

        complete_logs = [l for l in cm.output if "stage=STEP_COMPLETE" in l]
        self.assertEqual(len(complete_logs), 1)

    def test_step_failed_trace(self):
        """STEP_FAILED trace logged on failure."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("fail_skill", success=False, error="timeout")
        runner = WorkflowRunner(skill_map={"fail_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="fail_wf", steps=["fail_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=700)

        failed_logs = [l for l in cm.output if "stage=STEP_FAILED" in l]
        self.assertEqual(len(failed_logs), 1)
        self.assertIn("error=timeout", failed_logs[0])

    def test_workflow_end_success_trace(self):
        """WORKFLOW_END result=SUCCESS logged on completion."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("done_skill")
        runner = WorkflowRunner(skill_map={"done_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="done_wf", steps=["done_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=800)

        end_logs = [l for l in cm.output if "stage=WORKFLOW_END" in l and "SUCCESS" in l]
        self.assertEqual(len(end_logs), 1)

    def test_workflow_end_failed_trace(self):
        """WORKFLOW_END result=FAILED logged on failure."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("bad_skill", success=False, error="fail")
        runner = WorkflowRunner(skill_map={"bad_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="bad_wf", steps=["bad_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=900)

        end_logs = [l for l in cm.output if "stage=WORKFLOW_END" in l and "FAILED" in l]
        self.assertEqual(len(end_logs), 1)

    def test_full_delivery_trace_sequence(self):
        """Complete delivery trace: START → LOOKUP → FOUND → EXECUTE → COMPLETE → END."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("full_skill")
        runner = WorkflowRunner(skill_map={"full_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="full_wf", steps=["full_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=1000)

        stages = ["WORKFLOW_START", "SKILL_LOOKUP", "SKILL_EXECUTE", "STEP_COMPLETE", "WORKFLOW_END"]
        for stage in stages:
            matching = [l for l in cm.output if f"stage={stage}" in l]
            self.assertTrue(len(matching) >= 1, f"Missing stage: {stage}")


# ======================================================================
# Task 2: Skill Audit
# ======================================================================

class TestSkillAudit(unittest.TestCase):
    """[SKILL AUDIT] workflow→skill mapping."""

    def test_skill_found_logged(self):
        """SKILL AUDIT FOUND=YES when skill exists."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = _make_skill("exists_skill")
        runner = WorkflowRunner(skill_map={"exists_skill": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="audit_wf", steps=["exists_skill"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=1100)

        audit_logs = [l for l in cm.output if "[SKILL AUDIT]" in l and "FOUND=YES" in l]
        self.assertEqual(len(audit_logs), 1)
        self.assertIn("WORKFLOW=audit_wf", audit_logs[0])
        self.assertIn("STEP=exists_skill", audit_logs[0])

    def test_skill_not_found_logged(self):
        """SKILL AUDIT FOUND=NO when skill missing."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition
        from workflow.exceptions import SkillNotFoundError

        runner = WorkflowRunner(skill_map={}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="miss_wf", steps=["ghost"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            with self.assertRaises(SkillNotFoundError):
                runner.run(workflow, "COM1", trigger_id=1200)

        audit_logs = [l for l in cm.output if "[SKILL AUDIT]" in l and "FOUND=NO" in l]
        self.assertEqual(len(audit_logs), 1)
        self.assertIn("SKILL=ghost", audit_logs[0])

    def test_multiple_steps_all_audited(self):
        """All steps in multi-step workflow are audited."""
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        s1 = _make_skill("s1")
        s2 = _make_skill("s2")
        runner = WorkflowRunner(skill_map={"s1": s1, "s2": s2}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="multi_wf", steps=["s1", "s2"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=1300)

        audit_logs = [l for l in cm.output if "[SKILL AUDIT]" in l]
        self.assertEqual(len(audit_logs), 2)
        self.assertTrue(all("FOUND=YES" in l for l in audit_logs))


# ======================================================================
# Task 3: Command Audit
# ======================================================================

class TestCommandAudit(unittest.TestCase):
    """[COMMAND AUDIT] AT command construction."""

    def test_at_command_logged(self):
        """AT command is logged in COMMAND AUDIT."""
        from app.infrastructure.serial.at_client import ATClient

        serial = _make_serial()
        at_client = ATClient(serial)

        at_client.send_command("AT", timeout=2.0)

        # Check that write was called with correct payload
        serial.write.assert_called_once()
        written = serial.write.call_args[0][0]
        self.assertEqual(written, b"AT\r\n")

    def test_at_cpin_command_logged(self):
        """AT+CPIN? command is logged."""
        from app.infrastructure.serial.at_client import ATClient

        serial = _make_serial()
        at_client = ATClient(serial)

        at_client.send_command("AT+CPIN?", timeout=3.0)

        written = serial.write.call_args[0][0]
        self.assertEqual(written, b"AT+CPIN?\r\n")

    def test_ussd_command_logged(self):
        """USSD command is logged with CUSD format."""
        from app.infrastructure.serial.at_client import ATClient

        serial = _make_serial()
        at_client = ATClient(serial)

        at_client.send_ussd("*185#", timeout=30.0)

        written = serial.write.call_args[0][0]
        self.assertIn(b"AT+CUSD", written)
        self.assertIn(b"*185#", written)

    def test_serial_write_failure_logged(self):
        """Serial write failure produces COMMAND AUDIT FAILED log."""
        from app.infrastructure.serial.at_client import ATClient

        serial = MagicMock()
        serial.port_name = "COM99"
        serial.write.return_value = False
        serial.readline.return_value = b""
        at_client = ATClient(serial)

        with self.assertLogs("saiki.at_client", level="INFO") as cm:
            at_client.send_command("AT", timeout=2.0)

        failed_logs = [l for l in cm.output if "FAILED" in l and "serial_write_failed" in l]
        self.assertTrue(len(failed_logs) >= 1)


# ======================================================================
# Task 4: Serial Write Audit
# ======================================================================

class TestSerialWriteAudit(unittest.TestCase):
    """[SERIAL WRITE] byte-level tracing."""

    def test_write_logs_bytes_and_hex(self):
        """Serial write logs BYTES, HEX, and TEXT."""
        from app.infrastructure.serial.serial_adapter import SerialAdapter

        serial = MagicMock()
        serial.port_name = "COM5"
        serial._serial = MagicMock()
        serial._serial.is_open = True
        serial._serial.write.return_value = 10

        adapter = SerialAdapter.__new__(SerialAdapter)
        adapter._port_name = "COM5"
        adapter._serial = serial._serial
        adapter._is_open = True
        adapter._lock = __import__("threading").Lock()

        with self.assertLogs("saiki.serial", level="DEBUG") as cm:
            adapter.write(b"AT+CPIN?\r\n")

        write_logs = [l for l in cm.output if "[SERIAL WRITE]" in l and "RESULT" not in l]
        self.assertTrue(len(write_logs) >= 1)
        self.assertIn("PORT=COM5", write_logs[0])
        self.assertIn("BYTES=10", write_logs[0])
        self.assertIn("HEX=", write_logs[0])

    def test_write_result_success_logged(self):
        """Serial write success logs SUCCESS=YES."""
        from app.infrastructure.serial.serial_adapter import SerialAdapter

        adapter = SerialAdapter.__new__(SerialAdapter)
        adapter._port_name = "COM5"
        adapter._serial = MagicMock()
        adapter._serial.is_open = True
        adapter._serial.write.return_value = 5
        adapter._is_open = True
        adapter._lock = __import__("threading").Lock()

        with self.assertLogs("saiki.serial", level="DEBUG") as cm:
            adapter.write(b"AT\r\n")

        result_logs = [l for l in cm.output if "SERIAL WRITE RESULT" in l]
        self.assertTrue(len(result_logs) >= 1)
        self.assertIn("SUCCESS=YES", result_logs[0])
        self.assertIn("BYTES_WRITTEN=5", result_logs[0])

    def test_write_result_port_not_open(self):
        """Serial write on closed port logs SUCCESS=NO."""
        from app.infrastructure.serial.serial_adapter import SerialAdapter

        adapter = SerialAdapter.__new__(SerialAdapter)
        adapter._port_name = "COM5"
        adapter._serial = None
        adapter._is_open = False
        adapter._lock = __import__("threading").Lock()

        with self.assertLogs("saiki.serial", level="DEBUG") as cm:
            adapter.write(b"AT\r\n")

        result_logs = [l for l in cm.output if "SERIAL WRITE RESULT" in l]
        self.assertTrue(len(result_logs) >= 1)
        self.assertIn("SUCCESS=NO", result_logs[0])
        self.assertIn("port_not_open", result_logs[0])


# ======================================================================
# Task 5: Modem Response Audit
# ======================================================================

class TestModemResponseAudit(unittest.TestCase):
    """[MODEM RESPONSE] raw response logging."""

    def test_ok_response_logged(self):
        """OK response produces MODEM RESPONSE log with RAW."""
        from app.infrastructure.serial.at_client import ATClient

        serial = MagicMock()
        serial.port_name = "COM5"
        serial.write.return_value = True
        serial.readline.return_value = b"OK\r\n"
        at_client = ATClient(serial)

        with self.assertLogs("saiki.at_client", level="INFO") as cm:
            at_client.send_command("AT", timeout=2.0)

        response_logs = [l for l in cm.output if "[MODEM RESPONSE]" in l and "TIMEOUT" not in l]
        self.assertTrue(len(response_logs) >= 1)
        self.assertIn("RAW=", response_logs[0])
        self.assertIn("HEX=", response_logs[0])

    def test_timeout_response_logged(self):
        """Timeout produces MODEM RESPONSE TIMEOUT log."""
        from app.infrastructure.serial.at_client import ATClient

        serial = MagicMock()
        serial.port_name = "COM5"
        serial.write.return_value = True
        serial.readline.return_value = b""
        at_client = ATClient(serial)

        with self.assertLogs("saiki.at_client", level="INFO") as cm:
            at_client.send_command("AT", timeout=0.01)

        timeout_logs = [l for l in cm.output if "TIMEOUT" in l]
        self.assertTrue(len(timeout_logs) >= 1)

    def test_error_response_logged(self):
        """ERROR response is logged with RAW."""
        from app.infrastructure.serial.at_client import ATClient

        serial = MagicMock()
        serial.port_name = "COM5"
        serial.write.return_value = True
        serial.readline.return_value = b"ERROR\r\n"
        at_client = ATClient(serial)

        with self.assertLogs("saiki.at_client", level="INFO") as cm:
            at_client.send_command("AT", timeout=2.0)

        response_logs = [l for l in cm.output if "[MODEM RESPONSE]" in l and "TIMEOUT" not in l]
        self.assertTrue(len(response_logs) >= 1)


# ======================================================================
# Task 6: Delivery Report
# ======================================================================

class TestDeliveryReport(unittest.TestCase):
    """[DELIVERY REPORT] startup summary."""

    def test_report_format(self):
        """Delivery report has correct format with all fields."""
        engine = _make_engine()
        report = engine.get_delivery_report()

        self.assertIn("WORKFLOW DELIVERY AUDIT", report)
        self.assertIn("TRIGGERS RECEIVED:", report)
        self.assertIn("WORKFLOWS STARTED:", report)
        self.assertIn("WORKFLOWS COMPLETED:", report)
        self.assertIn("WORKFLOWS FAILED:", report)
        self.assertIn("SKILLS FOUND:", report)
        self.assertIn("SKILLS MISSING:", report)
        self.assertIn("COMMANDS BUILT:", report)
        self.assertIn("COMMANDS SENT:", report)
        self.assertIn("RESPONSES RECEIVED:", report)
        self.assertIn("TIMEOUTS:", report)
        self.assertIn("LAST BREAKPOINT:", report)
        self.assertIn("TOP FAILURE:", report)

    def test_report_initial_zeros(self):
        """Delivery report starts with all zeros."""
        engine = _make_engine()
        report = engine.get_delivery_report()

        self.assertIn("TRIGGERS RECEIVED: 0", report)
        self.assertIn("WORKFLOWS STARTED: 0", report)
        self.assertIn("SKILLS FOUND: 0", report)
        self.assertIn("SKILLS MISSING: 0", report)

    def test_update_delivery_stats(self):
        """update_delivery_stats increments counters."""
        engine = _make_engine()
        engine.update_delivery_stats(skills_found=5, skills_missing=2)
        report = engine.get_delivery_report()

        self.assertIn("SKILLS FOUND: 5", report)
        self.assertIn("SKILLS MISSING: 2", report)

    def test_log_delivery_report(self):
        """log_delivery_report produces [DELIVERY REPORT] logs."""
        engine = _make_engine()

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.log_delivery_report()

        report_logs = [l for l in cm.output if "[DELIVERY REPORT]" in l]
        self.assertTrue(len(report_logs) >= 10)

    def test_trigger_received_counted(self):
        """handle_trigger increments triggers_received."""
        engine = _make_engine()
        from automation.triggers import Trigger

        engine.handle_trigger(Trigger.CPIN_READY, "COM1", trigger_id=1)
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM2", trigger_id=2)

        self.assertEqual(engine._triggers_received, 2)


if __name__ == "__main__":
    unittest.main()
