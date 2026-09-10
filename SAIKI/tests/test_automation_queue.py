"""Tests for automation.queue — WorkflowQueue and QueueItem."""

import unittest

from automation.queue import WorkflowQueue, QueueItem


class TestQueueItem(unittest.TestCase):
    """Test QueueItem dataclass — queued workflow request."""

    def test_repr(self) -> None:
        """Verify QueueItem repr format."""
        item = QueueItem(priority=10, port="COM3", workflow_name="reactivate_full")
        r = repr(item)
        self.assertIn("COM3", r)
        self.assertIn("reactivate_full", r)
        self.assertIn("pri=10", r)

    def test_ordering_by_priority(self) -> None:
        """Verify QueueItem ordering by priority then time."""
        a = QueueItem(priority=10, port="COM3", created_at=1.0)
        b = QueueItem(priority=5, port="COM5", created_at=2.0)
        self.assertLess(b, a)

    def test_ordering_by_time_same_priority(self) -> None:
        """Verify QueueItem uses creation time as tiebreaker."""
        a = QueueItem(priority=10, port="COM3", created_at=1.0)
        b = QueueItem(priority=10, port="COM5", created_at=2.0)
        self.assertLess(a, b)


class TestWorkflowQueue(unittest.TestCase):
    """Test WorkflowQueue — FIFO queue with priority ordering."""

    def test_enqueue_and_dequeue(self) -> None:
        """Verify enqueue adds item and dequeue removes it."""
        q = WorkflowQueue()
        item = QueueItem(priority=10, port="COM3", workflow_name="check_data")
        q.enqueue(item)
        self.assertEqual(q.size, 1)
        result = q.dequeue()
        self.assertIsNotNone(result)
        self.assertEqual(result.port, "COM3")
        self.assertEqual(q.size, 0)

    def test_fifo_ordering(self) -> None:
        """Verify FIFO ordering within same priority."""
        q = WorkflowQueue()
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="a", created_at=1.0))
        q.enqueue(QueueItem(priority=10, port="COM5", workflow_name="b", created_at=2.0))
        q.enqueue(QueueItem(priority=10, port="COM7", workflow_name="c", created_at=3.0))

        first = q.dequeue()
        second = q.dequeue()
        third = q.dequeue()
        self.assertEqual(first.port, "COM3")
        self.assertEqual(second.port, "COM5")
        self.assertEqual(third.port, "COM7")

    def test_priority_ordering(self) -> None:
        """Verify lower priority number dequeues first."""
        q = WorkflowQueue()
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="low", created_at=1.0))
        q.enqueue(QueueItem(priority=5, port="COM5", workflow_name="high", created_at=2.0))
        q.enqueue(QueueItem(priority=15, port="COM7", workflow_name="lowest", created_at=3.0))

        first = q.dequeue()
        second = q.dequeue()
        third = q.dequeue()
        self.assertEqual(first.port, "COM5")
        self.assertEqual(second.port, "COM3")
        self.assertEqual(third.port, "COM7")

    def test_peek_does_not_remove(self) -> None:
        """Verify peek returns item without removing it."""
        q = WorkflowQueue()
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="check_data"))
        peeked = q.peek()
        self.assertIsNotNone(peeked)
        self.assertEqual(q.size, 1)

    def test_peek_returns_none_when_empty(self) -> None:
        """Verify peek returns None on empty queue."""
        q = WorkflowQueue()
        self.assertIsNone(q.peek())

    def test_dequeue_returns_none_when_empty(self) -> None:
        """Verify dequeue returns None on empty queue."""
        q = WorkflowQueue()
        self.assertIsNone(q.dequeue())

    def test_acquire_slot_success(self) -> None:
        """Verify acquire_slot returns True when slot available."""
        q = WorkflowQueue(max_concurrent=2)
        self.assertTrue(q.acquire_slot())
        self.assertEqual(q.running_count, 1)

    def test_acquire_slot_failure_when_full(self) -> None:
        """Verify acquire_slot returns False when all slots occupied."""
        q = WorkflowQueue(max_concurrent=1)
        self.assertTrue(q.acquire_slot())
        self.assertFalse(q.acquire_slot())

    def test_release_slot(self) -> None:
        """Verify release_slot frees a slot."""
        q = WorkflowQueue(max_concurrent=2)
        q.acquire_slot()
        q.acquire_slot()
        self.assertTrue(q.is_full)
        q.release_slot()
        self.assertFalse(q.is_full)
        self.assertEqual(q.running_count, 1)

    def test_release_slot_floors_at_zero(self) -> None:
        """Verify release_slot does not go below 0."""
        q = WorkflowQueue(max_concurrent=2)
        q.release_slot()
        self.assertEqual(q.running_count, 0)

    def test_available_slots(self) -> None:
        """Verify available_slots reflects remaining capacity."""
        q = WorkflowQueue(max_concurrent=3)
        self.assertEqual(q.available_slots, 3)
        q.acquire_slot()
        self.assertEqual(q.available_slots, 2)
        q.acquire_slot()
        self.assertEqual(q.available_slots, 1)
        q.release_slot()
        self.assertEqual(q.available_slots, 2)

    def test_is_full(self) -> None:
        """Verify is_full returns True only when all slots occupied."""
        q = WorkflowQueue(max_concurrent=1)
        self.assertFalse(q.is_full)
        q.acquire_slot()
        self.assertTrue(q.is_full)
        q.release_slot()
        self.assertFalse(q.is_full)

    def test_remove_by_port(self) -> None:
        """Verify remove_by_port removes matching items and returns count."""
        q = WorkflowQueue()
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="a"))
        q.enqueue(QueueItem(priority=10, port="COM5", workflow_name="b"))
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="c"))

        removed = q.remove_by_port("COM3")
        self.assertEqual(removed, 2)
        self.assertEqual(q.size, 1)

    def test_remove_by_port_nonexistent(self) -> None:
        """Verify remove_by_port returns 0 for unknown port."""
        q = WorkflowQueue()
        removed = q.remove_by_port("COM99")
        self.assertEqual(removed, 0)

    def test_clear(self) -> None:
        """Verify clear empties the queue."""
        q = WorkflowQueue()
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="a"))
        q.enqueue(QueueItem(priority=10, port="COM5", workflow_name="b"))
        q.clear()
        self.assertEqual(q.size, 0)

    def test_snapshot(self) -> None:
        """Verify snapshot returns list of dicts for queue items."""
        q = WorkflowQueue()
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="check_data"))
        q.enqueue(QueueItem(priority=5, port="COM5", workflow_name="reactivate_full"))
        snap = q.snapshot()
        self.assertEqual(len(snap), 2)
        self.assertEqual(snap[0]["port"], "COM5")
        self.assertEqual(snap[0]["workflow"], "reactivate_full")
        self.assertEqual(snap[0]["priority"], "5")

    def test_size(self) -> None:
        """Verify size reflects current queue length."""
        q = WorkflowQueue()
        self.assertEqual(q.size, 0)
        q.enqueue(QueueItem(priority=10, port="COM3", workflow_name="a"))
        self.assertEqual(q.size, 1)
        q.dequeue()
        self.assertEqual(q.size, 0)

    def test_running_count(self) -> None:
        """Verify running_count tracks acquired slots."""
        q = WorkflowQueue(max_concurrent=3)
        self.assertEqual(q.running_count, 0)
        q.acquire_slot()
        q.acquire_slot()
        self.assertEqual(q.running_count, 2)
        q.release_slot()
        self.assertEqual(q.running_count, 1)


if __name__ == "__main__":
    unittest.main()
