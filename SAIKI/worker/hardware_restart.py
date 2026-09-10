"""HardwareRestart — Simplified modem restart flow.

DD-013: Single Hardware Restart.
Flow: restart modem → wait online → detect SIM → evaluate.
"""

import time
from typing import Any, Optional, Tuple

from app.domain.enums import CpinState
from app.domain.classifier import parse_cpin_response
from app.domain.constants import STABILIZATION_SECONDS, CPIN_POLL_TIMEOUT


class HardwareRestart:
    """Handles hardware modem restart with SIM detection.

    After restart:
    - SIM NOT INSERTED → standby
    - SIM READY + Auto Run OFF → standby
    - SIM READY + Auto Run ON → enqueue automation
    """

    def __init__(self, modem: Any, event_bus: Any = None) -> None:
        self._modem = modem
        self._event_bus = event_bus

    def set_modem(self, modem: Any) -> None:
        """Inject modem adapter."""
        self._modem = modem

    def restart_modem(self) -> bool:
        """Send hardware restart command (ATZ).

        Returns True if modem responded.
        """
        if self._modem is None:
            return False

        try:
            response = self._modem.send_at("ATZ", timeout=5.0)
            time.sleep(STABILIZATION_SECONDS)
            return response is not None
        except Exception:
            time.sleep(STABILIZATION_SECONDS)
            return False

    def wait_online(self, timeout: float = 30.0) -> bool:
        """Wait for modem to come online after restart.

        Polls AT command until modem responds.
        Returns True if modem came online within timeout.
        """
        if self._modem is None:
            return False

        start = time.time()
        while time.time() - start < timeout:
            try:
                response = self._modem.send_at("AT", timeout=2.0)
                if response is not None:
                    return True
            except Exception:
                pass
            time.sleep(1.0)

        return False

    def detect_sim(self) -> CpinState:
        """Detect SIM state after restart.

        Returns CpinState from AT+CPIN? response.
        """
        if self._modem is None:
            return CpinState.UNKNOWN

        try:
            response = self._modem.send_at("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
            return parse_cpin_response(response)
        except Exception:
            return CpinState.UNKNOWN

    def execute_full_restart(self) -> Tuple[bool, CpinState]:
        """Execute complete restart flow.

        Steps:
        1. Restart modem
        2. Wait for online
        3. Detect SIM

        Returns:
            (online, sim_state)
        """
        self.restart_modem()

        online = self.wait_online()

        if not online:
            return False, CpinState.UNKNOWN

        sim_state = self.detect_sim()

        return True, sim_state

    def evaluate_post_restart(
        self,
        online: bool,
        sim_state: CpinState,
        auto_run_enabled: bool,
    ) -> str:
        """Evaluate state after restart and decide action.

        Returns:
            "automation" if should continue
            "standby" if should wait
        """
        if not online:
            return "standby"

        if sim_state == CpinState.NOT_INSERTED:
            return "standby"

        if sim_state == CpinState.PIN_REQUIRED:
            return "standby"

        if sim_state == CpinState.READY and not auto_run_enabled:
            return "standby"

        if sim_state == CpinState.READY and auto_run_enabled:
            return "automation"

        return "standby"
