"""ModemDetector — Detects modem presence and type.

Checks COM ports for modem availability using AT commands.
"""

import threading
from typing import Optional, Dict

from app.domain.enums import CpinState
from app.domain.classifier import parse_cpin_response


class ModemInfo:
    """Information about a detected modem."""

    def __init__(self, port_name: str, baud_rate: int = 0, model: str = "", sim_state: CpinState = CpinState.UNKNOWN) -> None:
        self.port_name: str = port_name
        self.baud_rate: int = baud_rate
        self.model: str = model
        self.sim_state: CpinState = sim_state

    def __repr__(self) -> str:
        return f"ModemInfo({self.port_name}, baud={self.baud_rate}, sim={self.sim_state.value})"


class ModemDetector:
    """Detects modem presence and state.

    Responsibilities:
    - Check if modem responds to AT
    - Detect modem model (ATI)
    - Detect SIM state (AT+CPIN?)
    - Track online/offline state
    """

    def __init__(self, event_bus: object = None) -> None:
        self._event_bus = event_bus
        self._lock: threading.Lock = threading.Lock()
        self._modem_info: Dict[str, ModemInfo] = {}

    def detect_modem(self, at_client: object) -> Optional[ModemInfo]:
        """Detect modem at given AT client.

        Returns ModemInfo if modem responds, None otherwise.
        """
        if not at_client.check_modem():
            return None

        model = self._get_model(at_client)

        sim_response = at_client.check_sim()
        sim_state = parse_cpin_response(sim_response)

        info = ModemInfo(
            port_name=at_client._serial.port_name if hasattr(at_client._serial, 'port_name') else "unknown",
            model=model,
            sim_state=sim_state,
        )

        with self._lock:
            self._modem_info[info.port_name] = info

        return info

    def check_sim_state(self, at_client: object) -> CpinState:
        """Check SIM state via AT+CPIN?."""
        response = at_client.check_sim()
        return parse_cpin_response(response)

    def is_modem_online(self, at_client: object) -> bool:
        """Check if modem is online."""
        return at_client.check_modem()

    def get_modem_info(self, port_name: str) -> Optional[ModemInfo]:
        """Get cached modem info."""
        with self._lock:
            return self._modem_info.get(port_name)

    def _get_model(self, at_client: object) -> str:
        """Get modem model via ATI command."""
        response = at_client.send_command("ATI", timeout=2.0)
        if response.success and response.lines:
            for line in response.lines:
                if line.strip() and line.strip() != "OK":
                    return line.strip()
        return "Unknown"
