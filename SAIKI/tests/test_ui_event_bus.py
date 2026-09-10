"""Tests for EventBus — thread-safe pub/sub for worker-UI communication."""

import unittest
import threading
import queue
from unittest.mock import MagicMock

from worker.ui.event_bus import EventBus


class TestEventBusSubscribePublish(unittest.TestCase):
    """Test EventBus subscribe/publish pattern."""

    def setUp(self):
        """Create fresh EventBus before each test."""
        self.bus = EventBus()

    def test_subscribe_and_publish(self):
        """Verify subscribe receives published events."""
        callback = MagicMock()
        self.bus.subscribe("test.event", callback)
        self.bus.publish("test.event", {"data": "hello"})
        callback.assert_called_once_with({"data": "hello"})

    def test_multiple_subscribers(self):
        """Verify multiple subscribers all receive events."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        self.bus.subscribe("test.event", cb1)
        self.bus.subscribe("test.event", cb2)
        self.bus.publish("test.event", "payload")
        cb1.assert_called_once_with("payload")
        cb2.assert_called_once_with("payload")

    def test_publish_to_no_subscribers(self):
        """Verify publish to nonexistent event does not crash."""
        self.bus.publish("nonexistent.event", "data")

    def test_unsubscribe(self):
        """Verify unsubscribe stops event delivery."""
        callback = MagicMock()
        self.bus.subscribe("test.event", callback)
        self.bus.unsubscribe("test.event", callback)
        self.bus.publish("test.event", "data")
        callback.assert_not_called()

    def test_get_subscribers(self):
        """Verify get_subscribers returns correct list."""
        cb = MagicMock()
        self.bus.subscribe("test.event", cb)
        subs = self.bus.get_subscribers("test.event")
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0], cb)

    def test_get_subscribers_nonexistent(self):
        """Verify get_subscribers returns empty list for unknown event."""
        subs = self.bus.get_subscribers("nonexistent")
        self.assertEqual(subs, [])


class TestEventBusUIUpdates(unittest.TestCase):
    """Test EventBus UI update queue and drain_ui_updates."""

    def setUp(self):
        """Create fresh EventBus before each test."""
        self.bus = EventBus()

    def test_publish_ui_update_queues(self):
        """Verify publish_ui_update adds to queue."""
        self.bus.publish_ui_update("COM3", "status", "BUSY")
        updates = self.bus.drain_ui_updates()
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0], ("COM3", "status", "BUSY"))

    def test_drain_ui_updates_deduplicates(self):
        """Verify drain_ui_updates deduplicates by (port, column)."""
        self.bus.publish_ui_update("COM3", "status", "BUSY")
        self.bus.publish_ui_update("COM3", "status", "READY")
        self.bus.publish_ui_update("COM3", "nomor", "08123")
        updates = self.bus.drain_ui_updates()
        self.assertEqual(len(updates), 2)
        status_updates = [u for u in updates if u[1] == "status"]
        self.assertEqual(len(status_updates), 1)
        self.assertEqual(status_updates[0][2], "READY")

    def test_drain_ui_updates_empty_queue(self):
        """Verify drain_ui_updates returns empty list when queue empty."""
        updates = self.bus.drain_ui_updates()
        self.assertEqual(updates, [])

    def test_drain_ui_updates_max_limit(self):
        """Verify drain_ui_updates respects max 1500 limit."""
        for i in range(1600):
            self.bus.publish_ui_update(f"COM{i % 10}", f"col{i}", f"val{i}")
        updates = self.bus.drain_ui_updates()
        self.assertLessEqual(len(updates), 1500)


class TestEventBusTasks(unittest.TestCase):
    """Test EventBus task queue and drain_tasks."""

    def setUp(self):
        """Create fresh EventBus before each test."""
        self.bus = EventBus()

    def test_publish_task_queues_callable(self):
        """Verify publish_task queues a callable."""
        task = MagicMock()
        self.bus.publish_task(task)
        tasks = self.bus.drain_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0], task)

    def test_drain_tasks_returns_callables(self):
        """Verify drain_tasks returns list of callables."""
        fn1 = lambda: None
        fn2 = lambda: None
        self.bus.publish_task(fn1)
        self.bus.publish_task(fn2)
        tasks = self.bus.drain_tasks()
        self.assertEqual(len(tasks), 2)

    def test_drain_tasks_empty_queue(self):
        """Verify drain_tasks returns empty list when queue empty."""
        tasks = self.bus.drain_tasks()
        self.assertEqual(tasks, [])

    def test_drain_tasks_clears_queue(self):
        """Verify drain_tasks clears queue after draining."""
        self.bus.publish_task(lambda: None)
        self.bus.drain_tasks()
        tasks = self.bus.drain_tasks()
        self.assertEqual(len(tasks), 0)


class TestEventBusClear(unittest.TestCase):
    """Test EventBus clear() removes all subscribers."""

    def setUp(self):
        """Create fresh EventBus before each test."""
        self.bus = EventBus()

    def test_clear_removes_all_subscribers(self):
        """Verify clear() removes all subscribers."""
        self.bus.subscribe("event1", MagicMock())
        self.bus.subscribe("event2", MagicMock())
        self.bus.clear()
        self.assertEqual(self.bus.get_subscribers("event1"), [])
        self.assertEqual(self.bus.get_subscribers("event2"), [])

    def test_clear_does_not_affect_queues(self):
        """Verify clear() does not clear UI/task queues."""
        self.bus.publish_ui_update("COM3", "status", "BUSY")
        self.bus.publish_task(lambda: None)
        self.bus.clear()
        self.assertEqual(len(self.bus.drain_ui_updates()), 1)
        self.assertEqual(len(self.bus.drain_tasks()), 1)


class TestEventBusThreadSafety(unittest.TestCase):
    """Test EventBus thread safety with concurrent publish/subscribe."""

    def setUp(self):
        """Create fresh EventBus before each test."""
        self.bus = EventBus()

    def test_concurrent_publish_subscribe(self):
        """Verify concurrent publish and subscribe do not crash."""
        errors = []

        def publisher():
            try:
                for i in range(200):
                    self.bus.publish("test.event", f"data_{i}")
            except Exception as e:
                errors.append(e)

        def subscriber():
            try:
                for _ in range(200):
                    self.bus.subscribe("test.event", MagicMock())
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=publisher),
            threading.Thread(target=subscriber),
            threading.Thread(target=publisher),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_concurrent_ui_update_publish_drain(self):
        """Verify concurrent UI update publish and drain do not crash."""
        errors = []

        def publisher():
            try:
                for i in range(200):
                    self.bus.publish_ui_update(f"COM{i % 5}", "status", "BUSY")
            except Exception as e:
                errors.append(e)

        def drainer():
            try:
                for _ in range(200):
                    self.bus.drain_ui_updates()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=publisher),
            threading.Thread(target=drainer),
            threading.Thread(target=publisher),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_concurrent_clear_and_subscribe(self):
        """Verify concurrent clear and subscribe do not crash."""
        errors = []

        def clearer():
            try:
                for _ in range(100):
                    self.bus.clear()
            except Exception as e:
                errors.append(e)

        def subscriber():
            try:
                for _ in range(100):
                    self.bus.subscribe("test.event", MagicMock())
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=clearer),
            threading.Thread(target=subscriber),
            threading.Thread(target=subscriber),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_publish_exception_in_callback_does_not_crash(self):
        """Verify exceptions in callbacks are silently caught."""
        def bad_callback(payload):
            raise RuntimeError("boom")

        self.bus.subscribe("test.event", bad_callback)
        # Should not raise
        self.bus.publish("test.event", "data")

    def test_publish_exception_does_not_break_other_subscribers(self):
        """Verify exception in one subscriber does not break others."""
        def bad_callback(payload):
            raise RuntimeError("boom")

        good_callback = MagicMock()
        self.bus.subscribe("test.event", bad_callback)
        self.bus.subscribe("test.event", good_callback)
        self.bus.publish("test.event", "data")
        good_callback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
