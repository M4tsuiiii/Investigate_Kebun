"""UssdRuntime — USSD dial, classify, cooldown.

Sends USSD commands via AT+CUSD, classifies responses, enforces cooldown.
Session safety: always close previous session before new dial.
"""

import logging
import time
from typing import Any, Optional

from app.domain.enums import UssdClass
from app.domain.constants import DIAL_COOLDOWN_SECONDS

logger = logging.getLogger("sengkuni.ussd")


class UssdRuntime:
    """USSD command executor for a single port.

    Session safety:
    1. Check session fence before dialing
    2. If fence busy → cancel session (AT+CUSD=2) → wait → retry
    3. Always send AT+CUSD=2 before new dial (M26 firmware bug workaround)
    """

    def __init__(self, port_id: str, at_client: Any, session_fence: Any = None, event_bus: Any = None) -> None:
        self._port_id = port_id
        self._at_client = at_client
        self._session_fence = session_fence
        self._event_bus = event_bus

    def dial(
        self,
        code: str,
        timeout: float = 30.0,
        cooldown: float = DIAL_COOLDOWN_SECONDS,
    ) -> Optional[str]:
        """Dial a USSD code, wait for response, cooldown.

        Session safety flow:
        1. Try to acquire session fence
        2. If fence busy → cancel stale session → wait → retry acquire
        3. If still busy → skip dial, return None
        4. Close any previous USSD session (AT+CUSD=2) — M26 firmware fix
        5. Dial the new USSD code
        6. Release fence + cooldown

        Returns raw response string or None on failure.
        """
        if not self._at_client:
            return None

        # Step 1: Acquire session fence
        if self._session_fence:
            acquired = self._session_fence.acquire(self._port_id)
            if not acquired:
                # Fence busy — another session may be active
                logger.warning("[USSD] %s: Session fence busy, cancelling stale session", self._port_id)

                # Try to cancel the stale session
                try:
                    self._at_client.cancel_ussd()
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning("[USSD] %s: Cancel stale session failed: %s", self._port_id, e)

                # Retry acquire after cancel
                acquired = self._session_fence.acquire(self._port_id)
                if not acquired:
                    logger.error("[USSD] %s: Could not acquire session fence after cancel — SKIPPING", self._port_id)
                    return None

        # Step 2: Close any previous USSD session (M26 firmware workaround)
        # M26 modem can cache previous responses if session not explicitly closed
        try:
            self._at_client.cancel_ussd()
            time.sleep(0.15)  # Brief settling after cancel
        except Exception:
            pass  # Best effort — modem may already be clean

        # Step 3: Dial the USSD code
        response = self._at_client.send_ussd(code, timeout=timeout)

        # Step 4: Release session fence
        if self._session_fence:
            self._session_fence.release(self._port_id)

        if self._event_bus:
            self._event_bus.publish("ussd.response", {
                "port": self._port_id,
                "code": code,
                "raw": response.raw,
                "success": response.success,
            })

        time.sleep(cooldown)
        return response.raw if response.success else None

    def classify(self, raw_response: str) -> UssdClass:
        """Classify a raw USSD response."""
        if not raw_response:
            return UssdClass.EMPTY_PAYLOAD
        upper = raw_response.upper()
        if "+CUSD" in upper and ",\"" in raw_response:
            return UssdClass.PAYLOAD
        if "+CUSD" in upper:
            return UssdClass.STATUS_ONLY
        if "OK" in upper:
            return UssdClass.AT_OK
        return UssdClass.PARTIAL
