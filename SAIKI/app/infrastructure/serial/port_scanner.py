"""PortScanner — COM port enumeration and baud detection.

Scans available COM ports and detects modem baud rates.
"""

import threading
import time
from typing import List, Optional

try:
    import serial.tools.list_ports
except ImportError:
    serial = None  # type: ignore

from app.domain.constants import DEFAULT_BAUD_RATES, DEFAULT_SCAN_TIMEOUT


class PortInfo:
    """Information about a detected COM port."""

    def __init__(self, port_name: str, description: str = "", baud_rate: int = 0) -> None:
        self.port_name: str = port_name
        self.description: str = description
        self.baud_rate: int = baud_rate

    def __repr__(self) -> str:
        return f"PortInfo({self.port_name}, baud={self.baud_rate})"


class PortScanner:
    """Scans COM ports and detects modem baud rates.

    Responsibilities:
    - Enumerate available COM ports
    - Detect baud rate by sending AT command
    - Thread-safe scanning
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._last_scan: List[PortInfo] = []

    @property
    def last_scan(self) -> List[PortInfo]:
        """Results of most recent scan."""
        with self._lock:
            return list(self._last_scan)

    def scan_ports(self) -> List[str]:
        """Scan for available COM ports. Returns list of port names."""
        if serial is None:
            return []

        ports: List[str] = []
        for port in serial.tools.list_ports.comports():
            ports.append(port.device)
        return ports

    def scan_with_info(self) -> List[PortInfo]:
        """Scan ports and return detailed info."""
        port_names = self.scan_ports()
        result: List[PortInfo] = []

        for name in port_names:
            info = PortInfo(port_name=name)
            result.append(info)

        with self._lock:
            self._last_scan = result

        return result

    def detect_baud(self, port_name: str) -> Optional[int]:
        """Detect baud rate by trying AT command at each rate.

        Returns detected baud rate or None.
        """
        if serial is None:
            return None

        for baud in DEFAULT_BAUD_RATES:
            try:
                ser = serial.Serial(
                    port=port_name,
                    baudrate=baud,
                    timeout=DEFAULT_SCAN_TIMEOUT,
                )

                ser.write(b"AT\r\n")

                response = b""
                deadline = time.time() + DEFAULT_SCAN_TIMEOUT
                while time.time() < deadline:
                    if ser.in_waiting:
                        response += ser.read(ser.in_waiting)
                        if b"OK" in response or b"ERROR" in response:
                            break
                    time.sleep(0.05)

                ser.close()

                if b"OK" in response:
                    return baud
            except Exception:
                try:
                    ser.close()
                except Exception:
                    pass

        return None

    def full_scan(self) -> List[PortInfo]:
        """Full scan: enumerate ports + detect baud rates."""
        port_names = self.scan_ports()
        result: List[PortInfo] = []

        for name in port_names:
            baud = self.detect_baud(name)
            info = PortInfo(
                port_name=name,
                baud_rate=baud if baud else 0,
            )
            result.append(info)

        with self._lock:
            self._last_scan = result

        return result
