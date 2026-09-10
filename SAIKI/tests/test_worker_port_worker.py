"""Tests for PortWorker — per-port orchestration engine."""

import unittest
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

from worker.port_worker import PortWorker
from worker.state import PortWorkerState
from worker.rules import AutoRunConfig
from app.domain.enums import PortStatus


def _make_worker(port_id="COM3"):
    event_bus = MagicMock()
    auto_run_config = AutoRunConfig()
    worker = PortWorker(port_id, event_bus, auto_run_config)
    return worker, event_bus, auto_run_config


class TestPortWorkerCreation(unittest.TestCase):
    """Test PortWorker creation and initialization."""

    def setUp(self):
        """Create fresh PortWorker before each test."""
        self.worker, self.event_bus, _ = _make_worker()

    def test_creation(self):
        """Verify worker is created with correct port_id."""
        self.assertEqual(self.worker.port_id, "COM3")

    def test_initial_state(self):
        """Verify state is PortWorkerState instance."""
        self.assertIsInstance(self.worker.state, PortWorkerState)

    def test_not_alive_before_start(self):
        """Verify is_alive is False before start."""
        self.assertFalse(self.worker.is_alive)

    def test_connect_stores_references(self):
        """Verify connect stores serial and at_client references."""
        serial = MagicMock()
        at_client = MagicMock()
        self.worker.connect(serial, at_client)
        self.assertEqual(self.worker._serial, serial)
        self.assertEqual(self.worker._at_client, at_client)


class TestPortWorkerLifecycle(unittest.TestCase):
    """Test PortWorker start/stop/restart thread lifecycle."""

    def setUp(self):
        """Create fresh PortWorker before each test."""
        self.worker, self.event_bus, _ = _make_worker()

    def tearDown(self):
        """Ensure worker is stopped after each test."""
        if self.worker.is_alive:
            self.worker.stop(timeout=2.0)

    def test_start_creates_daemon_thread(self):
        """Verify start() creates a daemon thread."""
        self.worker.start()
        self.assertTrue(self.worker.is_alive)
        self.assertTrue(self.worker._thread.daemon)

    def test_start_idempotent(self):
        """Verify calling start() twice does not create second thread."""
        self.worker.start()
        thread1 = self.worker._thread
        self.worker.start()
        self.assertEqual(self.worker._thread, thread1)
        self.assertTrue(self.worker.is_alive)

    def test_stop_joins_thread(self):
        """Verify stop() joins thread and sets OFF status."""
        self.worker.start()
        self.assertTrue(self.worker.is_alive)
        self.worker.stop(timeout=2.0)
        self.assertFalse(self.worker.is_alive)
        self.assertEqual(self.worker.state.status, PortStatus.OFF)

    def test_stop_publishes_status(self):
        """Verify stop() publishes OFF status to EventBus."""
        self.worker.start()
        self.worker.stop(timeout=2.0)
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("OFF" in c for c in calls))

    def test_restart_clears_state_and_restarts(self):
        """Verify restart() clears transient state and restarts."""
        self.worker.state.queue_auto_run()
        self.worker.state.set_force_retry()
        with patch("worker.port_worker.time.sleep"):
            self.worker.restart()
        # After restart, pending auto_run/force_retry were cleared
        self.assertFalse(self.worker.state.consume_auto_run())
        self.assertFalse(self.worker.state.consume_force_retry())
        self.assertTrue(self.worker.is_alive)

    def test_force_retry_sets_flag(self):
        """Verify force_retry() sets force_retry flag on state."""
        self.worker.force_retry()
        self.assertTrue(self.worker.state.consume_force_retry())

    def test_queue_auto_run_sets_flag(self):
        """Verify queue_auto_run() sets pending_auto_run flag."""
        self.worker.queue_auto_run()
        self.assertTrue(self.worker.state.consume_auto_run())

    def test_publish_status_calls_event_bus(self):
        """Verify _publish_status() calls EventBus publish."""
        self.worker._publish_status(PortStatus.BUSY, "Testing")
        self.event_bus.publish.assert_called_with(
            "ui.port.update",
            {"port": "COM3", "status": "BUSY", "detail": "Testing"},
        )

    def test_publish_status_no_event_bus(self):
        """Verify _publish_status() does not crash with no event bus."""
        worker = PortWorker(port_id="COM3", event_bus=None, auto_run_config=AutoRunConfig())
        worker._publish_status(PortStatus.READY, "OK")

    def test_run_loop_handles_exception(self):
        """Verify run loop continues after exception in _tick."""
        self.worker._tick = MagicMock(side_effect=RuntimeError("boom"))
        self.worker.start()
        time.sleep(0.3)
        self.assertTrue(self.worker.is_alive)

    def test_thread_lifecycle_start_stop(self):
        """Verify full start/stop lifecycle."""
        self.worker.start()
        time.sleep(0.1)
        self.assertTrue(self.worker.is_alive)
        self.worker.stop(timeout=2.0)
        self.assertFalse(self.worker.is_alive)

    def test_stop_without_start(self):
        """Verify stop() does not crash when not started."""
        self.worker.stop(timeout=1.0)
        self.assertFalse(self.worker.is_alive)


class TestPortWorkerTickPriority(unittest.TestCase):
    """Test PortWorker _tick priority order (HR-002)."""

    def setUp(self):
        """Create fresh PortWorker before each test."""
        self.worker, self.event_bus, _ = _make_worker()

    def test_tick_priority_reset_first(self):
        """Verify reset is checked first in tick priority."""
        self.worker.set_modem_online(True)
        self.worker.state.request_reset()
        self.worker.state.queue_auto_run()
        self.worker.state.set_force_retry()
        with patch.object(self.worker, "_execute_hardware_restart") as mock_hr:
            self.worker._tick()
            mock_hr.assert_called_once()

    def test_tick_priority_single_action_second(self):
        """Verify single_action is checked second after reset."""
        self.worker.set_modem_online(True)
        self.worker.state.set_single_action("cek_nomor")
        self.worker.state.queue_auto_run()
        with patch.object(self.worker, "_execute_step") as mock_step:
            self.worker._tick()
            mock_step.assert_called_once_with("cek_nomor")

    def test_tick_priority_force_retry_third(self):
        """Verify force_retry is checked third."""
        self.worker.set_modem_online(True)
        self.worker.state.set_force_retry()
        self.worker.state.queue_auto_run()
        with patch.object(self.worker, "_execute_step") as mock_step:
            self.worker._tick()
            mock_step.assert_called_once_with("cek_nomor")

    def test_tick_priority_auto_run_fourth(self):
        """Verify auto_run is checked fourth."""
        self.worker.set_modem_online(True)
        self.worker._auto_run_config.set_enabled(True)
        self.worker.state.queue_auto_run()
        with patch.object(self.worker, "_execute_auto_run") as mock_ar:
            self.worker._tick()
            mock_ar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
