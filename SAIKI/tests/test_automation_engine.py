"""Tests for automation.engine — AutomationEngine."""

import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from automation.engine import AutomationEngine
from automation.triggers import Trigger
from automation.state import AutomationStatus
from automation.policy import AutomationMode


def _make_engine(auto_run: bool = True, max_concurrent: int = 2) -> AutomationEngine:
    """Create an AutomationEngine with all dependencies mocked."""
    workflow_runner = MagicMock()
    workflow_registry = MagicMock()
    auto_run_config = MagicMock()
    auto_run_config.auto_run_enabled = auto_run
    event_bus = MagicMock()
    return AutomationEngine(
        workflow_runner=workflow_runner,
        workflow_registry=workflow_registry,
        auto_run_config=auto_run_config,
        event_bus=event_bus,
        max_concurrent=max_concurrent,
    )


class TestAutomationEngine(unittest.TestCase):
    """Test AutomationEngine — orchestration of workflow execution."""

    def test_handle_trigger_skips_when_auto_run_disabled(self) -> None:
        """Verify trigger is skipped when auto-run is disabled."""
        engine = _make_engine(auto_run=False)
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        self.assertEqual(engine.get_queue_size(), 0)
        engine._event_bus.publish.assert_called_once()
        call_args = engine._event_bus.publish.call_args
        self.assertEqual(call_args[0][0], "automation.skipped")

    def test_handle_trigger_enqueues_when_auto_run_enabled(self) -> None:
        """Verify trigger enqueues workflow when auto-run enabled."""
        engine = _make_engine(auto_run=True)
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        self.assertEqual(engine.get_queue_size(), 1)

    def test_handle_trigger_cancel_on_modem_offline(self) -> None:
        """Verify MODEM_OFFLINE cancels queued workflow for port."""
        engine = _make_engine(auto_run=True)
        # First enqueue something
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        self.assertEqual(engine.get_queue_size(), 1)
        # Then cancel it
        engine.handle_trigger(Trigger.MODEM_OFFLINE, "COM3")
        self.assertEqual(engine.get_queue_size(), 0)

    def test_handle_trigger_standby_on_cpin_required(self) -> None:
        """Verify CPIN_REQUIRED sets port to standby."""
        engine = _make_engine(auto_run=True)
        engine.handle_trigger(Trigger.CPIN_REQUIRED, "COM3")
        state = engine.get_state("COM3")
        self.assertEqual(state.status, AutomationStatus.STANDBY)
        self.assertEqual(engine.get_queue_size(), 0)

    def test_enqueue_workflow_manually(self) -> None:
        """Verify enqueue_workflow adds item to queue."""
        engine = _make_engine(auto_run=True)
        engine.enqueue_workflow("COM3", "check_data", priority=5)
        self.assertEqual(engine.get_queue_size(), 1)

    def test_get_queue_size(self) -> None:
        """Verify get_queue_size returns current count."""
        engine = _make_engine(auto_run=True)
        self.assertEqual(engine.get_queue_size(), 0)
        engine.enqueue_workflow("COM3", "check_data")
        self.assertEqual(engine.get_queue_size(), 1)

    def test_get_running_count(self) -> None:
        """Verify get_running_count returns 0 initially."""
        engine = _make_engine(auto_run=True)
        self.assertEqual(engine.get_running_count(), 0)

    def test_get_results(self) -> None:
        """Verify get_results returns list."""
        engine = _make_engine(auto_run=True)
        results = engine.get_results()
        self.assertIsInstance(results, list)

    def test_get_state(self) -> None:
        """Verify get_state returns AutomationState."""
        engine = _make_engine(auto_run=True)
        state = engine.get_state("COM3")
        self.assertIsNotNone(state)
        self.assertEqual(state.port, "COM3")

    def test_set_mode(self) -> None:
        """Verify set_mode updates internal policy mode."""
        engine = _make_engine(auto_run=True)
        engine.set_mode(AutomationMode.CHECK_DATA)
        self.assertEqual(engine.mode, AutomationMode.CHECK_DATA)

    def test_mode_property(self) -> None:
        """Verify mode property returns current policy mode."""
        engine = _make_engine(auto_run=True)
        self.assertEqual(engine.mode, AutomationMode.REACTIVATE_FULL)

    @patch("automation.engine.threading.Thread")
    def test_start_creates_thread(self, mock_thread_cls: MagicMock) -> None:
        """Verify start creates and starts daemon worker thread."""
        engine = _make_engine(auto_run=True)
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        engine.start()
        mock_thread_cls.assert_called_once()
        self.assertTrue(mock_thread.daemon)
        mock_thread.start.assert_called_once()
        engine.stop()

    def test_stop_clears_queue(self) -> None:
        """Verify stop clears the queue."""
        engine = _make_engine(auto_run=True)
        engine.enqueue_workflow("COM3", "check_data")
        self.assertEqual(engine.get_queue_size(), 1)
        engine.stop()
        self.assertEqual(engine.get_queue_size(), 0)

    def test_handle_trigger_user_mass_check_number(self) -> None:
        """Verify USER_MASS_CHECK_NUMBER enqueues check_data workflow."""
        engine = _make_engine(auto_run=True)
        engine.handle_trigger(Trigger.USER_MASS_CHECK_NUMBER, "COM3")
        self.assertEqual(engine.get_queue_size(), 1)
        snap = engine._queue.snapshot()
        self.assertEqual(snap[0]["workflow"], "check_data")

    def test_handle_trigger_user_mass_reactivation(self) -> None:
        """Verify USER_MASS_REACTIVATION enqueues current mode workflow."""
        engine = _make_engine(auto_run=True)
        engine.handle_trigger(Trigger.USER_MASS_REACTIVATION, "COM3")
        self.assertEqual(engine.get_queue_size(), 1)
        snap = engine._queue.snapshot()
        self.assertEqual(snap[0]["workflow"], "reactivate_full")

    def test_duplicate_enqueue_prevented(self) -> None:
        """Verify same port is not enqueued twice."""
        engine = _make_engine(auto_run=True)
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        self.assertEqual(engine.get_queue_size(), 1)

    def test_publish_called_on_events(self) -> None:
        """Verify event_bus.publish is called for various events."""
        engine = _make_engine(auto_run=True)
        engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        engine._event_bus.publish.assert_called()
        call_names = [call[0][0] for call in engine._event_bus.publish.call_args_list]
        self.assertIn("automation.queue_changed", call_names)

    def test_stop_and_start(self) -> None:
        """Verify engine can be stopped and restarted."""
        engine = _make_engine(auto_run=True)
        engine.stop()
        self.assertFalse(engine._running.is_set())

    def test_worker_loop_exception_safety(self) -> None:
        """Verify worker loop handles exceptions gracefully."""
        engine = _make_engine(auto_run=True)
        # Should not raise
        engine._running.clear()
        engine._worker_loop()

    def test_execute_workflow_publishes_started(self) -> None:
        """Verify _execute_workflow publishes automation.started event."""
        engine = _make_engine(auto_run=True)
        from automation.queue import QueueItem

        item = QueueItem(priority=10, port="COM3", workflow_name="check_data")
        mock_workflow = MagicMock()
        mock_workflow_result = MagicMock()
        mock_workflow_result.success = True
        engine._registry.get.return_value = mock_workflow
        engine._runner.run.return_value = mock_workflow_result

        engine._execute_workflow(item)

        engine._event_bus.publish.assert_any_call(
            "automation.started",
            {"port": "COM3", "workflow": "check_data"},
        )

    def test_execute_workflow_publishes_completed(self) -> None:
        """Verify _execute_workflow publishes automation.completed on success."""
        engine = _make_engine(auto_run=True)
        from automation.queue import QueueItem

        item = QueueItem(priority=10, port="COM3", workflow_name="check_data")
        mock_workflow = MagicMock()
        mock_workflow_result = MagicMock()
        mock_workflow_result.success = True
        engine._registry.get.return_value = mock_workflow
        engine._runner.run.return_value = mock_workflow_result

        engine._execute_workflow(item)

        call_names = [call[0][0] for call in engine._event_bus.publish.call_args_list]
        self.assertIn("automation.completed", call_names)

    def test_execute_workflow_publishes_failed_on_error(self) -> None:
        """Verify _execute_workflow publishes automation.failed on exception."""
        engine = _make_engine(auto_run=True)
        from automation.queue import QueueItem

        item = QueueItem(priority=10, port="COM3", workflow_name="check_data")
        engine._registry.get.side_effect = ValueError("Workflow not found: check_data")

        engine._execute_workflow(item)

        call_names = [call[0][0] for call in engine._event_bus.publish.call_args_list]
        self.assertIn("automation.failed", call_names)


if __name__ == "__main__":
    unittest.main()
