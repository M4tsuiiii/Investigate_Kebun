"""Automation State — Per-port automation state tracking."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Dict, Optional


class AutomationStatus(str, Enum):
    """Automation status for a port."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STANDBY = "STANDBY"
    QUEUED = "QUEUED"
    RETRY_PENDING = "RETRY_PENDING"


class AutomationState:
    """Thread-safe per-port automation state.

    Tracks:
    - Current automation status
    - Current workflow running
    - Last workflow result
    - Last grace value (for retry)
    """

    def __init__(self, port: str) -> None:
        self._port: str = port
        self._lock: threading.RLock = threading.RLock()
        self._status: AutomationStatus = AutomationStatus.IDLE
        self._current_workflow: str = ""
        self._last_workflow: str = ""
        self._last_success: bool = False
        self._last_grace: str = ""
        self._retry_count: int = 0

    @property
    def port(self) -> str:
        return self._port

    @property
    def status(self) -> AutomationStatus:
        with self._lock:
            return self._status

    @property
    def current_workflow(self) -> str:
        with self._lock:
            return self._current_workflow

    @property
    def is_idle(self) -> bool:
        return self.status == AutomationStatus.IDLE

    @property
    def is_running(self) -> bool:
        return self.status == AutomationStatus.RUNNING

    @property
    def is_standby(self) -> bool:
        return self.status == AutomationStatus.STANDBY

    def set_running(self, workflow_name: str) -> None:
        with self._lock:
            self._status = AutomationStatus.RUNNING
            self._current_workflow = workflow_name

    def set_idle(self) -> None:
        with self._lock:
            self._status = AutomationStatus.IDLE
            self._current_workflow = ""

    def set_standby(self) -> None:
        with self._lock:
            self._status = AutomationStatus.STANDBY
            self._current_workflow = ""

    def set_queued(self) -> None:
        with self._lock:
            self._status = AutomationStatus.QUEUED

    def set_retry_pending(self) -> None:
        with self._lock:
            self._status = AutomationStatus.RETRY_PENDING

    def record_result(self, workflow_name: str, success: bool, grace: str = "") -> None:
        with self._lock:
            self._last_workflow = workflow_name
            self._last_success = success
            if grace:
                self._last_grace = grace

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            return {
                "port": self._port,
                "status": self._status.value,
                "current_workflow": self._current_workflow,
                "last_workflow": self._last_workflow,
                "last_success": str(self._last_success),
                "last_grace": self._last_grace,
                "retry_count": str(self._retry_count),
            }
