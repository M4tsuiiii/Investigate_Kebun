"""Thread-safe UI update queue — decouples worker threads from Tkinter.

Workers never touch Tkinter directly. They enqueue updates here.
The main thread drain loop applies them in batch.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple


class UpdateQueue:
    """Thread-safe queue for UI column updates.

    Usage from worker thread:
        queue.put(port="COM3", column="status", value="READY")

    Usage from main thread:
        updates = queue.drain()
        for port, col, val in updates:
            apply_to_tree(port, col, val)
    """

    def __init__(self, max_batch: int = 1500):
        self._queue: queue.Queue = queue.Queue()
        self._max_batch = max_batch
        self._lock = threading.Lock()

    def put(self, port: str, column: str, value: Any) -> None:
        """Enqueue a column update. Thread-safe from any thread."""
        self._queue.put((port, column, value))

    def drain(self) -> List[Tuple[str, str, Any]]:
        """Drain all pending updates. Returns deduplicated latest values.

        Called from main thread only. Deduplicates by (port, column) key,
        keeping only the latest value for each cell.
        """
        latest: Dict[Tuple[str, str], Any] = {}
        count = 0
        while count < self._max_batch:
            try:
                port, column, value = self._queue.get_nowait()
                latest[(port, column)] = value
                count += 1
            except queue.Empty:
                break
        return [(port, col, val) for (port, col), val in latest.items()]

    def qsize(self) -> int:
        """Approximate queue size."""
        return self._queue.qsize()

    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()

    def clear(self) -> None:
        """Discard all pending updates."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


class TaskQueue:
    """Thread-safe queue for callable tasks to run on the main thread.

    Usage from worker thread:
        queue.put(lambda: messagebox.showinfo("Done", "OK"))

    Usage from main thread:
        tasks = queue.drain()
        for task in tasks:
            task()
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

    def put(self, task: Callable[[], None]) -> None:
        """Enqueue a callable task. Thread-safe from any thread."""
        self._queue.put(task)

    def drain(self) -> List[Callable[[], None]]:
        """Drain all pending tasks. Returns list of callables."""
        tasks = []
        while True:
            try:
                tasks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return tasks

    def qsize(self) -> int:
        """Approximate queue size."""
        return self._queue.qsize()

    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()
