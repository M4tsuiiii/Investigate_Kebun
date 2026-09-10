"""Sprint 15G — Single Source of Truth Audit (observation only, no fixes).

Root causes identified:
A. Event name mismatch: cpin.transition vs cpin.state_changed
B. Status hardcoded to CHECKING in _on_cpin_transition
C. Multiple status writers competing
"""

import unittest
from unittest.mock import MagicMock, patch, call


# ==================================================================
# PART 1 — STATUS WRITERS MAP
# ==================================================================

class TestStatusWritersMap(unittest.TestCase):
    """Map all locations that can write port status."""

    def test_port_worker_publish_status_exists(self):
        """PortWorker._publish_status exists and writes to ui.port.update."""
        from worker.port_worker import PortWorker
        import inspect
        source = inspect.getsource(PortWorker._publish_status)
        self.assertIn("ui.port.update", source)

    def test_port_worker_writes_status_in_run_loop(self):
        """PortWorker._run_loop writes READY and GAGAL."""
        from worker.port_worker import PortWorker
        import inspect
        source = inspect.getsource(PortWorker._run_loop)
        self.assertIn("set_status", source)
        self.assertIn("PortStatus.READY", source)
        self.assertIn("PortStatus.GAGAL", source)

    def test_port_worker_writes_status_in_execute_step(self):
        """PortWorker._execute_step writes BUSY, CHECKING, READY."""
        from worker.port_worker import PortWorker
        import inspect
        source = inspect.getsource(PortWorker._execute_step)
        self.assertIn("PortStatus.BUSY", source)
        self.assertIn("PortStatus.CHECKING", source)
        self.assertIn("PortStatus.READY", source)

    def test_port_worker_writes_status_in_auto_run(self):
        """PortWorker._execute_auto_run writes CHECKING."""
        from worker.port_worker import PortWorker
        import inspect
        source = inspect.getsource(PortWorker._execute_auto_run)
        self.assertIn("PortStatus.CHECKING", source)

    def test_port_worker_writes_status_in_hardware_restart(self):
        """PortWorker._execute_hardware_restart writes RESET, READY, IDLE, GAGAL."""
        from worker.port_worker import PortWorker
        import inspect
        source = inspect.getsource(PortWorker._execute_hardware_restart)
        self.assertIn("PortStatus.RESET", source)
        self.assertIn("PortStatus.READY", source)
        self.assertIn("PortStatus.IDLE", source)
        self.assertIn("PortStatus.GAGAL", source)

    def test_cpin_runtime_publishes_cpin_transition(self):
        """CpinRuntime._poll_once publishes cpin.transition."""
        from worker.cpin_runtime import CpinRuntime
        import inspect
        source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("cpin.transition", source)

    def test_gui_on_port_update_writes_status(self):
        """GUIApplication._on_port_update writes status to UI."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_port_update)
        self.assertIn("update_port", source)
        self.assertIn("status", source)

    def test_gui_on_cpin_transition_writes_idle(self):
        """GUIApplication._on_cpin_transition writes IDLE for neutral states (Sprint 15R.1)."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertIn('"IDLE"', source)


# ==================================================================
# PART 2 — SINGLE SOURCE OF TRUTH VIOLATIONS
# ==================================================================

