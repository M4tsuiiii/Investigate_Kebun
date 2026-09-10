"""Trigger ID — Thread-safe global counter for unique trigger identification (Sprint 15I)."""

import threading

_counter = 0
_lock = threading.Lock()


def next_trigger_id() -> int:
    """Return next unique trigger ID (globally unique across all sources)."""
    global _counter
    with _lock:
        _counter += 1
        return _counter


def reset_trigger_id() -> None:
    """Reset counter (for testing only)."""
    global _counter
    with _lock:
        _counter = 0
