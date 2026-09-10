"""Hardware State Machine — modem lifecycle state transitions (Sprint 15E: FSM trace).

States: OFFLINE → MODEM_DETECTED → PORT_READY → SIM_INSERTED → CPIN_READY → READY
Transitions: READY → SIM_REMOVED, READY → OFFLINE, OFFLINE → READY

Uses RLock for reentrant thread safety.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional

logger = logging.getLogger("saiki.hw_sm")


class HwState(Enum):
    """Hardware lifecycle states."""
    OFFLINE = "OFFLINE"
    MODEM_DETECTED = "MODEM_DETECTED"
    PORT_READY = "PORT_READY"
    SIM_INSERTED = "SIM_INSERTED"
    CPIN_READY = "CPIN_READY"
    READY = "READY"
    SIM_REMOVED = "SIM_REMOVED"


@dataclass(frozen=True)
class HwTransition:
    """Hardware state transition event."""
    port: str
    old_state: HwState
    new_state: HwState
    detail: str = ""


_VALID_HW_TRANSITIONS = {
    (HwState.OFFLINE, HwState.MODEM_DETECTED),
    (HwState.MODEM_DETECTED, HwState.PORT_READY),
    (HwState.PORT_READY, HwState.SIM_INSERTED),
    (HwState.SIM_INSERTED, HwState.CPIN_READY),
    (HwState.CPIN_READY, HwState.READY),
    (HwState.READY, HwState.SIM_REMOVED),
    (HwState.READY, HwState.OFFLINE),
    (HwState.SIM_REMOVED, HwState.OFFLINE),
    (HwState.SIM_REMOVED, HwState.SIM_INSERTED),
    (HwState.OFFLINE, HwState.READY),  # Direct reconnect
}


class HwStateMachine:
    """Hardware state machine — manages modem lifecycle.

    Uses RLock for reentrant thread safety.
    """

    def __init__(self, port_name: str) -> None:
        self.port_name: str = port_name
        self.current_state: HwState = HwState.OFFLINE
        self._lock: threading.RLock = threading.RLock()
        self._listeners: List[Callable[[HwTransition], None]] = []

    def subscribe(self, listener: Callable[[HwTransition], None]) -> None:
        """Register a listener for hardware state transitions."""
        with self._lock:
            self._listeners.append(listener)

    def transition(self, new_state: HwState, detail: str = "") -> Optional[HwTransition]:
        """Attempt a hardware state transition.

        Returns:
            HwTransition if transition occurred, None if same state or invalid.
        """
        with self._lock:
            old_state = self.current_state

            if old_state == new_state:
                return None

            if (old_state, new_state) not in _VALID_HW_TRANSITIONS:
                logger.info("[FSM TRACE] PORT=%s EVENT REJECTED: %s→%s (detail=%s)", self.port_name, old_state.value, new_state.value, detail)
                return None

            self.current_state = new_state

            event = HwTransition(
                port=self.port_name,
                old_state=old_state,
                new_state=new_state,
                detail=detail,
            )

            logger.info("[FSM TRACE] PORT=%s EVENT ACCEPTED: %s→%s (detail=%s)", self.port_name, old_state.value, new_state.value, detail)

            for listener in list(self._listeners):
                try:
                    listener(event)
                except Exception:
                    pass

            return event

    def force_offline(self) -> None:
        """Force state to OFFLINE regardless of current state."""
        with self._lock:
            self.current_state = HwState.OFFLINE

    @property
    def is_ready(self) -> bool:
        """Whether the hardware is in READY state."""
        return self.current_state == HwState.READY

    @property
    def is_online(self) -> bool:
        """Whether the hardware is online (not OFFLINE or SIM_REMOVED)."""
        return self.current_state not in (HwState.OFFLINE, HwState.SIM_REMOVED)

    def snapshot(self) -> dict:
        """Return current state as dict for UI/display."""
        with self._lock:
            return {
                "port": self.port_name,
                "hw_state": self.current_state.value,
            }
