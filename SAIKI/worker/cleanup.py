"""Cleanup — Session cleanup and cooldown discipline.

DD-015: Step-Based Automation — send → receive → cleanup → cooldown → next.
DD-019: Cooldown Discipline — every transition has configurable cooldown.
"""

import time
from typing import Any, Optional

from app.domain.constants import (
    USSD_SESSION_FENCE_TIMEOUT_SECONDS,
    DIAL_COOLDOWN_SECONDS,
    USSD_GRACE_READ_INITIAL_WAIT,
)


class CleanupManager:
    """Handles session cleanup and cooldown between steps.

    Every command execution must follow:
    1. Close USSD session (AT+CUSD=2)
    2. Clear modem input buffer
    3. Cooldown before next command
    """

    def __init__(self, modem: Any = None) -> None:
        self._modem = modem

    def set_modem(self, modem: Any) -> None:
        """Inject modem adapter."""
        self._modem = modem

    def close_session(self) -> None:
        """Close any active USSD session.

        Sends AT+CUSD=2 to cancel active session.
        """
        if self._modem is None:
            return
        try:
            self._modem.send_at(
                "AT+CUSD=2", timeout=USSD_SESSION_FENCE_TIMEOUT_SECONDS
            )
        except Exception:
            pass  # Best effort — session may already be closed

    def clear_buffer(self) -> None:
        """Clear modem input/output buffers."""
        if self._modem is None:
            return
        try:
            self._modem.reset_input_buffer()
            self._modem.reset_output_buffer()
        except Exception:
            pass

    def cooldown(self, seconds: Optional[float] = None) -> None:
        """Wait for cooldown between steps.

        Default: DIAL_COOLDOWN_SECONDS (4.0s).
        """
        wait_time = seconds if seconds is not None else DIAL_COOLDOWN_SECONDS
        time.sleep(wait_time)

    def full_cleanup(self) -> None:
        """Execute full cleanup sequence:
        1. Close session
        2. Clear buffer
        3. Cooldown
        """
        self.close_session()
        time.sleep(USSD_GRACE_READ_INITIAL_WAIT)
        self.clear_buffer()
        self.cooldown()


class StepExecutor:
    """Executes a single automation step with cleanup discipline.

    DD-015: send → receive → cleanup → cooldown → next.
    No overlapping commands.
    """

    def __init__(self, modem: Any, cleanup: CleanupManager) -> None:
        self._modem = modem
        self._cleanup = cleanup

    def execute(self, command: str, timeout: float = 10.0) -> Optional[str]:
        """Execute a single USSD command with full cleanup.

        Steps:
        1. Send command
        2. Receive response
        3. Close session
        4. Clear buffer
        5. Cooldown

        Returns response or None on failure.
        """
        if self._modem is None:
            return None

        try:
            response = self._modem.send_ussd(command, timeout=timeout)

            self._cleanup.close_session()
            self._cleanup.clear_buffer()
            self._cleanup.cooldown()

            return response
        except Exception:
            self._cleanup.close_session()
            self._cleanup.clear_buffer()
            return None

    def execute_at(self, command: str, timeout: float = 2.0) -> Optional[str]:
        """Execute an AT command with cleanup.

        Used for non-USSD commands (AT+CPIN?, AT, etc.).
        """
        if self._modem is None:
            return None

        try:
            response = self._modem.send_at(command, timeout=timeout)
            self._cleanup.clear_buffer()
            return response
        except Exception:
            self._cleanup.clear_buffer()
            return None