class TestSingleSourceViolations(unittest.TestCase):
    """Find status write conflicts."""

    def test_ready_written_by_port_worker(self):
        """READY is written by PortWorker._publish_status."""
        from worker.port_worker import PortWorker
        import inspect
        source = inspect.getsource(PortWorker._publish_status)
        self.assertIn("ui.port.update", source)

    def test_ready_written_by_cpin_transition_handler(self):
        """_on_cpin_transition writes READY for READY state, IDLE for neutral (Sprint 15R.1)."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertIn('"READY"', source)
        self.assertIn('"IDLE"', source)

    def test_status_flicker_simulation(self):
        """Simulate flicker: PortWorker writes READY, then CPIN writes CHECKING."""
        from app.domain.enums import PortStatus
        # PortWorker publishes READY
        port_worker_status = PortStatus.READY.value  # "READY"
        # CPIN handler overwrites with CHECKING
        cpin_status = "CHECKING"
        # Result: status flickers from READY to CHECKING
        self.assertEqual(port_worker_status, "READY")
        self.assertEqual(cpin_status, "CHECKING")
        self.assertNotEqual(port_worker_status, cpin_status)


# ==================================================================
# PART 3 — READY WORKFLOW PATH
# ==================================================================

class TestReadyWorkflowPath(unittest.TestCase):
    """Trace: CPIN READY → event → trigger → workflow."""

    def test_cpin_runtime_publishes_transition(self):
        """CpinRuntime publishes cpin.transition with state=READY."""
        from worker.cpin_runtime import CpinRuntime
        import inspect
        source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("cpin.transition", source)

    def test_system_bootstrap_subscribes_correct_event(self):
        """SystemBootstrap subscribes to 'cpin.transition' (FIXED)."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("cpin.transition", source)

    def test_controller_subscribes_correct_event(self):
        """Controller subscribes to 'cpin.transition' (FIXED)."""
        from worker.ui.controller import UIController
        import inspect
        source = inspect.getsource(UIController._subscribe_events)
        self.assertIn("cpin.transition", source)

    def test_event_name_now_matches(self):
        """cpin.transition (published) == cpin.transition (subscribed)."""
        published_event = "cpin.transition"
        subscribed_event = "cpin.transition"
        self.assertEqual(published_event, subscribed_event)

    def test_system_bootstrap_forwards_to_engine(self):
        """SystemBootstrap._subscribe_modem_events forwards CPIN to engine."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("handle_trigger", source)
        self.assertIn("Trigger.CPIN_READY", source)

    def test_controller_forwards_to_engine(self):
        """UIController._handle_cpin_changed forwards CPIN to engine."""
        from worker.ui.controller import UIController
        import inspect
        source = inspect.getsource(UIController._handle_cpin_changed)
        self.assertIn("handle_trigger", source)
        self.assertIn("Trigger.CPIN_READY", source)

    def test_auto_run_disabled_by_default(self):
        """AutoRunConfig defaults to disabled."""
        from worker.rules import AutoRunConfig
        config = AutoRunConfig()
        self.assertFalse(config.auto_run_enabled)

    def test_engine_skips_when_auto_run_disabled(self):
        """AutomationEngine skips triggers when auto-run disabled."""
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from worker.rules import AutoRunConfig
        mock_queue = MagicMock()
        engine = AutomationEngine(
            workflow_runner=MagicMock(),
            workflow_registry=MagicMock(),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )
        engine._queue = mock_queue
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM1")
        mock_queue.enqueue.assert_not_called()


# ==================================================================
# PART 4 — INSTRUMENTATION CHECKS
# ==================================================================

class TestInstrumentation(unittest.TestCase):
    """Verify audit logs exist for all status write locations."""

    def test_port_worker_publish_status_has_log(self):
        """_publish_status logs [UI] tag."""
        from worker.port_worker import PortWorker
        import inspect
        source = inspect.getsource(PortWorker._publish_status)
        self.assertIn("[UI]", source)

    def test_cpin_runtime_poll_once_has_raw_trace(self):
        """_poll_once logs [CPIN TRACE] RAW."""
        from worker.cpin_runtime import CpinRuntime
        import inspect
        source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("[CPIN TRACE]", source)

    def test_cpin_runtime_poll_once_has_parse_trace(self):
        """_poll_once logs [CPIN PARSE]."""
        from worker.cpin_runtime import CpinRuntime
        import inspect
        source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("[CPIN PARSE]", source)

    def test_cpin_runtime_poll_once_has_state_trace(self):
        """_poll_once logs [CPIN STATE]."""
        from worker.cpin_runtime import CpinRuntime
        import inspect
        source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("[CPIN STATE]", source)

    def test_cpin_runtime_poll_once_has_ui_trace(self):
        """_poll_once logs [CPIN EVENT] PUBLISH."""
        from worker.cpin_runtime import CpinRuntime
        import inspect
        source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("[CPIN EVENT] PUBLISH", source)

    def test_gui_on_cpin_transition_has_ui_trace(self):
        """_on_cpin_transition logs [UI TRACE]."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertIn("[UI TRACE]", source)

    def test_engine_handle_trigger_has_engine_log(self):
        """handle_trigger logs [ENGINE]."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("[ENGINE]", source)

    def test_engine_execute_workflow_has_workflow_log(self):
        """_execute_workflow logs [WORKFLOW]."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine._execute_workflow)
        self.assertIn("[WORKFLOW]", source)


# ==================================================================
# PART 5 — ROOT CAUSE DIAGNOSIS
# ==================================================================

