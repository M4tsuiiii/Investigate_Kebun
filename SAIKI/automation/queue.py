"""Workflow Queue — FIFO queue with priority and concurrency control."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(order=True)
class QueueItem:
    """A queued workflow execution request."""
    priority: int = field(compare=True)
    created_at: float = field(compare=True, default_factory=time.time)
    port: str = field(compare=False, default="")
    workflow_name: str = field(compare=False, default="")
    trigger_id: int = field(compare=False, default=0)

    def __repr__(self) -> str:
        return f"QueueItem(port={self.port!r}, workflow={self.workflow_name!r}, pri={self.priority}, tid={self.trigger_id})"


class WorkflowQueue:
    """Thread-safe FIFO workflow queue with priority ordering.

    Items are ordered by:
    1. Priority (lower = higher priority)
    2. Creation time (FIFO within same priority)
    """

    def __init__(self, max_concurrent: int = 2) -> None:
        self._lock: threading.RLock = threading.RLock()
        self._queue: List[QueueItem] = []
        self._running: int = 0
        self._max_concurrent: int = max_concurrent

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def running_count(self) -> int:
        with self._lock:
            return self._running

    @property
    def available_slots(self) -> int:
        with self._lock:
            return max(0, self._max_concurrent - self._running)

    @property
    def is_full(self) -> bool:
        return self.available_slots == 0

    def enqueue(self, item: QueueItem) -> None:
        """Add item to queue (sorted by priority then time)."""
        with self._lock:
            self._queue.append(item)
            self._queue.sort()

    def dequeue(self) -> Optional[QueueItem]:
        """Remove and return highest priority item. Returns None if empty."""
        with self._lock:
            if self._queue:
                return self._queue.pop(0)
            return None

    def peek(self) -> Optional[QueueItem]:
        """View next item without removing."""
        with self._lock:
            if self._queue:
                return self._queue[0]
            return None

    def acquire_slot(self) -> bool:
        """Try to acquire a running slot. Returns True if acquired."""
        with self._lock:
            if self._running < self._max_concurrent:
                self._running += 1
                return True
            return False

    def release_slot(self) -> None:
        """Release a running slot."""
        with self._lock:
            self._running = max(0, self._running - 1)

    def remove_by_port(self, port: str) -> int:
        """Remove all items for a port. Returns count removed."""
        with self._lock:
            before = len(self._queue)
            self._queue = [item for item in self._queue if item.port != port]
            return before - len(self._queue)

    def clear(self) -> None:
        """Clear all items."""
        with self._lock:
            self._queue.clear()

    def snapshot(self) -> List[Dict[str, str]]:
        """Snapshot of queue contents."""
        with self._lock:
            return [
                {"port": item.port, "workflow": item.workflow_name, "priority": str(item.priority)}
                for item in self._queue
            ]
