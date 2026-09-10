"""USSD State Machine — session lifecycle management.

States: IDLE → FENCING → DIALING → READING → PROCESSING → RECOVERY → IDLE

Uses RLock (audit M-13) for reentrant thread safety.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional


# ---------------------------------------------------------------------------
# USSD Session States
# ---------------------------------------------------------------------------

class UssdSessionState(Enum):
    """USSD session lifecycle states."""
    IDLE = "IDLE"
    FENCING = "FENCING"
    DIALING = "DIALING"
    READING = "READING"
    PROCESSING = "PROCESSING"
    RECOVERY = "RECOVERY"


# ---------------------------------------------------------------------------
# Transition Definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UssdTransition:
    """Represents a USSD session state transition."""
    port: str
    old_state: UssdSessionState
    new_state: UssdSessionState
    command: str = ""


# ---------------------------------------------------------------------------
# Valid Transitions
# ---------------------------------------------------------------------------

_VALID_USSD_TRANSITIONS = {
    (UssdSessionState.IDLE, UssdSessionState.FENCING),
    (UssdSessionState.FENCING, UssdSessionState.DIALING),
    (UssdSessionState.DIALING, UssdSessionState.READING),
    (UssdSessionState.READING, UssdSessionState.PROCESSING),
    (UssdSessionState.PROCESSING, UssdSessionState.IDLE),
    (UssdSessionState.PROCESSING, UssdSessionState.RECOVERY),
    (UssdSessionState.RECOVERY, UssdSessionState.IDLE),
    (UssdSessionState.RECOVERY, UssdSessionState.FENCING),
}


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

class UssdStateMachine:
    """USSD session state machine — manages dial lifecycle.

    Uses RLock (audit M-13) for reentrant thread safety.
    """

    def __init__(self, port_name: str):
        self.port_name = port_name
        self.current_state: UssdSessionState = UssdSessionState.IDLE
        self._lock = threading.RLock()
        self._listeners: List[Callable[[UssdTransition], None]] = []

    def subscribe(self, listener: Callable[[UssdTransition], None]) -> None:
        """Register a listener for USSD session transitions."""
        with self._lock:
            self._listeners.append(listener)

    def transition(
        self,
        new_state: UssdSessionState,
        command: str = "",
    ) -> Optional[UssdTransition]:
        """Attempt a USSD session state transition.

        Returns:
            UssdTransition if valid, None if invalid.
        """
        with self._lock:
            old_state = self.current_state

            if (old_state, new_state) not in _VALID_USSD_TRANSITIONS:
                return None

            self.current_state = new_state

            event = UssdTransition(
                port=self.port_name,
                old_state=old_state,
                new_state=new_state,
                command=command,
            )

            for listener in list(self._listeners):
                try:
                    listener(event)
                except Exception:
                    pass

            return event

    def force_idle(self) -> None:
        """Force back to IDLE state (for error recovery)."""
        with self._lock:
            self.current_state = UssdSessionState.IDLE

    @property
    def is_idle(self) -> bool:
        """Whether the session is idle."""
        return self.current_state == UssdSessionState.IDLE

    @property
    def is_active(self) -> bool:
        """Whether the session is currently active."""
        return self.current_state != UssdSessionState.IDLE

    def snapshot(self) -> dict:
        """Return current state as dict for UI/display."""
        with self._lock:
            return {
                "port": self.port_name,
                "ussd_state": self.current_state.value,
            }
