"""Automation Scheduler — Evaluates triggers and manages port scheduling."""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from automation.triggers import Trigger, TriggerEvent
from automation.state import AutomationState, AutomationStatus


class AutomationScheduler:
    """Evaluates triggers and manages port scheduling.

    Responsibilities:
    - Track per-port automation state
    - Evaluate triggers to determine action
    - Provide scheduling decisions
    """

    def __init__(self) -> None:
        self._states: Dict[str, AutomationState] = {}
        self._lock: threading.RLock = threading.RLock()

    def get_state(self, port: str) -> AutomationState:
        """Get or create automation state for a port."""
        with self._lock:
            if port not in self._states:
                self._states[port] = AutomationState(port)
            return self._states[port]

    def evaluate_trigger(self, event: TriggerEvent) -> Optional[str]:
        """Evaluate a trigger event and return action.

        Returns:
            "enqueue" — should enqueue a workflow
            "standby" — should enter standby
            "cancel" — should cancel queued workflow
            None — no action needed
        """
        state = self.get_state(event.port)

        if event.trigger == Trigger.MODEM_ONLINE:
            return "enqueue"

        if event.trigger == Trigger.MODEM_OFFLINE:
            return "cancel"

        if event.trigger == Trigger.SIM_INSERTED:
            if state.is_idle or state.is_standby:
                return "enqueue"

        if event.trigger == Trigger.SIM_REMOVED:
            return "cancel"

        if event.trigger == Trigger.CPIN_READY:
            if state.is_idle or state.is_standby:
                return "enqueue"

        if event.trigger == Trigger.CPIN_REQUIRED:
            return "standby"

        if event.trigger == Trigger.WORKFLOW_SUCCESS:
            return "standby"

        if event.trigger == Trigger.WORKFLOW_FAILED:
            return None

        if event.trigger in (Trigger.USER_MASS_REACTIVATION, Trigger.USER_MASS_CHECK_NUMBER):
            return "enqueue"

        return None

    def list_ports(self) -> List[str]:
        """List all tracked ports."""
        with self._lock:
            return list(self._states.keys())

    def snapshot(self) -> Dict[str, Dict[str, str]]:
        """Snapshot of all port states."""
        with self._lock:
            return {port: state.snapshot() for port, state in self._states.items()}
