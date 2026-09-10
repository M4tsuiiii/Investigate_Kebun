"""Tests for app/infrastructure/serial/serial_adapter.py — SerialAdapter.

SerialAdapter wraps pyserial for modem communication with thread-safe operations.
All pyserial calls are mocked — no real hardware access.
"""

import unittest
import threading
from unittest.mock import MagicMock, patch, PropertyMock

from app.infrastructure.serial.serial_adapter import SerialAdapter


class TestSerialAdapter(unittest.TestCase):
    """Test SerialAdapter — PySerial wrapper for modem communication."""

    def setUp(self) -> None:
        self.adapter = SerialAdapter(port_name="COM3", baud_rate=115200, timeout=1.0)

    @patch("app.infrastructure.serial.serial_adapter.serial", None)
    def test_initial_state_not_open(self) -> None:
        self.assertFalse(self.adapter.is_open)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_open_success(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_module.Serial.return_value = mock_ser

        result = self.adapter.open()
        self.assertTrue(result)
        self.assertTrue(self.adapter.is_open)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_open_failure_returns_false(self, mock_serial_module: MagicMock) -> None:
        mock_serial_module.Serial.side_effect = OSError("Port not found")

        result = self.adapter.open()
        self.assertFalse(result)
        self.assertFalse(self.adapter.is_open)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_close_sets_not_open(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        self.adapter.close()
        self.assertFalse(self.adapter.is_open)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_write_when_open_returns_true(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        result = self.adapter.write(b"AT\r\n")
        self.assertTrue(result)
        mock_ser.write.assert_called_once_with(b"AT\r\n")

    def test_write_when_closed_returns_false(self) -> None:
        result = self.adapter.write(b"AT\r\n")
        self.assertFalse(result)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_write_exception_returns_false(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.write.side_effect = OSError("Write failed")
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        result = self.adapter.write(b"AT\r\n")
        self.assertFalse(result)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_read_when_open_returns_data(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.read.return_value = b"OK"
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        data = self.adapter.read(2)
        self.assertEqual(data, b"OK")
        mock_ser.read.assert_called_once_with(2)

    def test_read_when_closed_returns_empty(self) -> None:
        data = self.adapter.read(10)
        self.assertEqual(data, b"")

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_readline_when_open(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.readline.return_value = b"OK\r\n"
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        line = self.adapter.readline()
        self.assertEqual(line, b"OK\r\n")

    def test_readline_when_closed_returns_empty(self) -> None:
        line = self.adapter.readline()
        self.assertEqual(line, b"")

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_reset_input_buffer_when_open(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        self.adapter.reset_input_buffer()
        mock_ser.reset_input_buffer.assert_called_once()

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_reset_output_buffer_when_open(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        self.adapter.reset_output_buffer()
        mock_ser.reset_output_buffer.assert_called_once()

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_in_waiting_returns_count(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.in_waiting = 5
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        self.assertEqual(self.adapter.in_waiting, 5)

    def test_in_waiting_when_closed_returns_zero(self) -> None:
        self.assertEqual(self.adapter.in_waiting, 0)

    def test_set_baud_rate(self) -> None:
        self.adapter.set_baud_rate(9600)
        self.assertEqual(self.adapter._baud_rate, 9600)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_set_timeout(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        self.adapter.set_timeout(2.0)
        self.assertEqual(self.adapter._timeout, 2.0)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    @patch("app.infrastructure.serial.serial_adapter.time.sleep", return_value=None)
    def test_reconnect_success_on_first(self, mock_sleep: MagicMock, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_module.Serial.return_value = mock_ser

        result = self.adapter.reconnect(max_attempts=3, delay=0.0)
        self.assertTrue(result)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    @patch("app.infrastructure.serial.serial_adapter.time.sleep", return_value=None)
    def test_reconnect_success_on_retry(self, mock_sleep: MagicMock, mock_serial_module: MagicMock) -> None:
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("First attempt fails")
            mock_ser = MagicMock()
            mock_ser.is_open = True
            return mock_ser

        mock_serial_module.Serial.side_effect = side_effect

        result = self.adapter.reconnect(max_attempts=3, delay=0.0)
        self.assertTrue(result)
        self.assertEqual(call_count, 2)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    @patch("app.infrastructure.serial.serial_adapter.time.sleep", return_value=None)
    def test_reconnect_all_fail_returns_false(self, mock_sleep: MagicMock, mock_serial_module: MagicMock) -> None:
        mock_serial_module.Serial.side_effect = OSError("Always fails")

        result = self.adapter.reconnect(max_attempts=3, delay=0.0)
        self.assertFalse(result)

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_port_name_property(self, mock_serial_module: MagicMock) -> None:
        self.assertEqual(self.adapter.port_name, "COM3")

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_read_exception_returns_empty(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.read.side_effect = OSError("Read error")
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        data = self.adapter.read(5)
        self.assertEqual(data, b"")

    @patch("app.infrastructure.serial.serial_adapter.serial")
    def test_readline_exception_returns_empty(self, mock_serial_module: MagicMock) -> None:
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.readline.side_effect = OSError("Readline error")
        mock_serial_module.Serial.return_value = mock_ser
        self.adapter.open()

        data = self.adapter.readline()
        self.assertEqual(data, b"")


if __name__ == "__main__":
    unittest.main()
