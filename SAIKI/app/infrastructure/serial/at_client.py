"""ATClient — AT command pipeline with timeout handling.

Implements: send → wait → parse → cleanup with timeout.

Sprint 15L: [COMMAND AUDIT], [MODEM RESPONSE] instrumentation.
"""

import logging
import threading
import time
from typing import Optional

from app.domain.constants import DEFAULT_AT_TIMEOUT, DEFAULT_READ_TIMEOUT

logger = logging.getLogger("saiki.at_client")


class AtResponse:
    """Parsed AT command response."""

    def __init__(self, raw: str, lines: list, is_ok: bool, is_error: bool, timeout: bool = False) -> None:
        self.raw: str = raw
        self.lines: list = lines
        self.is_ok: bool = is_ok
        self.is_error: bool = is_error
        self.timeout: bool = timeout

    @property
    def success(self) -> bool:
        return self.is_ok and not self.is_error and not self.timeout

    def __repr__(self) -> str:
        return f"AtResponse(ok={self.is_ok}, error={self.is_error}, timeout={self.timeout})"


class ATClient:
    """AT command pipeline with timeout handling.

    Pipeline: send → wait → parse → cleanup
    Thread-safe via lock.
    """

    def __init__(self, serial_adapter: object, cleanup_manager: object = None) -> None:
        self._serial = serial_adapter
        self._cleanup = cleanup_manager
        self._lock: threading.Lock = threading.Lock()

    def send_command(self, command: str, timeout: float = DEFAULT_AT_TIMEOUT) -> AtResponse:
        """Send AT command and wait for response.

        Pipeline:
        1. Send command + \\r\\n
        2. Wait for response (OK/ERROR or timeout)
        3. Parse response
        4. Cleanup (clear buffer)

        Sprint 15L: [COMMAND AUDIT], [MODEM RESPONSE] instrumentation.
        """
        with self._lock:
            payload = f"{command}\r\n"
            port_name = getattr(self._serial, 'port_name', 'UNKNOWN') if self._serial else 'UNKNOWN'
            serial_id = id(self._serial) if self._serial else 0
            is_open = self._serial.is_open if self._serial and hasattr(self._serial, 'is_open') else False
            logger.info("[COMMAND AUDIT] PORT=%s SKILL=at_command COMMAND=%s PAYLOAD=%s", port_name, command, payload.strip())
            logger.debug("[PORT OWNERSHIP] ROLE=AT_CLIENT PORT=%s SERIAL_ID=%d ACTION=send_command IS_OPEN=%s",
                         port_name, serial_id, is_open)

            if not self._serial.write(payload.encode()):
                logger.info("[COMMAND AUDIT] PORT=%s FAILED REASON=serial_write_failed", port_name)
                return AtResponse(raw="", lines=[], is_ok=False, is_error=True)

            response = self._read_response(timeout)

            if not response.strip():
                logger.info("[MODEM RESPONSE] PORT=%s TIMEOUT command=%s", port_name, command)
            else:
                logger.info("[MODEM RESPONSE] PORT=%s RAW=%s HEX=%s", port_name, response[:200], response[:200].encode().hex())

            parsed = self._parse_response(response)

            if self._cleanup:
                self._cleanup.clear_buffer()

            return parsed

    def send_ussd(self, ussd_code: str, timeout: float = DEFAULT_READ_TIMEOUT) -> AtResponse:
        """Send USSD command and wait for response.

        Uses AT+CUSD=1 for USSD dial.

        Sprint 15L: [COMMAND AUDIT], [MODEM RESPONSE] instrumentation.
        """
        with self._lock:
            cmd = f'AT+CUSD=1,"{ussd_code}",15'
            payload = f"{cmd}\r\n"
            port_name = getattr(self._serial, 'port_name', 'UNKNOWN') if self._serial else 'UNKNOWN'
            serial_id = id(self._serial) if self._serial else 0
            is_open = self._serial.is_open if self._serial and hasattr(self._serial, 'is_open') else False
            logger.info("[COMMAND AUDIT] PORT=%s SKILL=ussd COMMAND=%s PAYLOAD=%s", port_name, ussd_code, cmd)
            logger.debug("[PORT OWNERSHIP] ROLE=AT_CLIENT PORT=%s SERIAL_ID=%d ACTION=send_ussd IS_OPEN=%s",
                         port_name, serial_id, is_open)

            if not self._serial.write(payload.encode()):
                logger.info("[COMMAND AUDIT] PORT=%s FAILED REASON=serial_write_failed", port_name)
                return AtResponse(raw="", lines=[], is_ok=False, is_error=True)

            response = self._read_response(timeout)

            if not response.strip():
                logger.info("[MODEM RESPONSE] PORT=%s TIMEOUT command=USSD code=%s", port_name, ussd_code)
            else:
                logger.info("[MODEM RESPONSE] PORT=%s RAW=%s HEX=%s", port_name, response[:200], response[:200].encode().hex())

            parsed = self._parse_response(response)

            if self._cleanup:
                self._cleanup.close_session()
                self._cleanup.clear_buffer()

            return parsed

    def cancel_ussd(self) -> AtResponse:
        """Cancel active USSD session."""
        return self.send_command("AT+CUSD=2", timeout=3.0)

    def check_modem(self) -> bool:
        """Check if modem responds to AT. Returns True if online."""
        response = self.send_command("AT", timeout=2.0)
        return response.success

    def check_sim(self) -> str:
        """Check SIM state via AT+CPIN?. Returns raw response."""
        response = self.send_command("AT+CPIN?", timeout=3.0)
        return response.raw

    def _read_response(self, timeout: float) -> str:
        """Read response from serial port until OK/ERROR or timeout."""
        response_lines: list = []
        start_time = time.time()

        while time.time() - start_time < timeout:
            line = self._serial.readline()
            if line:
                decoded = line.decode("ascii", errors="ignore").strip()
                if decoded:
                    response_lines.append(decoded)
                    if "OK" in decoded or "ERROR" in decoded:
                        break
            time.sleep(0.01)

        return "\n".join(response_lines)

    def _parse_response(self, raw: str) -> AtResponse:
        """Parse raw response into AtResponse."""
        lines = raw.split("\n") if raw else []
        is_ok = "OK" in raw
        is_error = "ERROR" in raw
        timeout = not raw.strip() if raw else True

        return AtResponse(
            raw=raw,
            lines=lines,
            is_ok=is_ok,
            is_error=is_error,
            timeout=timeout,
        )
