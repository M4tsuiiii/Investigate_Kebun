"""Flow State Machine — reactivation workflow state transitions.

States: STABILISASI → CEK_NOMOR → CEK_STATUS → CEK_NIK → CEK_KK → INJECTING → VERIFYING → DONE/GAGAL

Uses RLock (audit M-13) for reentrant thread safety.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

from ..enums import FlowStatus, FailureCode


# ---------------------------------------------------------------------------
# Transition Definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FlowTransition:
    """Represents a reactivation flow state transition."""
    port: str
    old_status: FlowStatus
    new_status: FlowStatus
    failure_code: Optional[FailureCode] = None


# ---------------------------------------------------------------------------
# Valid Transitions
# ---------------------------------------------------------------------------

_VALID_FLOW_TRANSITIONS = {
    (FlowStatus.STABILISASI, FlowStatus.CEK_NOMOR),
    (FlowStatus.STABILISASI, FlowStatus.GAGAL),
    (FlowStatus.CEK_NOMOR, FlowStatus.CEK_STATUS),
    (FlowStatus.CEK_NOMOR, FlowStatus.GAGAL),
    (FlowStatus.CEK_STATUS, FlowStatus.CEK_NIK),
    (FlowStatus.CEK_STATUS, FlowStatus.DONE),
    (FlowStatus.CEK_STATUS, FlowStatus.GAGAL),
    (FlowStatus.CEK_NIK, FlowStatus.CEK_KK),
    (FlowStatus.CEK_NIK, FlowStatus.GAGAL),
    (FlowStatus.CEK_KK, FlowStatus.INJECTING),
    (FlowStatus.CEK_KK, FlowStatus.GAGAL),
    (FlowStatus.INJECTING, FlowStatus.VERIFYING),
    (FlowStatus.INJECTING, FlowStatus.GAGAL),
    (FlowStatus.INJECTING, FlowStatus.DONE),
    (FlowStatus.VERIFYING, FlowStatus.DONE),
    (FlowStatus.VERIFYING, FlowStatus.GAGAL),
}


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

class FlowStateMachine:
    """Reactivation flow state machine — explicit step progression.

    Uses RLock (audit M-13) for reentrant thread safety.
    """

    def __init__(self, port_name: str):
        self.port_name = port_name
        self.current_status: FlowStatus = FlowStatus.STABILISASI
        self._lock = threading.RLock()
        self._listeners: List[Callable[[FlowTransition], None]] = []

    def subscribe(self, listener: Callable[[FlowTransition], None]) -> None:
        """Register a listener for flow transitions."""
        with self._lock:
            self._listeners.append(listener)

    def transition(
        self,
        new_status: FlowStatus,
        failure_code: Optional[FailureCode] = None,
    ) -> Optional[FlowTransition]:
        """Attempt a flow state transition.

        Returns:
            FlowTransition if valid, None if invalid transition.
        """
        with self._lock:
            old_status = self.current_status

            if (old_status, new_status) not in _VALID_FLOW_TRANSITIONS:
                return None

            self.current_status = new_status

            event = FlowTransition(
                port=self.port_name,
                old_status=old_status,
                new_status=new_status,
                failure_code=failure_code,
            )

            for listener in list(self._listeners):
                try:
                    listener(event)
                except Exception:
                    pass

            return event

    def reset(self) -> None:
        """Reset to initial state."""
        with self._lock:
            self.current_status = FlowStatus.STABILISASI

    @property
    def is_done(self) -> bool:
        """Whether the flow has completed successfully."""
        return self.current_status == FlowStatus.DONE

    @property
    def is_failed(self) -> bool:
        """Whether the flow has failed."""
        return self.current_status == FlowStatus.GAGAL

    @property
    def is_active(self) -> bool:
        """Whether the flow is currently active (not DONE or GAGAL)."""
        return self.current_status not in (FlowStatus.DONE, FlowStatus.GAGAL)

    def snapshot(self) -> dict:
        """Return current state as dict for UI/display."""
        with self._lock:
            return {
                "port": self.port_name,
                "flow_status": self.current_status.value,
            }
