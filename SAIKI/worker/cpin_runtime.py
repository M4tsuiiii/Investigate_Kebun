"""CpinRuntime — AT+CPIN? polling with stabilization (Sprint 15F, 15K).

Polls AT+CPIN?, applies stabilization thresholds, publishes state transitions.
Implements GOOD parity: CHECKING_THRESHOLD=2, UNKNOWN_THRESHOLD=3, removal confirmation.

Sprint 15K additions:
- P1-001: Confirmation poll before state flip (READY→bad)
- P1-002: Flush serial buffer before CPIN query
- P1-003: Reset cleanup method
- Beta stats per port
"""

import logging
import threading
import time
from typing import Any, Optional

from app.domain.enums import CpinState
from app.domain.constants import (
    CPIN_POLL_INTERVAL,
    CPIN_POLL_TIMEOUT,
    CPIN_UNKNOWN_THRESHOLD,
    CPIN_CHECKING_THRESHOLD,
    CPIN_MAX_REMOVAL_CONFIRM,
)
from app.domain.classifier import parse_cpin_response

logger = logging.getLogger("saiki.cpin")


class BetaStats:
    """Runtime statistics per port for beta validation (Sprint 15K)."""

    def __init__(self) -> None:
        self.ready_count: int = 0
        self.not_ready_count: int = 0
        self.unknown_count: int = 0
        self.ready_to_not_ready: int = 0
        self.not_ready_to_ready: int = 0
        self.confirmation_poll_triggered: int = 0
        self.confirmation_poll_prevented: int = 0
        self.buffer_flush_count: int = 0
        self.cpin_poll_count: int = 0

    def format_report(self, port_id: str) -> str:
        return (
            f"[BETA STATS] PORT={port_id}\n"
            f"READY_COUNT={self.ready_count}\n"
            f"NOT_READY_COUNT={self.not_ready_count}\n"
            f"UNKNOWN_COUNT={self.unknown_count}\n"
            f"READY_TO_NOT_READY={self.ready_to_not_ready}\n"
            f"NOT_READY_TO_READY={self.not_ready_to_ready}\n"
            f"CONFIRMATION_POLL_TRIGGERED={self.confirmation_poll_triggered}\n"
            f"CONFIRMATION_POLL_PREVENTED={self.confirmation_poll_prevented}\n"
            f"BUFFER_FLUSH_COUNT={self.buffer_flush_count}\n"
            f"CPIN_POLL_COUNT={self.cpin_poll_count}"
        )


