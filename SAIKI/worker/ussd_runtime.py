"""UssdRuntime — USSD dial, classify, cooldown.

Sends USSD commands via AT+CUSD, classifies responses, enforces cooldown.
"""

import time
from typing import Any, Optional

from app.domain.enums import UssdClass
from app.domain.constants import DIAL_COOLDOWN_SECONDS


class UssdRuntime:
    """USSD command executor for a single port."""

    def __init__(self, port_id: str, at_client: Any, event_bus: Any) -> None:
        self._port_id = port_id
        self._at_client = at_client
        self._event_bus = event_bus

    def dial(
        self,
        code: str,
        timeout: float = 30.0,
        cooldown: float = DIAL_COOLDOWN_SECONDS,
    ) -> Optional[str]:
        """Dial a USSD code, wait for response, cooldown.

        Returns raw response string or None on failure.
        """
        if not self._at_client:
            return None

        response = self._at_client.send_ussd(code, timeout=timeout)
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
