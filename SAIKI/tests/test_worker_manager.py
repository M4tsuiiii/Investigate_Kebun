"""Tests for WorkerManager — port lifecycle management."""

import unittest
import threading
from unittest.mock import MagicMock, patch

from worker.worker_manager import WorkerManager
from worker.port_worker import PortWorker
from worker.rules import AutoRunConfig


def _make_manager():
    event_bus = MagicMock()
    auto_run_config = AutoRunConfig()
    manager = WorkerManager(event_bus=event_bus, auto_run_config=auto_run_config)
    return manager, event_bus, auto_run_config


class TestWorkerManagerRegistry(unittest.TestCase):
    """Test WorkerManager worker registry operations."""

    def setUp(self):
        """Create fresh WorkerManager before each test."""
        self.manager, self.event_bus, _ = _make_manager()

    def tearDown(self):
        """Stop all workers after each test."""
        self.manager.stop_all()

    def test_create_worker_adds_to_registry(self):
        """Verify create_worker adds worker to registry."""
        worker = self.manager.create_worker("COM3")
        self.assertIsInstance(worker, PortWorker)
        self.assertIn("COM3", self.manager.workers)

    def test_create_worker_returns_existing(self):
        """Verify create_worker returns existing worker if already registered."""
        worker1 = self.manager.create_worker("COM3")
        worker2 = self.manager.create_worker("COM3")
        self.assertEqual(worker1, worker2)

    def test_destroy_worker_removes_from_registry(self):
        """Verify destroy_worker removes worker from registry."""
        self.manager.create_worker("COM3")
        self.manager.destroy_worker("COM3")
        self.assertNotIn("COM3", self.manager.workers)

    def test_destroy_nonexistent_worker(self):
        """Verify destroy_worker does not crash for unknown port."""
        self.manager.destroy_worker("COM99")

    def test_get_worker_returns_correct_worker(self):
        """Verify get_worker returns the correct worker."""
        worker = self.manager.create_worker("COM3")
        result = self.manager.get_worker("COM3")
        self.assertEqual(worker, result)

    def test_get_worker_returns_none_for_unknown(self):
        """Verify get_worker returns None for unknown port."""
        result = self.manager.get_worker("COM99")
        self.assertIsNone(result)

    def test_workers_property_returns_snapshot(self):
        """Verify workers property returns a copy, not internal dict."""
        self.manager.create_worker("COM3")
        workers_snapshot = self.manager.workers
        self.assertIn("COM3", workers_snapshot)
        # Modifying snapshot should not affect internal state
        workers_snapshot["COM99"] = MagicMock()
        self.assertNotIn("COM99", self.manager.workers)


class TestWorkerManagerLifecycle(unittest.TestCase):
    """Test WorkerManager global commands."""

    def setUp(self):
        """Create fresh WorkerManager before each test."""
        self.manager, self.event_bus, _ = _make_manager()

    def tearDown(self):
        """Stop all workers after each test."""
        self.manager.stop_all()

    def test_stop_all_stops_workers(self):
        """Verify stop_all stops all workers and clears registry."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        self.manager.stop_all()
        self.assertEqual(len(self.manager.workers), 0)

    def test_stop_all_stops_scanning(self):
        """Verify stop_all stops scanning thread."""
        self.manager.start_scanning()
        self.manager.stop_all()
        self.assertFalse(self.manager._scanning.is_set())

    def test_restart_all_sets_force_retry(self):
        """Verify restart_all sets force_retry on all workers."""
        w1 = self.manager.create_worker("COM3")
        w2 = self.manager.create_worker("COM5")
        self.manager.restart_all()
        self.assertTrue(w1.state.consume_force_retry())
        self.assertTrue(w2.state.consume_force_retry())

    def test_queue_auto_run_all(self):
        """Verify queue_auto_run_all sets pending_auto_run on all workers."""
        w1 = self.manager.create_worker("COM3")
        w2 = self.manager.create_worker("COM5")
        self.manager.queue_auto_run_all()
        self.assertTrue(w1.state.consume_auto_run())
        self.assertTrue(w2.state.consume_auto_run())

    def test_create_worker_publishes_event(self):
        """Verify create_worker publishes port.discovered event."""
        self.manager.create_worker("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("port.discovered" in c for c in calls))

    def test_destroy_worker_publishes_event(self):
        """Verify destroy_worker publishes port.removed event."""
        self.manager.create_worker("COM3")
        self.manager.destroy_worker("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("port.removed" in c for c in calls))


class TestWorkerManagerThreadSafety(unittest.TestCase):
    """Test WorkerManager thread-safe registry access."""

    def setUp(self):
        """Create fresh WorkerManager before each test."""
        self.manager, self.event_bus, _ = _make_manager()

    def tearDown(self):
        """Stop all workers after each test."""
        self.manager.stop_all()

    def test_concurrent_create_destroy(self):
        """Verify concurrent create/destroy does not crash."""
        errors = []

        def creator(port_id):
            try:
                for _ in range(10):
                    self.manager.create_worker(port_id)
                    self.manager.destroy_worker(port_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=creator, args=(f"COM{i}",))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_concurrent_read_write(self):
        """Verify concurrent reads and writes do not crash."""
        errors = []

        def writer():
            try:
                for i in range(20):
                    self.manager.create_worker(f"COM{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    _ = self.manager.workers
                    _ = self.manager.get_worker("COM3")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_concurrent_restart_all(self):
        """Verify concurrent restart_all does not crash."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        errors = []

        def restarter():
            try:
                for _ in range(20):
                    self.manager.restart_all()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=restarter) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
