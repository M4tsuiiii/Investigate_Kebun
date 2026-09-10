"""Tests for app/infrastructure/serial/port_scanner.py — PortScanner.

PortScanner enumerates COM ports and detects modem baud rates.
Tests mock the serial.tools.list_ports module — no real serial access.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.infrastructure.serial.port_scanner import PortScanner, PortInfo


class TestPortScanner(unittest.TestCase):
    """Test PortScanner — COM port enumeration and info."""

    def setUp(self) -> None:
        self.scanner = PortScanner()

    @patch("app.infrastructure.serial.port_scanner.serial", None)
    def test_scan_ports_returns_list(self) -> None:
        result = self.scanner.scan_ports()
        self.assertIsInstance(result, list)

    @patch("app.infrastructure.serial.port_scanner.serial", None)
    def test_scan_ports_empty_when_no_serial(self) -> None:
        result = self.scanner.scan_ports()
        self.assertEqual(result, [])

    @patch("app.infrastructure.serial.port_scanner.serial")
    def test_scan_with_info_returns_port_info_list(self, mock_serial: MagicMock) -> None:
        mock_port = MagicMock()
        mock_port.device = "COM3"
        mock_serial.tools.list_ports.comports.return_value = [mock_port]

        result = self.scanner.scan_with_info()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        self.assertIsInstance(result[0], PortInfo)

    @patch("app.infrastructure.serial.port_scanner.serial")
    def test_last_scan_stores_results(self, mock_serial: MagicMock) -> None:
        mock_port = MagicMock()
        mock_port.device = "COM5"
        mock_serial.tools.list_ports.comports.return_value = [mock_port]

        self.scanner.scan_with_info()
        last = self.scanner.last_scan
        self.assertTrue(len(last) > 0)
        self.assertEqual(last[0].port_name, "COM5")

    def test_port_info_repr(self) -> None:
        info = PortInfo(port_name="COM3", baud_rate=115200)
        self.assertIn("COM3", repr(info))
        self.assertIn("115200", repr(info))

    def test_port_info_defaults(self) -> None:
        info = PortInfo(port_name="COM7")
        self.assertEqual(info.port_name, "COM7")
        self.assertEqual(info.description, "")
        self.assertEqual(info.baud_rate, 0)

    @patch("app.infrastructure.serial.port_scanner.serial", None)
    def test_scan_ports_returns_empty_when_no_serial(self) -> None:
        result = self.scanner.scan_ports()
        self.assertEqual(result, [])

    @patch("app.infrastructure.serial.port_scanner.serial")
    def test_scan_ports_returns_device_names(self, mock_serial: MagicMock) -> None:
        port1 = MagicMock()
        port1.device = "COM3"
        port2 = MagicMock()
        port2.device = "COM5"
        mock_serial.tools.list_ports.comports.return_value = [port1, port2]

        result = self.scanner.scan_ports()
        self.assertEqual(result, ["COM3", "COM5"])

    @patch("app.infrastructure.serial.port_scanner.serial")
    def test_scan_with_info_stores_last_scan(self, mock_serial: MagicMock) -> None:
        mock_serial.tools.list_ports.comports.return_value = []
        self.scanner.scan_with_info()
        self.assertEqual(self.scanner.last_scan, [])

    @patch("app.infrastructure.serial.port_scanner.serial")
    def test_detect_baud_returns_none_when_no_serial(self, mock_serial: MagicMock) -> None:
        mock_serial.tools.list_ports.comports.return_value = []
        result = self.scanner.detect_baud("COM3")
        self.assertIsNone(result)

    def test_last_scan_initially_empty(self) -> None:
        self.assertEqual(self.scanner.last_scan, [])


if __name__ == "__main__":
    unittest.main()
