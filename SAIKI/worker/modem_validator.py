"""ModemValidator — validates COM ports by sending AT command (Sprint 11A, 13).

Flow (with baud_rates):
  COM detected
  -> for each baud rate:
     -> open serial at baud rate
     -> send "AT"
     -> wait response
     -> if contains "OK" -> VALID_MODEM (with detected baud)
  -> else -> INVALID_DEVICE or UNRESPONSIVE

Flow (without baud_rates):
  COM detected
  -> open serial via factory
  -> send "AT"
  -> wait response
  -> if contains "OK" -> VALID_MODEM
  -> else -> INVALID_DEVICE or UNRESPONSIVE

Only VALID_MODEM ports may create workers.
"""

import logging
import time
from typing import Callable, Any, Optional, List
from dataclasses import dataclass

from app.domain.enums import ValidationResult

logger = logging.getLogger("saiki.validator")


@dataclass
class PortValidationResult:
    """Result of modem validation for a single COM port."""
    port_id: str
    status: ValidationResult
    response: str = ""
    attempts: int = 0
    error: str = ""
    baud_rate: int = 0  # Detected baud rate (0 if not detected)


class ModemValidator:
    """Validates COM ports by sending AT command and checking for OK response.

    Supports two modes:
    - Multi-baud detection: pass baud_rates to try each rate
    - Single-probe: no baud_rates, uses serial_factory with fixed rate

    Usage:
        validator = ModemValidator(timeout=2.0, retries=2, baud_rates=[9600, 19200, 115200])
        result = validator.validate("COM3", serial_factory)
        if result.status == ValidationResult.VALID_MODEM:
            # create worker with result.baud_rate
    """

    def __init__(
        self,
        timeout: float = 2.0,
        retries: int = 2,
        baud_rates: Optional[List[int]] = None,
    ) -> None:
        self._timeout = timeout
        self._retries = retries
        self._baud_rates = baud_rates

    def validate(
        self,
        port_id: str,
        serial_factory: Callable[..., Any],
    ) -> PortValidationResult:
        """Validate a COM port by sending AT command.

        Args:
            port_id: COM port identifier (e.g. "COM3")
            serial_factory: Callable that creates a SerialAdapter.
                Signature: serial_factory(port_id) or serial_factory(port_id, baud_rate)

        Returns:
            PortValidationResult with status, response, attempts, baud_rate.
        """
        if self._baud_rates:
            return self._validate_with_baud_detection(port_id)
        return self._validate_with_factory(port_id, serial_factory)

    def _validate_with_baud_detection(self, port_id: str) -> PortValidationResult:
        """Validate by probing multiple baud rates."""
        result = PortValidationResult(
            port_id=port_id,
            status=ValidationResult.UNRESPONSIVE,
        )

        for baud in self._baud_rates:
            for attempt in range(1, self._retries + 1):
                result.attempts += 1
                adapter = None
                try:
                    from app.infrastructure.serial import SerialAdapter
                    adapter = SerialAdapter(port_id, baud_rate=baud, timeout=self._timeout)

                    if not adapter.open():
                        result.status = ValidationResult.UNRESPONSIVE
                        result.error = f"Cannot open at {baud}"
                        logger.info("[VALIDATE] %s baud=%d attempt %d: cannot open",
                                    port_id, baud, attempt)
                        continue

                    adapter.reset_input_buffer()
                    written = adapter.write(b"AT\r\n")
                    if not written:
                        result.status = ValidationResult.UNRESPONSIVE
                        result.error = f"Write failed at {baud}"
                        logger.info("[VALIDATE] %s baud=%d attempt %d: write failed",
                                    port_id, baud, attempt)
                        continue

                    response_bytes = b""
                    deadline = time.time() + self._timeout
                    while time.time() < deadline:
                        if adapter.in_waiting > 0:
                            chunk = adapter.read(adapter.in_waiting)
                            if chunk:
                                response_bytes += chunk
                                decoded = response_bytes.decode("utf-8", errors="replace")
                                if "OK" in decoded or "ERROR" in decoded:
                                    break
                        time.sleep(0.05)

                    if not response_bytes:
                        result.status = ValidationResult.UNRESPONSIVE
                        result.error = f"No response at {baud}"
                        logger.info("[VALIDATE] %s baud=%d attempt %d: no response",
                                    port_id, baud, attempt)
                        continue

                    response = response_bytes.decode("utf-8", errors="replace").strip()
                    result.response = response

                    if "OK" in response.upper():
                        result.status = ValidationResult.VALID_MODEM
                        result.baud_rate = baud
                        logger.info("[VALIDATE] %s: VALID_MODEM baud=%d (attempt %d)",
                                    port_id, baud, result.attempts)
                        return result
                    else:
                        result.status = ValidationResult.INVALID_DEVICE
                        result.error = f"No OK at {baud}: {response[:100]}"
                        logger.info("[VALIDATE] %s baud=%d attempt %d: invalid '%s'",
                                    port_id, baud, attempt, response[:50])

                except Exception as e:
                    result.status = ValidationResult.UNRESPONSIVE
                    result.error = str(e)
                    logger.info("[VALIDATE] %s baud=%d attempt %d: exception %s",
                                port_id, baud, attempt, e)
                finally:
                    if adapter is not None:
                        try:
                            adapter.close()
                        except Exception:
                            pass

        return result

    def _validate_with_factory(
        self, port_id: str, serial_factory: Callable[..., Any]
    ) -> PortValidationResult:
        """Validate using provided serial factory (single baud rate)."""
        result = PortValidationResult(
            port_id=port_id,
            status=ValidationResult.UNRESPONSIVE,
        )

        serial_adapter = None
        for attempt in range(1, self._retries + 1):
            result.attempts = attempt
            try:
                serial_adapter = serial_factory(port_id)
                if serial_adapter is None:
                    result.status = ValidationResult.INVALID_DEVICE
                    result.error = "Factory returned None"
                    logger.info("[VALIDATE] %s attempt %d: factory returned None", port_id, attempt)
                    continue

                if not serial_adapter.open():
                    result.status = ValidationResult.UNRESPONSIVE
                    result.error = "Failed to open serial port"
                    logger.info("[VALIDATE] %s attempt %d: cannot open port", port_id, attempt)
                    continue

                serial_adapter.reset_input_buffer()
                written = serial_adapter.write(b"AT\r\n")
                if not written:
                    result.status = ValidationResult.UNRESPONSIVE
                    result.error = "Failed to write AT command"
                    logger.info("[VALIDATE] %s attempt %d: write failed", port_id, attempt)
                    continue

                response_bytes = b""
                deadline = time.time() + self._timeout
                while time.time() < deadline:
                    if serial_adapter.in_waiting > 0:
                        chunk = serial_adapter.read(serial_adapter.in_waiting)
                        if chunk:
                            response_bytes += chunk
                            decoded_so_far = response_bytes.decode("utf-8", errors="replace")
                            if "OK" in decoded_so_far or "ERROR" in decoded_so_far:
                                break
                    time.sleep(0.05)

                if not response_bytes:
                    result.status = ValidationResult.UNRESPONSIVE
                    result.error = "No response from device"
                    logger.info("[VALIDATE] %s attempt %d: no response", port_id, attempt)
                    continue

                response = response_bytes.decode("utf-8", errors="replace").strip()
                result.response = response

                if "OK" in response.upper():
                    result.status = ValidationResult.VALID_MODEM
                    logger.info("[VALIDATE] %s: VALID_MODEM (attempt %d)", port_id, attempt)
                    break
                else:
                    result.status = ValidationResult.INVALID_DEVICE
                    result.error = f"No OK in response: {response[:100]}"
                    logger.info("[VALIDATE] %s attempt %d: invalid response '%s'",
                                port_id, attempt, response[:50])

            except Exception as e:
                result.status = ValidationResult.UNRESPONSIVE
                result.error = str(e)
                logger.info("[VALIDATE] %s attempt %d: exception %s", port_id, attempt, e)
            finally:
                if serial_adapter is not None:
                    try:
                        serial_adapter.close()
                    except Exception:
                        pass

        return result
