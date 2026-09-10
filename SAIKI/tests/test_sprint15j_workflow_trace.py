"""Sprint 15J Tests — Workflow Step Trace + Lifecycle + Cancellation + Runtime Audit.

Verifies:
- [STEP TRACE] logging for each workflow step
- [WORKFLOW LIFECYCLE] logging with START/STEP_OK/STEP_FAILED/END
- [WORKFLOW CANCELLED] logging for all cancel paths
- WORKFLOW RUNTIME AUDIT report
- Workflow execution actually reaches runner.run()
"""

import time
import unittest
from unittest.mock import MagicMock, patch, call


class TestStepTraceInRunner(unittest.TestCase):
    """Test [STEP TRACE] logging in WorkflowRunner.run()."""

    def test_step_trace_logged_for_each_step(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill1 = MagicMock()
        skill1.execute.return_value = MagicMock(success=True, data={}, error="")
        skill2 = MagicMock()
        skill2.execute.return_value = MagicMock(success=True, data={}, error="")

        runner = WorkflowRunner(skill_map={"skill_a": skill1, "skill_b": skill2}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="test_wf", steps=["skill_a", "skill_b"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            result = runner.run(workflow, "COM1", trigger_id=42)

        step_logs = [l for l in cm.output if "[STEP TRACE]" in l]
        self.assertEqual(len(step_logs), 4)  # 2 start + 2 success
        self.assertTrue(all("trigger_id=42" in l for l in step_logs))
        self.assertTrue(all("WORKFLOW=test_wf" in l for l in step_logs))

    def test_step_trace_on_failure(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill1 = MagicMock()
        skill1.execute.return_value = MagicMock(success=True, data={}, error="")
        skill2 = MagicMock()
        skill2.execute.return_value = MagicMock(success=False, data={}, error="timeout")

        runner = WorkflowRunner(skill_map={"ok": skill1, "fail": skill2}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="fail_wf", steps=["ok", "fail"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            result = runner.run(workflow, "COM1", trigger_id=7)

        step_logs = [l for l in cm.output if "[STEP TRACE]" in l]
        # start_ok, success_ok, start_fail, failed_fail = 4
        self.assertEqual(len(step_logs), 4)
        failed_logs = [l for l in step_logs if "RESULT=failed" in l]
        self.assertEqual(len(failed_logs), 1)
        self.assertIn("ERROR=timeout", failed_logs[0])

    def test_step_trace_numbered_correctly(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = MagicMock()
        skill.execute.return_value = MagicMock(success=True, data={}, error="")

        runner = WorkflowRunner(skill_map={"s": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="num_wf", steps=["s", "s", "s"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=1)

        step_logs = [l for l in cm.output if "[STEP TRACE]" in l]
        self.assertIn("STEP=1/3", step_logs[0])
        self.assertIn("STEP=2/3", step_logs[2])
        self.assertIn("STEP=3/3", step_logs[4])


class TestWorkflowLifecycleLogging(unittest.TestCase):
    """Test [WORKFLOW LIFECYCLE] logging."""

    def test_lifecycle_start_and_end_success(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = MagicMock()
        skill.execute.return_value = MagicMock(success=True, data={}, error="")

        runner = WorkflowRunner(skill_map={"s": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="ok_wf", steps=["s"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=5)

        lc_logs = [l for l in cm.output if "[WORKFLOW LIFECYCLE]" in l]
        self.assertEqual(len(lc_logs), 2)  # START + END=SUCCESS
        self.assertIn("START", lc_logs[0])
        self.assertIn("END=SUCCESS", lc_logs[1])
        self.assertIn("STEP_1_OK", lc_logs[1])

    def test_lifecycle_end_failed(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = MagicMock()
        skill.execute.return_value = MagicMock(success=False, data={}, error="bad")

        runner = WorkflowRunner(skill_map={"s": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="fail_wf", steps=["s"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=6)

        lc_logs = [l for l in cm.output if "[WORKFLOW LIFECYCLE]" in l]
        self.assertEqual(len(lc_logs), 2)  # START + END=FAILED
        self.assertIn("END=FAILED", lc_logs[1])
        self.assertIn("STEP_1_FAILED", lc_logs[1])

    def test_lifecycle_multi_step(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill = MagicMock()
        skill.execute.return_value = MagicMock(success=True, data={}, error="")

        runner = WorkflowRunner(skill_map={"s": skill}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="multi_wf", steps=["s", "s", "s"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=8)

        lc_logs = [l for l in cm.output if "[WORKFLOW LIFECYCLE]" in l]
        self.assertEqual(len(lc_logs), 2)  # START + END=SUCCESS
        self.assertIn("STEP_1_OK", lc_logs[1])
        self.assertIn("STEP_2_OK", lc_logs[1])
        self.assertIn("STEP_3_OK", lc_logs[1])
        self.assertIn("END=SUCCESS", lc_logs[1])

    def test_lifecycle_stops_on_first_failure(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition

        skill1 = MagicMock()
        skill1.execute.return_value = MagicMock(success=False, data={}, error="err")
        skill2 = MagicMock()
        skill2.execute.return_value = MagicMock(success=True, data={}, error="")

        runner = WorkflowRunner(skill_map={"f": skill1, "ok": skill2}, cooldown_seconds=0.01)
        workflow = WorkflowDefinition(name="stop_wf", steps=["f", "ok"])

        with self.assertLogs("saiki.workflow", level="INFO") as cm:
            runner.run(workflow, "COM1", trigger_id=9)

        lc_logs = [l for l in cm.output if "[WORKFLOW LIFECYCLE]" in l]
        # skill2 should NOT have been called
        skill2.execute.assert_not_called()
        self.assertIn("STEP_1_FAILED", lc_logs[1])
        self.assertNotIn("STEP_2", lc_logs[1])


class TestWorkflowCancelledLogging(unittest.TestCase):
    """Test [WORKFLOW CANCELLED] logging in engine."""

    def test_cancel_on_modem_offline(self):
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from automation.queue import QueueItem
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        config = AutoRunConfig()
        config.set_enabled(True)
        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=config,
            event_bus=MagicMock(),
        )

        # Manually enqueue an item
        item = QueueItem(priority=10, port="COM1", workflow_name="test", trigger_id=1)
        engine._queue.enqueue(item)
        self.assertEqual(engine._queue.size, 1)

        # MODEM_OFFLINE triggers cancel
        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.MODEM_OFFLINE, "COM1", trigger_id=2, source="TEST")

        cancel_logs = [l for l in cm.output if "[WORKFLOW CANCELLED]" in l]
        self.assertEqual(len(cancel_logs), 1)
        self.assertIn("PORT=COM1", cancel_logs[0])
        self.assertIn("REASON=MODEM_OFFLINE", cancel_logs[0])
        self.assertEqual(engine._queue.size, 0)

    def test_cancel_on_port_excluded(self):
        from automation.engine import AutomationEngine
        from automation.queue import QueueItem
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )
        engine.start()

        item = QueueItem(priority=10, port="COM2", workflow_name="test", trigger_id=3)
        engine._queue.enqueue(item)

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine._on_port_excluded({"port": "COM2"})

        cancel_logs = [l for l in cm.output if "[WORKFLOW CANCELLED]" in l]
        self.assertEqual(len(cancel_logs), 1)
        self.assertIn("REASON=port_excluded", cancel_logs[0])

        engine.stop()

    def test_cancel_on_engine_stop(self):
        from automation.engine import AutomationEngine
        from automation.queue import QueueItem
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )

        item = QueueItem(priority=10, port="COM3", workflow_name="test", trigger_id=4)
        engine._queue.enqueue(item)

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.stop()

        cancel_logs = [l for l in cm.output if "[WORKFLOW CANCELLED]" in l]
        self.assertEqual(len(cancel_logs), 1)
        self.assertIn("REASON=engine_stop", cancel_logs[0])

    def test_cancel_on_sim_removed(self):
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from automation.queue import QueueItem
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        config = AutoRunConfig()
        config.set_enabled(True)
        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=config,
            event_bus=MagicMock(),
        )

        item = QueueItem(priority=10, port="COM4", workflow_name="test", trigger_id=5)
        engine._queue.enqueue(item)

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.SIM_REMOVED, "COM4", trigger_id=6, source="TEST")

        cancel_logs = [l for l in cm.output if "[WORKFLOW CANCELLED]" in l]
        self.assertEqual(len(cancel_logs), 1)
        self.assertIn("REASON=SIM_REMOVED", cancel_logs[0])

    def test_no_cancel_log_when_nothing_queued(self):
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.MODEM_OFFLINE, "COM5", trigger_id=7, source="TEST")

        cancel_logs = [l for l in cm.output if "[WORKFLOW CANCELLED]" in l]
        self.assertEqual(len(cancel_logs), 0)


class TestWorkflowRuntimeAuditReport(unittest.TestCase):
    """Test WORKFLOW RUNTIME AUDIT report."""

    def test_report_method_exists(self):
        from worker.system_bootstrap import SystemBootstrap
        self.assertTrue(hasattr(SystemBootstrap, '_print_workflow_runtime_audit'))

    def test_report_reads_from_engine(self):
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._print_workflow_runtime_audit)
        self.assertIn("get_runtime_stats", source)
        self.assertIn("get_top_failure_reason", source)

    def test_report_shows_expected_fields(self):
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._print_workflow_runtime_audit)
        self.assertIn("STARTED", source)
        self.assertIn("COMPLETED", source)
        self.assertIn("FAILED", source)
        self.assertIn("CANCELLED", source)
        self.assertIn("TOP FAILURE REASON", source)

    def test_report_called_from_lifecycle(self):
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._print_trigger_ownership_audit)
        self.assertIn("_print_workflow_runtime_audit", source)


class TestRuntimeStatsTracking(unittest.TestCase):
    """Test runtime stats counters in engine."""

    def test_initial_stats_zero(self):
        from automation.engine import AutomationEngine
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )
        stats = engine.get_runtime_stats()
        self.assertEqual(stats["started"], 0)
        self.assertEqual(stats["completed"], 0)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["cancelled"], 0)

    def test_top_failure_reason_empty(self):
        from automation.engine import AutomationEngine
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )
        self.assertEqual(engine.get_top_failure_reason(), "none")

    def test_top_failure_reason_tracking(self):
        from automation.engine import AutomationEngine
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )
        engine._failure_reasons = {"timeout": 5, "connection_error": 3, "unknown": 1}
        self.assertEqual(engine.get_top_failure_reason(), "timeout")


class TestTriggerIdPropagatedToRunner(unittest.TestCase):
    """Test that trigger_id reaches the runner."""

    def test_runner_receives_trigger_id(self):
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition
        import inspect

        source = inspect.getsource(WorkflowRunner.run)
        self.assertIn("trigger_id", source)

    def test_run_by_name_passes_trigger_id(self):
        from workflow.runner import WorkflowRunner
        import inspect

        source = inspect.getsource(WorkflowRunner.run_by_name)
        self.assertIn("trigger_id=trigger_id", source)


class TestEngineLogFormats(unittest.TestCase):
    """Test engine log format includes new tags."""

    def test_engine_step_trace_in_runner_source(self):
        from workflow.runner import WorkflowRunner
        import inspect
        source = inspect.getsource(WorkflowRunner.run)
        self.assertIn("[STEP TRACE]", source)
        self.assertIn("[WORKFLOW LIFECYCLE]", source)

    def test_engine_workflow_cancelled_in_engine_source(self):
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("[WORKFLOW CANCELLED]", source)

    def test_engine_cancelled_in_stop(self):
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.stop)
        self.assertIn("[WORKFLOW CANCELLED]", source)

    def test_engine_cancelled_in_port_excluded(self):
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine._on_port_excluded)
        self.assertIn("[WORKFLOW CANCELLED]", source)

    def test_controller_cancelled_in_disappeared(self):
        from worker.ui.controller import UIController
        import inspect
        source = inspect.getsource(UIController._handle_modem_disappeared)
        self.assertIn("[WORKFLOW CANCELLED]", source)


if __name__ == "__main__":
    unittest.main()
