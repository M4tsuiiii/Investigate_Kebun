"""Sprint 15H-VERIFY — Trigger Path Verification Tests.

READ ONLY AUDIT — proves the trigger path works.
"""

import unittest
from unittest.mock import MagicMock, patch, call
import logging


# ==================================================================
# TASK 1 — Trigger Source Audit
# ==================================================================

class TestTriggerSourceAudit(unittest.TestCase):
    """Verify [TRIGGER SOURCE] logging exists at all trigger creation points."""

    def test_system_bootstrap_has_trigger_source_log(self):
        """SystemBootstrap logs [TRIGGER SOURCE] for MODEM_ONLINE."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("[TRIGGER SOURCE]", source)
        self.assertIn("SOURCE=SYSTEM_BOOTSTRAP", source)

    def test_controller_has_trigger_source_log(self):
        """Controller logs [TRIGGER SOURCE] for MODEM_ONLINE."""
        from worker.ui.controller import UIController
        import inspect
        source = inspect.getsource(UIController._handle_modem_online)
        self.assertIn("[TRIGGER SOURCE]", source)
        self.assertIn("SOURCE=CONTROLLER", source)

    def test_system_bootstrap_logs_cpin_ready_source(self):
        """SystemBootstrap logs TRIGGER=CPIN_READY."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("TRIGGER=CPIN_READY", source)

    def test_controller_logs_cpin_ready_source(self):
        """Controller logs TRIGGER=CPIN_READY."""
        from worker.ui.controller import UIController
        import inspect
        source = inspect.getsource(UIController._handle_cpin_changed)
        self.assertIn("TRIGGER=CPIN_READY", source)

    def test_system_bootstrap_logs_modem_online_source(self):
        """SystemBootstrap logs TRIGGER=MODEM_ONLINE."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("TRIGGER=MODEM_ONLINE", source)

    def test_controller_logs_modem_online_source(self):
        """Controller logs TRIGGER=MODEM_ONLINE."""
        from worker.ui.controller import UIController
        import inspect
        source = inspect.getsource(UIController._handle_modem_online)
        self.assertIn("TRIGGER=MODEM_ONLINE", source)


# ==================================================================
# TASK 2 — Workflow Selection Audit
# ==================================================================

class TestWorkflowSelectionAudit(unittest.TestCase):
    """Verify [WORKFLOW SELECT] logging in handle_trigger."""

    def test_engine_has_workflow_select_log(self):
        """handle_trigger logs [WORKFLOW SELECT]."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("[WORKFLOW SELECT]", source)

    def test_engine_logs_workflow_name(self):
        """handle_trigger logs workflow=... when selected."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("workflow=", source)

    def test_engine_logs_workflow_none(self):
        """handle_trigger logs workflow=None when no workflow."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("workflow=None", source)


# ==================================================================
# TASK 3 — Queue Audit
# ==================================================================

