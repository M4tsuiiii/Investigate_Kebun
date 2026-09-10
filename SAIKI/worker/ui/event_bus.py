"""EventBus — Thread-safe pub/sub for worker-UI communication."""
import logging
import threading
import queue
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("saiki.event_bus")


class EventBus:
    """Thread-safe event bus with UI update queue.
    
    Two communication patterns:
    1. Direct publish/subscribe for events
    2. Queued updates for UI (thread-safe)
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: Dict[str, List[Callable]] = {}
        self._ui_queue = queue.Queue()
        self._task_queue = queue.Queue()
    
    def subscribe(self, event_name: str, callback: Callable):
        """Subscribe to an event."""
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            self._subscribers[event_name].append(callback)
    
    def unsubscribe(self, event_name: str, callback: Callable):
        """Unsubscribe from an event."""
        with self._lock:
            if event_name in self._subscribers:
                self._subscribers[event_name] = [
                    cb for cb in self._subscribers[event_name]
                    if cb != callback
                ]
    
    def publish(self, event_name: str, payload: Any = None):
        """Publish an event to all subscribers.
        
        Sprint 15S.1: Logs [COMMAND DELIVERY FAILED] when no subscribers
        or when a handler raises an exception.
        """
        with self._lock:
            callbacks = self._subscribers.get(event_name, []).copy()

        if not callbacks and event_name.startswith("cmd."):
            logger.warning("[COMMAND DELIVERY FAILED] EVENT=%s STAGE=event_subscription REASON=no_subscribers", event_name)
            return
        
        for callback in callbacks:
            try:
                callback(payload)
            except Exception as exc:
                logger.error("[COMMAND DELIVERY FAILED] EVENT=%s STAGE=handler REASON=%s: %s",
                             event_name, type(exc).__name__, exc)
    
    def publish_ui_update(self, port: str, column: str, value: str):
        """Queue a UI update (thread-safe)."""
        self._ui_queue.put((port, column, value))
    
    def publish_task(self, task: Callable):
        """Queue a task for main thread execution."""
        self._task_queue.put(task)
    
    def drain_ui_updates(self) -> list:
        """Drain UI updates (deduplicated, max 1500)."""
        updates = {}
        count = 0
        while not self._ui_queue.empty() and count < 1500:
            try:
                port, col, val = self._ui_queue.get_nowait()
                updates[(port, col)] = (port, col, val)
                count += 1
            except queue.Empty:
                break
        return list(updates.values())
    
    def drain_tasks(self) -> list:
        """Drain task queue."""
        tasks = []
        while not self._task_queue.empty():
            try:
                tasks.append(self._task_queue.get_nowait())
            except queue.Empty:
                break
        return tasks
    
    def get_subscribers(self, event_name: str) -> list:
        with self._lock:
            return self._subscribers.get(event_name, []).copy()
    
    def has_subscribers(self, event_name: str) -> bool:
        """Check if an event has any subscribers."""
        with self._lock:
            return len(self._subscribers.get(event_name, [])) > 0
    
    def clear(self):
        """Clear all subscribers."""
        with self._lock:
            self._subscribers.clear()
