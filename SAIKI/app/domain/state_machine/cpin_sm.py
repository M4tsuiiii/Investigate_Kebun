"""CPIN State Machine — manages SIM card CPIN state transitions.

States: READY, NOT_INSERTED, PIN_REQUIRED, NOT_READY, UNKNOWN
Transitions: explicit, event-driven, thread-safe with RLock.

Resolves: 4-way CPIN state ownership (RE-02A), CHECKING overlay stuck (HR-017),
          awaiting_card_cycle stuck (HR-004).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ..enums import CpinState


# ---------------------------------------------------------------------------
# Transition Definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CpinTransition:
    """Represents a CPIN state transition event."""
    port: str
    old_state: CpinState
    new_state: CpinState
    raw_response: str = ""
    is_same_state: bool = False

    @property
    def should_process(self) -> bool:
        """HR-001: PSM early-return guard — skip same-state transitions."""
        return not self.is_same_state


# ---------------------------------------------------------------------------
# Transition Table
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: Dict[Tuple[CpinState, CpinState], str] = {
    (CpinState.UNKNOWN, CpinState.READY): "on_ready",
    (CpinState.NOT_READY, CpinState.READY): "on_ready",
    (CpinState.PIN_REQUIRED, CpinState.READY): "on_ready",
    (CpinState.NOT_INSERTED, CpinState.READY): "on_ready",
    (CpinState.READY, CpinState.NOT_READY): "on_not_ready",
    (CpinState.READY, CpinState.UNKNOWN): "on_unknown_from_ready",
    (CpinState.READY, CpinState.NOT_INSERTED): "on_not_inserted",
    (CpinState.NOT_READY, CpinState.NOT_INSERTED): "on_not_inserted",
    (CpinState.UNKNOWN, CpinState.NOT_INSERTED): "on_not_inserted",
    (CpinState.READY, CpinState.PIN_REQUIRED): "on_pin_required",
    (CpinState.NOT_READY, CpinState.PIN_REQUIRED): "on_pin_required",
}


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

class CpinStateMachine:
    """CPIN state machine — explicit transitions, no implicit logic.

    This is the SINGLE source of truth for CPIN state.
    All other components must observe via this machine.

    Uses RLock (audit M-13) for reentrant thread safety.
    """

    def __init__(self, port_name: str):
        self.port_name = port_name
        self.current_state: CpinState = CpinState.UNKNOWN
        self.awaiting_card_cycle: bool = False
        self.prompt_recovery_count: int = 0
        self._lock = threading.RLock()
        self._listeners: List[Callable[[CpinTransition], None]] = []

    def subscribe(self, listener: Callable[[CpinTransition], None]) -> None:
        """Register a listener for state transitions."""
        with self._lock:
            self._listeners.append(listener)

    def transition(
        self,
        new_state: CpinState,
        raw_response: str = "",
    ) -> Optional[CpinTransition]:
        """Attempt a state transition.

        Returns:
            CpinTransition if transition occurred, None if same state (HR-001 guard).
        """
        with self._lock:
            old_state = self.current_state

            if new_state == old_state:
                return CpinTransition(
                    port=self.port_name,
                    old_state=old_state,
                    new_state=new_state,
                    raw_response=raw_response,
                    is_same_state=True,
                )

            transition_key = (old_state, new_state)
            if transition_key not in _VALID_TRANSITIONS:
                if new_state == CpinState.NOT_INSERTED:
                    action_key = "on_not_inserted"
                else:
                    action_key = "on_unknown"
            else:
                action_key = _VALID_TRANSITIONS[transition_key]

            self.current_state = new_state

            event = CpinTransition(
                port=self.port_name,
                old_state=old_state,
                new_state=new_state,
                raw_response=raw_response,
            )

            self._execute_action(action_key, event)

            for listener in list(self._listeners):
                try:
                    listener(event)
                except Exception:
                    pass

            return event

    def _execute_action(self, action_key: str, event: CpinTransition) -> None:
        """Execute side effects for a state transition."""
        if action_key == "on_ready":
            self._on_ready(event)
        elif action_key == "on_not_inserted":
            self._on_not_inserted(event)
        elif action_key == "on_pin_required":
            self._on_pin_required(event)
        elif action_key == "on_not_ready":
            self._on_not_ready(event)
        elif action_key == "on_unknown_from_ready":
            self._on_unknown_from_ready(event)

    def _on_ready(self, event: CpinTransition) -> None:
        """Actions when entering READY state."""
        self.prompt_recovery_count = 0

    def _on_not_inserted(self, event: CpinTransition) -> None:
        """Actions when entering NOT_INSERTED state."""
        self.awaiting_card_cycle = False

    def _on_pin_required(self, event: CpinTransition) -> None:
        """Actions when entering PIN_REQUIRED state."""
        self.awaiting_card_cycle = False

    def _on_not_ready(self, event: CpinTransition) -> None:
        """Actions when entering NOT_READY state."""
        pass

    def _on_unknown_from_ready(self, event: CpinTransition) -> None:
        """Actions when transitioning from READY to UNKNOWN."""
        pass

    # -----------------------------------------------------------------------
    # Card Cycle Management (BR-012)
    # -----------------------------------------------------------------------

    def require_card_cycle(self) -> None:
        """Set awaiting_card_cycle flag — blocks auto-run until cleared."""
        with self._lock:
            self.awaiting_card_cycle = True

    def clear_card_cycle(self) -> None:
        """Clear awaiting_card_cycle flag."""
        with self._lock:
            self.awaiting_card_cycle = False

    def should_block_auto_run(self, trigger_mode: str) -> bool:
        """Check if auto-run should be blocked.

        BR-011: ALL conditions must pass:
            1. trigger_mode == "Auto-Run on Insert"
            2. current_state != READY (already was READY)
            3. not awaiting_card_cycle
        """
        with self._lock:
            if trigger_mode != "Auto-Run on Insert":
                return True
            if self.current_state == CpinState.READY:
                return True
            if self.awaiting_card_cycle:
                return True
            return False

    # -----------------------------------------------------------------------
    # State Queries
    # -----------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """Whether the SIM is in READY state."""
        return self.current_state == CpinState.READY

    @property
    def is_inserted(self) -> bool:
        """Whether the SIM appears to be physically inserted."""
        return self.current_state not in (CpinState.NOT_INSERTED, CpinState.UNKNOWN)

    def get_state(self) -> CpinState:
        """Thread-safe getter for current state."""
        with self._lock:
            return self.current_state

    def snapshot(self) -> dict:
        """Return current state as dict for UI/display."""
        with self._lock:
            return {
                "port": self.port_name,
                "cpin_state": self.current_state.value,
                "awaiting_card_cycle": self.awaiting_card_cycle,
                "prompt_recovery_count": self.prompt_recovery_count,
            }