class CpinRuntime:
    """Continuous CPIN monitor with stabilization (Sprint 15F, 15K).

    Implements GOOD parity:
    - CHECKING_THRESHOLD=2: READY→UNKNOWN twice = CHECKING
    - UNKNOWN_THRESHOLD=3: READY→UNKNOWN thrice = NOT_READY
    - Removal confirmation: READY→NOT_INSERTED needs N confirmations
    - Adaptive polling: READY ports poll slower than CHECKING ports

    Sprint 15K additions:
    - P1-001: Confirmation poll before state flip
    - P1-002: Flush serial buffer before CPIN query
    - P1-003: Reset cleanup method
    """

    def __init__(self, port_id: str, at_client: Any, event_bus: Any) -> None:
        self._port_id = port_id
        self._at_client = at_client
        self._event_bus = event_bus
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._current_state: CpinState = CpinState.UNKNOWN
        self._first_poll_done: threading.Event = threading.Event()

        # Stabilization counters (Sprint 15F)
        self._unknown_count: int = 0
        self._checking_count: int = 0
        self._removal_confirm_count: int = 0
        self._pending_removal: bool = False

        # Adaptive polling (Sprint 15F)
        self._poll_interval: float = CPIN_POLL_INTERVAL

        # Beta stats (Sprint 15K)
        self._beta_stats = BetaStats()

    @property
    def cpin_state(self) -> CpinState:
        return self._current_state

    @property
    def first_poll_done(self) -> bool:
        """Check if first CPIN poll has completed."""
        return self._first_poll_done.is_set()

    @property
    def beta_stats(self) -> BetaStats:
        return self._beta_stats

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"CPIN-{self._port_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("[CPIN STARTED] PORT=%s", self._port_id)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop CPIN polling and join thread (Sprint 15O).

        Ensures thread has exited before returning.
        """
        logger.info("[CPIN PAUSE] PORT=%s REASON=stop", self._port_id)
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("[CPIN STOPPED] PORT=%s THREAD_EXITED=NO TIMEOUT=%.1f",
                               self._port_id, timeout)
            else:
                logger.info("[CPIN STOPPED] PORT=%s THREAD_EXITED=YES", self._port_id)
        else:
            logger.info("[CPIN STOPPED] PORT=%s THREAD_EXITED=YES (no thread)", self._port_id)
        self._thread = None

    def reset_stabilization(self) -> None:
        """Reset all stabilization counters and state (P1-003).

        Called on hardware restart, worker recreation, port reconnect.
        """
        self._unknown_count = 0
        self._checking_count = 0
        self._removal_confirm_count = 0
        self._pending_removal = False
        logger.debug("[RESET CLEANUP] PORT=%s CPIN_RUNTIME_RESET=YES", self._port_id)

    def _poll_loop(self) -> None:
        while self._running.is_set():
            try:
                self._poll_once()
            except Exception:
                pass
            time.sleep(self._poll_interval)

    # ------------------------------------------------------------------
    # P1-002: Buffer Flush
    # ------------------------------------------------------------------

    def _flush_buffers(self) -> None:
        """Flush serial input/output buffers before CPIN query (P1-002)."""
        serial = getattr(self._at_client, '_serial', None)
        if serial and hasattr(serial, 'reset_input_buffer'):
            serial_id = id(serial)
            is_open = serial.is_open if hasattr(serial, 'is_open') else False
            logger.debug("[PORT OWNERSHIP] ROLE=CPIN_RUNTIME PORT=%s SERIAL_ID=%d ACTION=flush_buffers IS_OPEN=%s REACH_IN=at_client._serial",
                         self._port_id, serial_id, is_open)
            serial.reset_input_buffer()
            serial.reset_output_buffer()
            self._beta_stats.buffer_flush_count += 1
            logger.debug("[BUFFER FLUSH] PORT=%s BEFORE_CPIN=YES", self._port_id)

    # ------------------------------------------------------------------
    # CPIN Poll (single AT+CPIN? cycle)
    # ------------------------------------------------------------------

    def _send_cpin_query(self) -> tuple:
        """Send AT+CPIN? and return (raw_original, raw_state).

        Shared by main poll and confirmation poll.
        """
        response = self._at_client.send_command("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
        raw_original = response.raw
        raw = response.raw if response.raw else ""
        raw_state = parse_cpin_response(raw_original)
        return raw_original, raw_state

    def _poll_once(self) -> None:
        if not self._at_client:
            return

        self._beta_stats.cpin_poll_count += 1

        # ---- PORT OWNERSHIP TRACE ----
        serial_ref = getattr(self._at_client, '_serial', None)
        serial_id = id(serial_ref) if serial_ref else 0
        is_open = serial_ref.is_open if serial_ref and hasattr(serial_ref, 'is_open') else False
        logger.debug("[PORT OWNERSHIP] ROLE=CPIN_RUNTIME PORT=%s SERIAL_ID=%d ACTION=poll IS_OPEN=%s POLL=%d",
                     self._port_id, serial_id, is_open, self._beta_stats.cpin_poll_count)

        # P1-002: Flush before query
        self._flush_buffers()

        # ---- RAW MODEM TRACE ----
        logger.debug("[CPIN TRACE] PORT=%s", self._port_id)
        logger.debug("[CPIN TRACE] SEND: AT+CPIN?")

        raw_original, raw_state = self._send_cpin_query()

        raw = raw_original if raw_original else ""
        lines = raw.split("\n") if raw else []
        logger.debug("[CPIN TRACE] RAW RESPONSE:\n%s", raw if raw else "(empty)")
        logger.debug("[CPIN TRACE] HEX: %s", raw.encode().hex() if raw else "(empty)")
        logger.debug("[CPIN TRACE] LINES:")
        for i, line in enumerate(lines):
            logger.debug("[CPIN TRACE]   [%d] %s", i, line)

        # ---- PARSER TRACE ----
        previous = self._current_state
        logger.debug("[CPIN PARSE] INPUT: %r", raw_original)
        logger.debug("[CPIN PARSE] OUTPUT: %s", raw_state.value)
        if raw_state == CpinState.UNKNOWN:
            logger.info("[CPIN PARSE] RESULT=UNKNOWN REASON=no known token matched in: %r", raw_original)

        # ---- STABILIZATION (Sprint 15F) ----
        needs_confirmation, candidate_state = self._check_confirmation_needed(previous, raw_state)

        if needs_confirmation:
            # P1-001: Confirmation poll before state flip
            self._beta_stats.confirmation_poll_triggered += 1
            logger.info(
                "[CONFIRMATION POLL] PORT=%s CURRENT=%s CANDIDATE=%s",
                self._port_id, previous.value, candidate_state.value,
            )

            # Flush before confirmation poll too
            self._flush_buffers()

            _, confirm_state = self._send_cpin_query()
            logger.info("[CONFIRMATION POLL] RESULT=%s", confirm_state.value)

            if confirm_state == CpinState.READY:
                # Confirmation returned READY — ignore the bad state
                self._beta_stats.confirmation_poll_prevented += 1
                logger.info("[CONFIRMATION POLL] PORT=%s ACTION=IGNORE", self._port_id)
                new_state = previous
            else:
                # Confirmation still bad — proceed with transition
                logger.info("[CONFIRMATION POLL] PORT=%s ACTION=TRANSITION", self._port_id)
                new_state = confirm_state
        else:
            new_state = self._apply_stabilization(previous, raw_state)

        # ---- CPIN RUNTIME TRACE ----
        changed = new_state != previous
        logger.debug("[CPIN STATE] PREVIOUS: %s", previous.value)
        logger.debug("[CPIN STATE] CURRENT: %s", new_state.value)
        if changed:
            logger.info("[CPIN STATE] CHANGED: YES PREVIOUS=%s CURRENT=%s", previous.value, new_state.value)

        if changed:
            self._current_state = new_state
            self._update_poll_interval(new_state)
            self._track_state_change(previous, new_state)
            if self._event_bus:
                logger.info("[CPIN EVENT] PUBLISH cpin.transition PORT=%s OLD=%s NEW=%s", self._port_id, previous.value, new_state.value)
                self._event_bus.publish("cpin.transition", {
                    "port": self._port_id,
                    "old": previous.value,
                    "new": new_state.value,
                })

        # Mark first poll as done
        if not self._first_poll_done.is_set():
            self._first_poll_done.set()

    # ------------------------------------------------------------------
    # P1-001: Confirmation Check
    # ------------------------------------------------------------------

    def _check_confirmation_needed(self, previous: CpinState, raw_state: CpinState) -> tuple:
        """Check if a confirmation poll is needed before flipping from READY.

        Returns (needs_confirmation: bool, candidate_state: CpinState).
        """
        # Only triggered when previous is READY
        if previous != CpinState.READY:
            return False, raw_state

        # READY stays READY — no confirmation needed
        if raw_state == CpinState.READY:
            return False, raw_state

        # READY → NOT_READY: always confirm (P1-001)
        if raw_state == CpinState.NOT_READY:
            return True, raw_state

        # READY → UNKNOWN: confirm only at or above threshold
        if raw_state == CpinState.UNKNOWN and self._unknown_count < CPIN_UNKNOWN_THRESHOLD:
            return False, raw_state

        # READY → NOT_INSERTED: confirm only at or above threshold
        if raw_state == CpinState.NOT_INSERTED and self._removal_confirm_count < CPIN_MAX_REMOVAL_CONFIRM:
            return False, raw_state

        # READY → PIN_REQUIRED or other bad state: always confirm
        return True, raw_state

    # ------------------------------------------------------------------
    # Beta Stats Tracking
    # ------------------------------------------------------------------

    def _track_state_change(self, old: CpinState, new: CpinState) -> None:
        """Track state transitions for beta stats."""
        if new == CpinState.READY:
            self._beta_stats.ready_count += 1
            if old == CpinState.NOT_READY:
                self._beta_stats.not_ready_to_ready += 1
        elif new == CpinState.NOT_READY:
            self._beta_stats.not_ready_count += 1
            if old == CpinState.READY:
                self._beta_stats.ready_to_not_ready += 1
        elif new == CpinState.UNKNOWN:
            self._beta_stats.unknown_count += 1

    # ------------------------------------------------------------------
    # Stabilization
    # ------------------------------------------------------------------

    def _apply_stabilization(self, previous: CpinState, raw_state: CpinState) -> CpinState:
        """Apply stabilization thresholds to prevent flickering (Sprint 15F).

        Rules:
        1. READY→UNKNOWN: increment counter, don't flip immediately
           - count >= CHECKING_THRESHOLD(2): emit CHECKING
           - count >= UNKNOWN_THRESHOLD(3): flip to NOT_READY
        2. READY→NOT_INSERTED: require confirmation retries
           - count >= CPIN_MAX_REMOVAL_CONFIRM(2): final NOT_INSERTED
        3. Any known state→READY: reset counters, flip immediately
        4. UNKNOWN→anything stable: reset counters
        """
        logger.debug("[CPIN STABILIZE] prev=%s raw=%s unknown_count=%d checking_count=%d removal_count=%d",
                     previous.value, raw_state.value, self._unknown_count, self._checking_count, self._removal_confirm_count)

        # Case 1: READY → UNKNOWN (possible SIM busy or removal)
        if previous == CpinState.READY and raw_state == CpinState.UNKNOWN:
            self._unknown_count += 1
            self._checking_count += 1
            logger.debug("[CPIN STABILIZE] READY→UNKNOWN: unknown=%d checking=%d", self._unknown_count, self._checking_count)

            if self._unknown_count >= CPIN_UNKNOWN_THRESHOLD:
                # Final confirmation — downgrade to NOT_READY
                logger.info("[CPIN STABILIZE] UNKNOWN_THRESHOLD reached → NOT_READY")
                self._unknown_count = 0
                self._checking_count = 0
                return CpinState.NOT_READY
            elif self._checking_count >= CPIN_CHECKING_THRESHOLD:
                # Intermediate — still CHECKING, don't flip state yet
                logger.debug("[CPIN STABILIZE] CHECKING_THRESHOLD reached → stay CHECKING (no state flip)")
                return previous  # Keep READY until confirmed
            else:
                # Below threshold — keep previous state (don't flicker)
                logger.debug("[CPIN STABILIZE] Below threshold → keep %s", previous.value)
                return previous

        # Case 2: READY → NOT_INSERTED (removal confirmation)
        if previous == CpinState.READY and raw_state == CpinState.NOT_INSERTED:
            self._removal_confirm_count += 1
            logger.debug("[CPIN STABILIZE] READY→NOT_INSERTED: removal_confirm=%d/%d",
                         self._removal_confirm_count, CPIN_MAX_REMOVAL_CONFIRM)

            if self._removal_confirm_count >= CPIN_MAX_REMOVAL_CONFIRM:
                # Confirmed removal
                logger.info("[CPIN STABILIZE] Removal confirmed → NOT_INSERTED")
                self._removal_confirm_count = 0
                self._unknown_count = 0
                self._checking_count = 0
                return CpinState.NOT_INSERTED
            else:
                # Not confirmed yet — keep previous state
                logger.debug("[CPIN STABILIZE] Removal not confirmed → keep %s", previous.value)
                return previous

        # Case 3: Any known state → READY (reset counters, accept immediately)
        if raw_state == CpinState.READY and previous != CpinState.READY:
            logger.info("[CPIN STABILIZE] → READY: reset counters")
            self._unknown_count = 0
            self._checking_count = 0
            self._removal_confirm_count = 0
            self._pending_removal = False
            return CpinState.READY

        # Case 4: UNKNOWN/NOT_READY → stable state (reset counters)
        if raw_state in (CpinState.READY, CpinState.NOT_INSERTED, CpinState.PIN_REQUIRED):
            if previous in (CpinState.UNKNOWN, CpinState.NOT_READY):
                logger.debug("[CPIN STABILIZE] %s→%s: reset counters", previous.value, raw_state.value)
                self._unknown_count = 0
                self._checking_count = 0
                self._removal_confirm_count = 0
                return raw_state

        # Case 5: Same state — no change
        if raw_state == previous:
            return raw_state

        # Case 6: Other transitions — accept with counter reset
        logger.info("[CPIN STABILIZE] Other transition %s→%s: accept", previous.value, raw_state.value)
        self._unknown_count = 0
        self._checking_count = 0
        self._removal_confirm_count = 0
        return raw_state

    def _update_poll_interval(self, state: CpinState) -> None:
        """Adaptive polling: READY=slow, NOT_READY=fast, UNKNOWN=normal."""
        if state == CpinState.READY:
            self._poll_interval = CPIN_POLL_INTERVAL * 3  # Slower for stable
        elif state == CpinState.NOT_READY:
            self._poll_interval = CPIN_POLL_INTERVAL * 0.5  # Faster for transitional
        else:
            self._poll_interval = CPIN_POLL_INTERVAL  # Normal for uncertain
        logger.debug("[CPIN] PORT=%s: poll_interval=%.1fs (state=%s)", self._port_id, self._poll_interval, state.value)