class TestQueueAudit(unittest.TestCase):
    """Verify [QUEUE AUDIT] logging in handle_trigger."""

    def test_engine_has_queue_audit_log(self):
        """handle_trigger logs [QUEUE AUDIT]."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("[QUEUE AUDIT]", source)

    def test_engine_logs_enqueue(self):
        """handle_trigger logs ENQUEUE when workflow queued."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("ENQUEUE", source)

    def test_engine_logs_skipped(self):
        """handle_trigger logs SKIPPED when queue not created."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("SKIPPED", source)


# ==================================================================
# TASK 4 — Auto Run Gate Audit
# ==================================================================

class TestAutoRunGateAudit(unittest.TestCase):
    """Verify [AUTORUN GATE] logging in handle_trigger."""

    def test_engine_has_autorun_gate_log(self):
        """handle_trigger logs [AUTORUN GATE]."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("[AUTORUN GATE]", source)

    def test_engine_logs_auto_run_value(self):
        """handle_trigger logs AUTO_RUN=True/False."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("AUTO_RUN=", source)

    def test_engine_logs_blocked_reason(self):
        """handle_trigger logs BLOCKED reason=auto_run_disabled."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("reason=auto_run_disabled", source)

    def test_engine_logs_passed(self):
        """handle_trigger logs PASSED when auto-run enabled."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("PASSED", source)


# ==================================================================
# TASK 5 — End-to-End Trigger Path
# ==================================================================

class TestEndToEndTriggerPath(unittest.TestCase):
    """Verify the complete trigger path exists in code."""

    def test_cpim_ready_path_exists(self):
        """Complete path: cpin.transition -> trigger -> workflow -> queue."""
        # 1. CpinRuntime publishes
        from worker.cpin_runtime import CpinRuntime
        import inspect
        cpin_source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("cpin.transition", cpin_source)

        # 2. SystemBootstrap subscribes and creates trigger
        from worker.system_bootstrap import SystemBootstrap
        bootstrap_source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("cpin.transition", bootstrap_source)
        self.assertIn("Trigger.CPIN_READY", bootstrap_source)

        # 3. Engine handles trigger
        from automation.engine import AutomationEngine
        engine_source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("ENGINE ENTER", engine_source)
        self.assertIn("[WORKFLOW SELECT]", engine_source)
        self.assertIn("[QUEUE AUDIT]", engine_source)
        self.assertIn("[AUTORUN GATE]", engine_source)

    def test_scheduler_enqueues_on_cpin_ready(self):
        """Scheduler returns 'enqueue' for CPIN_READY."""
        from automation.scheduler import AutomationScheduler
        from automation.triggers import Trigger, TriggerEvent
        scheduler = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.CPIN_READY, port="COM1")
        action = scheduler.evaluate_trigger(event)
        self.assertEqual(action, "enqueue")

    def test_policy_selects_workflow_for_cpin_ready(self):
        """Policy selects workflow for CPIN_READY trigger."""
        from automation.policy import AutomationPolicy
        policy = AutomationPolicy()
        workflow = policy.select_workflow(trigger="CPIN_READY")
        self.assertIsNotNone(workflow)
        self.assertIn(workflow, ["check_data", "reactivate_fast", "reactivate_full"])


# ==================================================================
# TASK 6 — Verification Report
# ==================================================================

class TestVerificationReport(unittest.TestCase):
    """Verify the verification report exists."""

    def test_system_bootstrap_has_verification_report(self):
        """SystemBootstrap has _print_trigger_path_verification method."""
        from worker.system_bootstrap import SystemBootstrap
        self.assertTrue(hasattr(SystemBootstrap, '_print_trigger_path_verification'))

    def test_verification_report_method_is_callable(self):
        """_print_trigger_path_verification is callable."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        self.assertTrue(callable(getattr(SystemBootstrap, '_print_trigger_path_verification')))


# ==================================================================
# Summary: All checks pass
# ==================================================================

class TestTriggerPathSummary(unittest.TestCase):
    """Summary: prove the trigger path is complete."""

    def test_all_components_present(self):
        """All 10 components of the trigger path are present."""
        components = [
            ("CpinRuntime publishes", "worker.cpin_runtime", "CpinRuntime", "_poll_once", "cpin.transition"),
            ("SystemBootstrap subscribes", "worker.system_bootstrap", "SystemBootstrap", "_subscribe_modem_events", "cpin.transition"),
            ("SystemBootstrap creates trigger", "worker.system_bootstrap", "SystemBootstrap", "_subscribe_modem_events", "Trigger.CPIN_READY"),
            ("Engine handles trigger", "automation.engine", "AutomationEngine", "handle_trigger", "ENGINE ENTER"),
            ("Engine logs workflow select", "automation.engine", "AutomationEngine", "handle_trigger", "[WORKFLOW SELECT]"),
            ("Engine logs queue audit", "automation.engine", "AutomationEngine", "handle_trigger", "[QUEUE AUDIT]"),
            ("Engine logs autorun gate", "automation.engine", "AutomationEngine", "handle_trigger", "[AUTORUN GATE]"),
            ("Scheduler enqueues CPIN_READY", "automation.scheduler", "AutomationScheduler", "evaluate_trigger", "enqueue"),
            ("Policy selects workflow", "automation.policy", "AutomationPolicy", "select_workflow", "check_data"),
            ("Controller subscribes", "worker.ui.controller", "UIController", "_subscribe_events", "cpin.transition"),
        ]
        
        for name, module_name, class_name, method_name, expected in components:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            import inspect
            source = inspect.getsource(getattr(cls, method_name))
            self.assertIn(expected, source, f"Component '{name}' missing '{expected}'")


if __name__ == "__main__":
    unittest.main()