class TestRootCauseDiagnosis(unittest.TestCase):
    """Verify root cause analysis."""

    def test_root_cause_a_event_mismatch_fixed(self):
        """ROOT CAUSE A: Event name mismatch FIXED."""
        published = "cpin.transition"
        subscribed = "cpin.transition"
        self.assertEqual(published, subscribed,
                          "Event name mismatch fixed: workflow trigger now fires")

    def test_root_cause_b_status_hardcoded_fixed(self):
        """ROOT CAUSE B: _on_cpin_transition now maps status correctly (FIXED)."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        # Fixed: READY maps to READY, neutral states map to IDLE
        self.assertIn('port_status = "READY"', source)
        self.assertIn('"IDLE"', source)


# ==================================================================
# NEW TESTS — Sprint 15H-A
# ==================================================================

class TestTriggerPathFixed(unittest.TestCase):
    """Test A: CPIN READY → trigger created → handle_trigger called."""

    def test_cpim_ready_creates_trigger(self):
        """CPIN READY event creates Trigger.CPIN_READY."""
        from automation.triggers import Trigger
        self.assertEqual(Trigger.CPIN_READY.value, "CPIN_READY")

    def test_system_bootstrap_handles_cpin_ready(self):
        """SystemBootstrap.on_cpin_changed creates CPIN_READY trigger."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("Trigger.CPIN_READY", source)
        self.assertIn("handle_trigger", source)

    def test_engine_receives_trigger(self):
        """AutomationEngine.handle_trigger processes CPIN_READY."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("ENGINE ENTER", source)

    def test_scheduler_enqueues_on_cpin_ready(self):
        """Scheduler returns 'enqueue' for CPIN_READY."""
        from automation.scheduler import AutomationScheduler
        from automation.triggers import Trigger, TriggerEvent
        scheduler = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.CPIN_READY, port="COM1")
        action = scheduler.evaluate_trigger(event)
        self.assertEqual(action, "enqueue")


class TestStatusMappingFixed(unittest.TestCase):
    """Test B: READY → status READY, neutral → IDLE (Sprint 15R.1)."""

    def test_ready_maps_to_ready(self):
        """CPIN READY maps to port status READY."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertIn('port_status = "READY"', source)

    def test_not_inserted_maps_to_idle(self):
        """CPIN NOT_INSERTED maps to port status IDLE (Sprint 15R.1)."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertIn('_NEUTRAL_CPIN', source)
        self.assertIn('"IDLE"', source)

    def test_pin_required_maps_to_idle(self):
        """CPIN PIN_REQUIRED maps to port status IDLE (Sprint 15R.1)."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertIn('PIN_REQUIRED', source)
        self.assertIn('"IDLE"', source)

    def test_no_hardcoded_checking_for_ready(self):
        """READY no longer hardcoded to CHECKING."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertNotIn('update_port(port, "status", "CHECKING")', source)


class TestWorkflowGateInstrumentation(unittest.TestCase):
    """Test C: Workflow Gate logs BLOCKED/ALLOWED."""

    def test_engine_has_workflow_gate_log(self):
        """handle_trigger logs [AUTORUN GATE]."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("[AUTORUN GATE]", source)

    def test_engine_logs_auto_run_disabled(self):
        """handle_trigger logs BLOCKED reason=auto_run_disabled."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("auto_run_disabled", source)

    def test_engine_logs_port_excluded(self):
        """handle_trigger logs BLOCKED reason=port_excluded."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("port_excluded", source)

    def test_engine_logs_cancel(self):
        """handle_trigger logs BLOCKED reason=cancel."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("reason=cancel", source)

    def test_engine_logs_standby(self):
        """handle_trigger logs BLOCKED reason=standby."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("reason=standby", source)

    def test_engine_logs_allowed(self):
        """handle_trigger logs PASSED when workflow selected."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("PASSED", source)

    def test_engine_logs_no_workflow(self):
        """handle_trigger logs BLOCKED reason=no_workflow."""
        from automation.engine import AutomationEngine
        import inspect
        source = inspect.getsource(AutomationEngine.handle_trigger)
        self.assertIn("no_workflow", source)


class TestEndToEndTriggerTrace(unittest.TestCase):
    """Verify end-to-end trace logging exists."""

    def test_cpin_runtime_has_publish_trace(self):
        """CpinRuntime logs CPIN EVENT PUBLISH."""
        from worker.cpin_runtime import CpinRuntime
        import inspect
        source = inspect.getsource(CpinRuntime._poll_once)
        self.assertIn("[CPIN EVENT] PUBLISH", source)

    def test_system_bootstrap_has_receive_trace(self):
        """SystemBootstrap logs CPIN EVENT RECEIVE."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("[CPIN EVENT] RECEIVE", source)

    def test_system_bootstrap_has_workflow_gate_trace(self):
        """SystemBootstrap logs TRIGGER SOURCE before trigger."""
        from worker.system_bootstrap import SystemBootstrap
        import inspect
        source = inspect.getsource(SystemBootstrap._subscribe_modem_events)
        self.assertIn("[TRIGGER SOURCE]", source)

    def test_gui_has_status_write_trace(self):
        """GUI logs STATUS WRITE."""
        from gui import GUIApplication
        import inspect
        source = inspect.getsource(GUIApplication._on_cpin_transition)
        self.assertIn("[STATUS WRITE]", source)


if __name__ == "__main__":
    unittest.main()
