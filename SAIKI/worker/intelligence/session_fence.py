"""SessionFence — Prevent USSD session collisions.

Adopted from GOOD: AT+CUSD=2 cancel, fence_quiet_minimum_seconds, fence_timeout.
Ensures no overlapping USSD sessions on the same modem port.

Session collision causes "USSD modal" errors and stuck sessions.
"""

import time
import threading
import logging
from typing import Any, Optional

logger = logging.getLogger("saiki.intelligence.session_fence")


class SessionFence:
    """Per-port USSD session fence.

    Prevents overlapping USSD sessions on the same modem.
    Uses AT+CUSD=2 to cancel stuck sessions.

    GOOD reference:
    - self.modem.send_at("AT+CUSD=2")
    - fence_quiet_minimum_seconds: float = 0.25
    - fence_timeout: float = 3.0
    """

    def __init__(
        self,
        quiet_minimum: float = 0.25,
        fence_timeout: float = 3.0,
        cooldown: float = 0.5,
    ) -> None:
        """
        Args:
            quiet_minimum: Minimum quiet time before next USSD (seconds)
            fence_timeout: Timeout for AT+CUSD=2 cancel (seconds)
            cooldown: Cooldown between USSD sessions (seconds)
        """
        self._quiet_minimum = quiet_minimum
        self._fence_timeout = fence_timeout
        self._cooldown = cooldown
        self._last_activity: Dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, port: str) -> bool:
        """Try to acquire session fence for a port.

        Returns True if acquired, False if another session is active.
        """
        now = time.time()
        with self._lock:
            last = self._last_activity.get(port, 0.0)
            elapsed = now - last
            if elapsed < self._quiet_minimum:
                logger.info("[SESSION_FENCE] BLOCKED port=%s elapsed=%.3f min=%.3f",
                            port, elapsed, self._quiet_minimum)
                return False
            self._last_activity[port] = now
            logger.info("[SESSION_FENCE] ACQUIRED port=%s", port)
            return True

    def release(self, port: str) -> None:
        """Release session fence for a port."""
        with self._lock:
            self._last_activity[port] = time.time()
            logger.info("[SESSION_FENCE] RELEASED port=%s", port)

    def cancel_session(self, modem: Any, port: str) -> bool:
        """Cancel any active USSD session via AT+CUSD=2.

        Returns True if cancel was sent successfully.
        """
        if modem is None:
            return False
        try:
            modem.send_at("AT+CUSD=2", timeout=self._fence_timeout)
            logger.info("[SESSION_FENCE] CANCEL_SENT port=%s", port)
            time.sleep(self._cooldown)
            return True
        except Exception as e:
            logger.warning("[SESSION_FENCE] CANCEL_FAILED port=%s error=%s", port, e)
            return False

    def ensure_clean(self, modem: Any, port: str) -> None:
        """Ensure modem is in a clean state before USSD.

        1. Cancel any active session
        2. Wait quiet minimum
        3. Clear buffer
        """
        self.cancel_session(modem, port)
        time.sleep(self._quiet_minimum)
        if modem:
            try:
                modem.reset_input_buffer()
                modem.reset_output_buffer()
            except Exception:
                pass

    def wait_cooldown(self) -> None:
        """Wait the cooldown period between sessions."""
        time.sleep(self._cooldown)


# Type alias for dict access
from typing import Dict
