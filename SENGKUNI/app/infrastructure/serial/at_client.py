"""ATClient — AT command pipeline with timeout handling.

Implements: flush → send → wait → parse → cleanup with timeout.
All operations always flush buffer first to prevent stale data contamination.
"""

import logging
import re
import threading
import time
from typing import Optional

from app.domain.constants import DEFAULT_AT_TIMEOUT, DEFAULT_READ_TIMEOUT

logger = logging.getLogger("sengkuni.at_client")

# Unolicited result codes that can appear between AT command and response
_URC_PREFIXES = ("+CREG:", "+CEREG:", "+CSQ:", "+WIND:", "+CPIN:", "+CNUM:",
                 "+COPS:", "+CLIP:", "+CCID:", "+CIMI:", "+CGSN:", "+QIND:")


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

    Pipeline: flush → send → wait → parse → cleanup
    Thread-safe via lock. Buffer is ALWAYS flushed before every command.
    """

    def __init__(self, serial_adapter: object, cleanup_manager: object = None) -> None:
        self._serial = serial_adapter
        self._cleanup = cleanup_manager
        self._lock: threading.Lock = threading.Lock()
        self._last_command: str = ""  # Track last sent command for echo filtering

    def send_at(self, command: str, timeout: float = DEFAULT_AT_TIMEOUT) -> Optional[str]:
        """Send AT command and return raw response string, or None if failed."""
        response = self.send_command(command, timeout=timeout)
        if response.is_ok or (response.raw and not response.is_error and not response.timeout):
            return response.raw
        return None

    def _flush_and_drain(self) -> None:
        """Flush input buffer AND drain any remaining bytes.

        This prevents stale data from previous commands contaminating
        the next response read. Two-pass approach:
        1. OS-level flush (reset_input_buffer)
        2. Read remaining bytes (in case data arrived between flush and now)
        """
        if not self._serial:
            return
        try:
            # Pass 1: OS-level flush
            if hasattr(self._serial, "reset_input_buffer"):
                self._serial.reset_input_buffer()
            if hasattr(self._serial, "reset_output_buffer"):
                self._serial.reset_output_buffer()
        except Exception:
            pass

        # Pass 2: Drain any bytes that arrived after flush
        try:
            time.sleep(0.02)  # 20ms settling — let any in-flight bytes arrive
            if hasattr(self._serial, "read"):
                max_drain = 1024  # safety limit
                total_drained = 0
                while total_drained < max_drain:
                    waiting = 0
                    if hasattr(self._serial, "in_waiting"):
                        waiting = self._serial.in_waiting
                    if waiting <= 0:
                        break
                    chunk = self._serial.read(waiting)
                    if not chunk:
                        break
                    total_drained += len(chunk)
                if total_drained > 0:
                    logger.debug("Drained %d stale bytes from buffer", total_drained)
        except Exception:
            pass

    def send_command(self, command: str, timeout: float = DEFAULT_AT_TIMEOUT) -> AtResponse:
        """Send AT command and wait for response.

        Pipeline:
        1. Flush stale bytes from prior operations (always)
        2. Send command + \\r\\n
        3. Wait for response (OK/ERROR or timeout)
        4. Parse response (with echo filtering)
        5. Cleanup (clear buffer)
        """
        with self._lock:
            self._last_command = command.strip().upper()

            # ALWAYS flush before sending — no stale data
            self._flush_and_drain()

            payload = f"{command}\r\n"

            if not self._serial.write(payload.encode()):
                return AtResponse(raw="", lines=[], is_ok=False, is_error=True)

            response = self._read_response(timeout)
            parsed = self._parse_response(response)

            if self._cleanup:
                self._cleanup.clear_buffer()

            return parsed

    def send_ussd(self, ussd_code: str, timeout: float = DEFAULT_READ_TIMEOUT) -> AtResponse:
        """Send USSD command and wait for response.

        Uses AT+CUSD=1 for USSD dial and waits for the actual +CUSD network payload.
        Flushes buffer before sending to prevent stale data contamination.
        """
        with self._lock:
            self._last_command = f'AT+CUSD=1,"{ussd_code}",15'

            # ALWAYS flush before USSD — critical for preventing stale CPIN data
            self._flush_and_drain()

            cmd = f'AT+CUSD=1,"{ussd_code}",15'
            payload = f"{cmd}\r\n"

            if not self._serial.write(payload.encode()):
                return AtResponse(raw="", lines=[], is_ok=False, is_error=True)

            response = self._read_ussd_response(timeout)
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
        """Read response from serial port until OK/ERROR or timeout.

        Filters out:
        - Echo of the command just sent
        - Unolicited notifications (+CREG, +CSQ, +WIND, etc.)
        """
        response_lines: list = []
        start_time = time.time()
        echo_skipped = False

        while time.time() - start_time < timeout:
            line = self._serial.readline()
            if line:
                decoded = line.decode("ascii", errors="ignore").strip()
                if not decoded:
                    continue

                # Skip echo of command we just sent
                if not echo_skipped and self._last_command:
                    upper = decoded.upper()
                    # Echo contains our command text
                    if self._last_command in upper or upper.startswith("AT"):
                        echo_skipped = True
                        continue

                # Skip unsolicited notifications (URC)
                if any(decoded.upper().startswith(p) for p in _URC_PREFIXES):
                    # +CPIN: notification outside of explicit query = skip
                    if not self._last_command.startswith("AT+CPIN"):
                        logger.debug("Filtered URC: %s", decoded[:60])
                        continue

                response_lines.append(decoded)
                if "OK" in decoded or "ERROR" in decoded:
                    break
            time.sleep(0.01)

        return "\n".join(response_lines)

    def _read_ussd_response(self, timeout: float) -> str:
        """Read USSD response from serial port.

        Termination conditions (in priority order):
        1. +CME ERROR found → stop immediately
        2. Closing quote pattern found (",15 or ",0) → response complete
        3. "OK" found after +CUSD line → response complete
        4. Timeout → return what we have

        Does NOT break on first empty line — multi-line USSD responses
        from Quectel M26 modem may have gaps between lines.
        """
        response_lines: list = []
        start_time = time.time()
        cusd_found = False
        raw_accumulated = ""

        while time.time() - start_time < timeout:
            line = self._serial.readline()
            if line:
                decoded = line.decode("ascii", errors="ignore").strip()
                if decoded:
                    response_lines.append(decoded)
                    raw_accumulated += decoded + "\n"

                    upper = decoded.upper()

                    # Error → stop immediately
                    if "+CME ERROR" in upper or "+CMS ERROR" in upper:
                        break

                    # +CUSD found → mark but keep reading for closing quote
                    if "+CUSD:" in upper:
                        cusd_found = True

                    # Check for closing quote pattern: ",15 or ",0
                    # This indicates the full USSD payload has been received
                    if cusd_found and re.search(r'",\s*\d+\s*$', decoded):
                        break

                    # If we have +CUSD and now see OK → response complete
                    if cusd_found and "OK" in upper:
                        break
            else:
                # Empty readline (timeout per read)
                # Only break if we already have complete response
                if cusd_found and response_lines:
                    # Check if we have a complete +CUSD response
                    full_text = "\n".join(response_lines)
                    if re.search(r'",\s*\d+\s*', full_text) or "OK" in full_text.upper():
                        break
            time.sleep(0.01)

        return "\n".join(response_lines)

    def _parse_response(self, raw: str) -> AtResponse:
        """Parse raw response into AtResponse."""
        lines = raw.split("\n") if raw else []
        is_ok = "OK" in raw or "+CUSD:" in raw.upper()
        is_error = "+CME ERROR" in raw.upper() or "+CMS ERROR" in raw.upper() or ("ERROR" in raw and "+CUSD:" not in raw.upper())
        timeout = not raw.strip() if raw else True

        return AtResponse(
            raw=raw,
            lines=lines,
            is_ok=is_ok,
            is_error=is_error,
            timeout=timeout,
        )
