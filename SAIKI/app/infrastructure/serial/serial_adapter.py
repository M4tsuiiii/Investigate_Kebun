"""SerialAdapter — PySerial wrapper for modem communication.

Provides thread-safe serial port operations with reconnect support.

Sprint 15L: [SERIAL WRITE] byte-level tracing.
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("saiki.serial")

try:
    import serial
except ImportError:
    serial = None  # type: ignore


class SerialAdapter:
    """Thread-safe PySerial wrapper.

    Responsibilities:
    - Open/close serial port
    - Read/write bytes
    - Reset buffers
    - Reconnect on failure
    - Thread-safe operations via lock
    """

    def __init__(self, port_name: str, baud_rate: int = 115200, timeout: float = 1.0) -> None:
        self._port_name: str = port_name
        self._baud_rate: int = baud_rate
        self._timeout: float = timeout
        self._serial: Optional[serial.Serial] = None
        self._lock: threading.Lock = threading.Lock()
        self._is_open: bool = False

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open and self._serial is not None and self._serial.is_open

    @property
    def in_waiting(self) -> int:
        with self._lock:
            if self._serial and self._serial.is_open:
                return self._serial.in_waiting
            return 0

    def open(self) -> bool:
        """Open serial port. Returns True on success."""
        if serial is None:
            return False

        with self._lock:
            serial_id = id(self._serial) if self._serial else 0
            logger.info("[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER PORT=%s SERIAL_ID=%d ACTION=open IS_OPEN=%s",
                        self._port_name, serial_id, self._is_open)
            try:
                if self._serial and self._serial.is_open:
                    self._serial.close()

                self._serial = serial.Serial(
                    port=self._port_name,
                    baudrate=self._baud_rate,
                    timeout=self._timeout,
                    write_timeout=self._timeout,
                )
                self._is_open = True
                logger.info("[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER PORT=%s SERIAL_ID=%d ACTION=opened IS_OPEN=True",
                            self._port_name, id(self._serial))
                return True
            except Exception:
                self._is_open = False
                return False

    def close(self) -> None:
        """Close serial port."""
        with self._lock:
            serial_id = id(self._serial) if self._serial else 0
            logger.info("[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER PORT=%s SERIAL_ID=%d ACTION=close IS_OPEN=%s",
                        self._port_name, serial_id, self._is_open)
            logger.info("[PORT CLOSED TRACE] PORT=%s SERIAL_ID=%d CALLER=SerialAdapter REASON=close",
                        self._port_name, serial_id)
            try:
                if self._serial and self._serial.is_open:
                    self._serial.close()
            except Exception:
                pass
            finally:
                self._is_open = False
                self._serial = None
                logger.info("[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER PORT=%s ACTION=closed IS_OPEN=False SERIAL=NULL",
                            self._port_name)

    def write(self, data: bytes) -> bool:
        """Write bytes to serial port. Returns True on success.

        Sprint 15L: [SERIAL WRITE] byte-level tracing.
        """
        with self._lock:
            serial_id = id(self._serial) if self._serial else 0
            is_open = self._serial is not None and self._serial.is_open
            text = data.decode("ascii", errors="ignore")
            logger.debug("[SERIAL WRITE] PORT=%s BYTES=%d HEX=%s TEXT=%s",
                         self._port_name, len(data), data.hex(), text.strip())
            logger.debug("[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER PORT=%s SERIAL_ID=%d ACTION=write IS_OPEN=%s",
                         self._port_name, serial_id, is_open)

            if not self._serial or not self._serial.is_open:
                logger.info("[SERIAL WRITE RESULT] PORT=%s SUCCESS=NO REASON=port_not_open", self._port_name)
                return False
            try:
                written = self._serial.write(data)
                logger.debug("[SERIAL WRITE RESULT] PORT=%s SUCCESS=YES BYTES_WRITTEN=%d", self._port_name, written)
                return True
            except Exception as e:
                logger.info("[SERIAL WRITE RESULT] PORT=%s SUCCESS=NO REASON=%s", self._port_name, str(e))
                return False

    def read(self, size: int = 1) -> bytes:
        """Read bytes from serial port."""
        with self._lock:
            serial_id = id(self._serial) if self._serial else 0
            is_open = self._serial is not None and self._serial.is_open
            logger.debug("[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER PORT=%s SERIAL_ID=%d ACTION=read IS_OPEN=%s",
                         self._port_name, serial_id, is_open)
            if not self._serial or not self._serial.is_open:
                return b""
            try:
                return self._serial.read(size)
            except Exception:
                return b""

    def readline(self) -> bytes:
        """Read a line from serial port."""
        with self._lock:
            serial_id = id(self._serial) if self._serial else 0
            is_open = self._serial is not None and self._serial.is_open
            logger.debug("[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER PORT=%s SERIAL_ID=%d ACTION=readline IS_OPEN=%s",
                         self._port_name, serial_id, is_open)
            if not self._serial or not self._serial.is_open:
                return b""
            try:
                return self._serial.readline()
            except Exception:
                return b""

    def reset_input_buffer(self) -> None:
        """Clear input buffer."""
        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.reset_input_buffer()
                except Exception:
                    pass

    def reset_output_buffer(self) -> None:
        """Clear output buffer."""
        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.reset_output_buffer()
                except Exception:
                    pass

    def reconnect(self, max_attempts: int = 3, delay: float = 1.0) -> bool:
        """Attempt to reconnect. Returns True on success."""
        logger.info("[PORT CLOSED TRACE] PORT=%s SERIAL_ID=%d CALLER=SerialAdapter REASON=reconnect",
                    self._port_name, id(self._serial) if self._serial else 0)
        for attempt in range(max_attempts):
            self.close()
            time.sleep(delay)
            if self.open():
                return True
        return False

    def set_baud_rate(self, baud_rate: int) -> None:
        """Change baud rate (requires reopen)."""
        self._baud_rate = baud_rate

    def set_timeout(self, timeout: float) -> None:
        """Change timeout."""
        self._timeout = timeout
        with self._lock:
            if self._serial:
                self._serial.timeout = timeout
