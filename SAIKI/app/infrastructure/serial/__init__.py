"""Serial Infrastructure — PySerial adapters for modem communication."""

from app.infrastructure.serial.serial_adapter import SerialAdapter
from app.infrastructure.serial.port_scanner import PortScanner, PortInfo
from app.infrastructure.serial.at_client import ATClient, AtResponse
from app.infrastructure.serial.modem_detector import ModemDetector, ModemInfo

__all__ = [
    "SerialAdapter",
    "PortScanner",
    "PortInfo",
    "ATClient",
    "AtResponse",
    "ModemDetector",
    "ModemInfo",
]
