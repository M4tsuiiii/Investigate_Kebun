"""Port worker state — per-port mutable state with RLock.

All consume_* methods use RLock for atomic read-and-clear (M-02, M-03).
All state mutations hold the lock for the duration of the change.
"""

import threading
from typing import Optional, Dict, Any

from app.domain.enums import CpinState, PortStatus
from app.domain.constants import (
    CPIN_UNKNOWN_THRESHOLD,
    CPIN_CHECKING_THRESHOLD,
    PROMPT_RECOVERY_MAX,
)


class PortWorkerState:
    """Thread-safe mutable state for a single port worker.

    Lock hierarchy: Level 1 — never hold while calling EventBus (§10.2).
    All consume_* methods atomically read-and-clear under RLock.

    Hidden Rules:
    - HR-004: awaiting_card_cycle flag
    - HR-005/008: pending_auto_run can be cleared by prompt recovery
    - HR-002/003: force_retry cleared before READY guard
    - HR-006: force_retry persists on disabled ports
    - HR-010: request_reset clears all pending actions
    """

    def __init__(self, port_name: str) -> None:
        self._port_name: str = port_name
        self._lock: threading.RLock = threading.RLock()

        # === Modem State ===
        self._current_baud: Optional[int] = None
        self._cpin_state: CpinState = CpinState.UNKNOWN
        self._last_cpin: CpinState = CpinState.UNKNOWN

        # === Flow Control Flags ===
        self._awaiting_card_cycle: bool = False
        self._pending_auto_run: bool = False
        self._force_retry: bool = False
        self._single_action: Optional[str] = None
        self._reset_requested: bool = False

        # === CPIN Tracking (HR-018, HR-019) ===
        self._unknown_failure_count: int = 0
        self._cpin_failure_count: int = 0

        # === Prompt Recovery (BR-026) ===
        self._prompt_recovery_count: int = 0

        # === UI State ===
        self._status: PortStatus = PortStatus.OFF
        self._status_detail: str = ""

        # === Card Data ===
        self._nomor: str = "-"
        self._nik: str = "-"
        self._kk: str = "-"
        self._masa_aktif: str = "-"

    @property
    def port_name(self) -> str:
        return self._port_name

    # ------------------------------------------------------------------
    # Auto-Run
    # ------------------------------------------------------------------

    def queue_auto_run(self) -> None:
        """Queue auto-run if not already queued.

        Source: Line 1147
        """
        with self._lock:
            self._pending_auto_run = True

    def consume_auto_run(self) -> bool:
        """Atomic read-and-clear of pending_auto_run flag.

        Returns True if was pending.
        """
        with self._lock:
            if self._pending_auto_run:
                self._pending_auto_run = False
                return True
            return False

    # ------------------------------------------------------------------
    # Single Action
    # ------------------------------------------------------------------

    def set_single_action(self, action: Optional[str]) -> None:
        """Set single action to execute.

        Source: Line 1318 (highest priority after reset).
        """
        with self._lock:
            self._single_action = action

    def consume_single_action(self) -> Optional[str]:
        """Atomic read-and-clear of single action."""
        with self._lock:
            action = self._single_action
            self._single_action = None
            return action

    # ------------------------------------------------------------------
    # Force Retry
    # ------------------------------------------------------------------

    def set_force_retry(self) -> None:
        """Set force retry flag.

        Source: Line 2815 (restart_all sets on all workers).
        HR-006: Persists even on disabled/offline ports.
        """
        with self._lock:
            self._force_retry = True

    def consume_force_retry(self) -> bool:
        """Atomic read-and-clear of force_retry flag.

        Source: Line 1324 (HR-002: cleared before READY guard).
        """
        with self._lock:
            if self._force_retry:
                self._force_retry = False
                return True
            return False

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def request_reset(self) -> None:
        """Request modem reset. Clears all pending actions.

        Source: Lines 1068-1071 (HR-010).
        """
        with self._lock:
            self._reset_requested = True
            self._force_retry = False
            self._single_action = None
            self._pending_auto_run = False

    def consume_reset(self) -> bool:
        """Atomic read-and-clear of reset request flag."""
        with self._lock:
            if self._reset_requested:
                self._reset_requested = False
                return True
            return False

    # ------------------------------------------------------------------
    # CPIN Tracking
    # ------------------------------------------------------------------

    def increment_unknown(self) -> bool:
        """Increment unknown failure count atomically.

        Returns True if threshold reached (CPIN_UNKNOWN_THRESHOLD).
        """
        with self._lock:
            self._unknown_failure_count += 1
            self._cpin_failure_count += 1
            return self._unknown_failure_count >= CPIN_UNKNOWN_THRESHOLD

    def increment_checking(self) -> bool:
        """Increment checking failure count atomically.

        Returns True if threshold reached (CPIN_CHECKING_THRESHOLD).
        """
        with self._lock:
            self._cpin_failure_count += 1
            return self._cpin_failure_count >= CPIN_CHECKING_THRESHOLD

    def reset_cpin_counters(self) -> None:
        """Reset all CPIN-related counters.

        Source: Lines 1448-1449 (reset on READY/NOT_INSERTED/PIN_REQUIRED).
        """
        with self._lock:
            self._unknown_failure_count = 0
            self._cpin_failure_count = 0

    # ------------------------------------------------------------------
    # Card Cycle (HR-004)
    # ------------------------------------------------------------------

    def require_card_cycle(self) -> None:
        """Set awaiting_card_cycle flag.

        Source: Lines 1847, 2010 (set after SUCCESS/AKTIF/TENGGANG).
        """
        with self._lock:
            self._awaiting_card_cycle = True

    def clear_card_cycle(self) -> None:
        """Clear awaiting_card_cycle flag.

        Source: Lines 233, 236 (cleared on PIN_REQUIRED/NOT_INSERTED).
        """
        with self._lock:
            self._awaiting_card_cycle = False

    # ------------------------------------------------------------------
    # Prompt Recovery (BR-026)
    # ------------------------------------------------------------------

    def increment_prompt_recovery(self) -> bool:
        """Increment prompt recovery count. Returns True if max reached."""
        with self._lock:
            self._prompt_recovery_count += 1
            return self._prompt_recovery_count >= PROMPT_RECOVERY_MAX

    def reset_prompt_recovery(self) -> None:
        """Reset prompt recovery counter."""
        with self._lock:
            self._prompt_recovery_count = 0

    # ------------------------------------------------------------------
    # CPIN State
    # ------------------------------------------------------------------

    def set_cpin_state(self, new_state: CpinState) -> bool:
        """Update CPIN state. Returns True if state changed.

        Source: Lines 208-244 (PSM _on_cpin_transition).
        """
        with self._lock:
            old_state = self._cpin_state
            self._last_cpin = new_state
            self._cpin_state = new_state
            return old_state != new_state

    @property
    def cpin_state(self) -> CpinState:
        with self._lock:
            return self._cpin_state

    @property
    def last_cpin(self) -> CpinState:
        with self._lock:
            return self._last_cpin

    # ------------------------------------------------------------------
    # UI State
    # ------------------------------------------------------------------

    def set_status(self, status: PortStatus, detail: str = "") -> None:
        """Update worker status."""
        with self._lock:
            self._status = status
            self._status_detail = detail

    @property
    def status(self) -> PortStatus:
        with self._lock:
            return self._status

    @property
    def status_detail(self) -> str:
        with self._lock:
            return self._status_detail

    # ------------------------------------------------------------------
    # Card Data
    # ------------------------------------------------------------------

    def clear_card_data(self) -> None:
        """Clear all card-related fields.

        Source: Lines 1353-1356 (removal confirmation flow).
        """
        with self._lock:
            self._nomor = "-"
            self._nik = "-"
            self._kk = "-"
            self._masa_aktif = "-"

    def set_card_data(
        self,
        nomor: Optional[str] = None,
        nik: Optional[str] = None,
        kk: Optional[str] = None,
        masa_aktif: Optional[str] = None,
    ) -> None:
        """Update card data fields."""
        with self._lock:
            if nomor is not None:
                self._nomor = nomor
            if nik is not None:
                self._nik = nik
            if kk is not None:
                self._kk = kk
            if masa_aktif is not None:
                self._masa_aktif = masa_aktif

    # ------------------------------------------------------------------
    # Thread-safe Snapshot (M-03)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Atomic snapshot of all state — no TOCTOU.

        Must be used for any cross-field consistency checks.
        """
        with self._lock:
            return {
                "port_name": self._port_name,
                "current_baud": self._current_baud,
                "cpin_state": self._cpin_state,
                "last_cpin": self._last_cpin,
                "awaiting_card_cycle": self._awaiting_card_cycle,
                "pending_auto_run": self._pending_auto_run,
                "force_retry": self._force_retry,
                "single_action": self._single_action,
                "reset_requested": self._reset_requested,
                "unknown_failure_count": self._unknown_failure_count,
                "cpin_failure_count": self._cpin_failure_count,
                "prompt_recovery_count": self._prompt_recovery_count,
                "status": self._status,
                "status_detail": self._status_detail,
                "nomor": self._nomor,
                "nik": self._nik,
                "kk": self._kk,
                "masa_aktif": self._masa_aktif,
            }

    # ------------------------------------------------------------------
    # Modem Baud
    # ------------------------------------------------------------------

    def set_current_baud(self, baud: Optional[int]) -> None:
        """Set current baud rate."""
        with self._lock:
            self._current_baud = baud

    @property
    def current_baud(self) -> Optional[int]:
        with self._lock:
            return self._current_baud
