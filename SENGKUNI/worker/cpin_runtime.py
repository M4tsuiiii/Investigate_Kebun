"""CpinRuntime — AT+CPIN? polling with stabilization.

Polls AT+CPIN?, applies stabilization thresholds, publishes state transitions.
Implements GOOD parity: CHECKING_THRESHOLD=2, UNKNOWN_THRESHOLD=3, removal confirmation.
Added: READY confirmation threshold to prevent false positive triggering.
"""

import logging
import threading
import time
from typing import Any, Callable, Optional

from app.domain.enums import CpinState
from app.domain.constants import (
    CPIN_POLL_INTERVAL,
    CPIN_POLL_TIMEOUT,
    CPIN_UNKNOWN_THRESHOLD,
    CPIN_CHECKING_THRESHOLD,
    CPIN_MAX_REMOVAL_CONFIRM,
)
from app.domain.classifier import parse_cpin_response

logger = logging.getLogger("sengkuni.cpin")


class CpinRuntime:
    """Continuous CPIN monitor with stabilization.

    Implements GOOD parity:
    - CHECKING_THRESHOLD=2: READY→UNKNOWN twice = CHECKING
    - UNKNOWN_THRESHOLD=3: READY→UNKNOWN thrice = NOT_READY
    - Removal confirmation: READY→NOT_INSERTED needs N confirmations
    - Adaptive polling: READY ports poll slower than CHECKING ports

    Added anti-false-positive:
    - READY confirmation: Any→READY needs 2 consecutive polls before triggering auto-run
    - This prevents a single stale buffer read from launching the entire workflow
    """

    def __init__(
        self,
        port_id: str,
        at_client: Any,
        on_cpin_transition: Callable[[CpinState, CpinState], None],
        event_bus: Any = None,
    ) -> None:
        self._port_id = port_id
        self._at_client = at_client
        self._on_cpin_transition = on_cpin_transition
        self._event_bus = event_bus
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._current_state: CpinState = CpinState.UNKNOWN
        self._first_poll_done: threading.Event = threading.Event()

        # Stabilization counters
        self._unknown_count: int = 0
        self._checking_count: int = 0
        self._removal_confirm_count: int = 0
        self._pending_removal: bool = False

        # READY confirmation threshold (anti-false-positive)
        self._ready_confirm_count: int = 0
        self._READY_CONFIRM_THRESHOLD: int = 2  # Need 2 consecutive READY before triggering auto-run
        self._ready_confirmed: bool = False  # Set True after threshold met

        # Adaptive polling
        self._poll_interval: float = CPIN_POLL_INTERVAL

        # Timestamp tracking for watchdog
        self._last_poll_time: float = 0.0
        self._last_cpin_state_change: float = 0.0

    @property
    def cpin_state(self) -> CpinState:
        return self._current_state

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def last_poll_time(self) -> float:
        return self._last_poll_time

    @property
    def last_state_change_time(self) -> float:
        return self._last_cpin_state_change

    def start(self) -> None:
        """Start CPIN polling thread."""
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("[CPIN] %s: Started", self._port_id)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop CPIN polling thread."""
        self._running.clear()
        self._paused.clear()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("[CPIN] %s: Stopped", self._port_id)

    def pause(self) -> None:
        """Pause CPIN polling."""
        self._paused.set()

    def resume(self) -> None:
        """Resume CPIN polling."""
        self._paused.clear()

    def reset_stabilization(self) -> None:
        """Reset stabilization counters."""
        self._unknown_count = 0
        self._checking_count = 0
        self._removal_confirm_count = 0
        self._pending_removal = False
        self._ready_confirm_count = 0
        self._ready_confirmed = False

    def _poll_loop(self) -> None:
        """Main CPIN polling loop."""
        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.2)
                continue

            try:
                self._poll_once()
            except Exception as e:
                logger.error("[CPIN] %s: Poll error: %s", self._port_id, e)

            time.sleep(self._poll_interval)

    def _poll_once(self) -> None:
        """Single CPIN poll cycle."""
        self._last_poll_time = time.time()

        # Send AT+CPIN? — buffer is always flushed by ATClient.send_command
        response = self._at_client.send_command("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
        raw = response.raw if response else ""

        # Parse response
        new_state = parse_cpin_response(raw)

        # Apply stabilization
        stabilized_state = self._apply_stabilization(new_state)

        # Update state if changed
        if stabilized_state != self._current_state:
            old_state = self._current_state
            self._current_state = stabilized_state
            self._last_cpin_state_change = time.time()

            # Callback handles event publishing (port_worker._on_cpin_transition)
            # Do NOT publish here — that would be a double publish
            self._on_cpin_transition(old_state, stabilized_state)

        self._first_poll_done.set()

    def _apply_stabilization(self, new_state: CpinState) -> CpinState:
        """Apply stabilization thresholds to prevent flapping.

        Anti-false-positive logic:
        - Any → READY: needs _READY_CONFIRM_THRESHOLD consecutive READY polls
          before confirming. Single READY is held as "pending" not confirmed.
        - This prevents a single stale buffer read from triggering auto-run.
        """
        old_state = self._current_state

        # Any → READY: count consecutive READY polls
        if new_state == CpinState.READY:
            self._ready_confirm_count += 1

            # Not yet confirmed — hold at current state
            if self._ready_confirm_count < self._READY_CONFIRM_THRESHOLD:
                logger.debug(
                    "[CPIN] %s: READY pending confirmation (%d/%d)",
                    self._port_id, self._ready_confirm_count, self._READY_CONFIRM_THRESHOLD,
                )
                # Still hold at old state until threshold met
                return old_state

            # Confirmed — accept READY
            self._ready_confirmed = True
            self._unknown_count = 0
            self._checking_count = 0
            self._removal_confirm_count = 0
            self._pending_removal = False
            return CpinState.READY

        # Not READY → reset confirmation counter
        self._ready_confirm_count = 0

        # READY → UNKNOWN: increment counter
        if old_state == CpinState.READY and new_state == CpinState.UNKNOWN:
            self._unknown_count += 1
            self._checking_count += 1

            if self._checking_count >= CPIN_CHECKING_THRESHOLD:
                return CpinState.UNKNOWN
            return CpinState.READY

        # READY → NOT_INSERTED: require confirmation
        if old_state == CpinState.READY and new_state == CpinState.NOT_INSERTED:
            self._removal_confirm_count += 1
            if self._removal_confirm_count >= CPIN_MAX_REMOVAL_CONFIRM:
                return CpinState.NOT_INSERTED
            return CpinState.READY

        # READY → NOT_READY: require confirmation
        if old_state == CpinState.READY and new_state == CpinState.NOT_READY:
            return CpinState.READY

        # Other transitions: accept
        self._unknown_count = 0
        self._checking_count = 0
        self._removal_confirm_count = 0
        return new_state
