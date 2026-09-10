"""Tests for app/infrastructure/serial/at_client.py — ATClient.

ATClient implements AT command pipeline with timeout handling:
send → wait → parse → cleanup.
All serial I/O is mocked — no real hardware access.
"""

import unittest
from unittest.mock import MagicMock, patch, call

from app.infrastructure.serial.at_client import ATClient, AtResponse


class TestAtResponse(unittest.TestCase):
    """Test AtResponse — parsed AT command response data class."""

    def test_success_property(self) -> None:
        resp = AtResponse(raw="OK", lines=["OK"], is_ok=True, is_error=False, timeout=False)
        self.assertTrue(resp.success)

    def test_not_success_on_error(self) -> None:
        resp = AtResponse(raw="ERROR", lines=["ERROR"], is_ok=False, is_error=True, timeout=False)
        self.assertFalse(resp.success)

    def test_not_success_on_timeout(self) -> None:
        resp = AtResponse(raw="", lines=[], is_ok=False, is_error=False, timeout=True)
        self.assertFalse(resp.success)

    def test_not_success_on_ok_and_error(self) -> None:
        resp = AtResponse(raw="OK\nERROR", lines=["OK", "ERROR"], is_ok=True, is_error=True, timeout=False)
        self.assertFalse(resp.success)

    def test_repr(self) -> None:
        resp = AtResponse(raw="OK", lines=["OK"], is_ok=True, is_error=False, timeout=False)
        self.assertIn("ok=True", repr(resp))
        self.assertIn("error=False", repr(resp))


class TestATClient(unittest.TestCase):
    """Test ATClient — AT command pipeline with timeout handling."""

    def setUp(self) -> None:
        self.mock_serial = MagicMock()
        self.mock_cleanup = MagicMock()
        self.client = ATClient(serial_adapter=self.mock_serial, cleanup_manager=self.mock_cleanup)

    @patch("app.infrastructure.serial.at_client.time.sleep", return_value=None)
    @patch("app.infrastructure.serial.at_client.time.time")
    def test_send_command_success(self, mock_time: MagicMock, mock_sleep: MagicMock) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [
            b"+CPIN: READY\r\n",
            b"OK\r\n",
            b"",
            b"",
        ]
        mock_time.side_effect = [0.0, 0.01, 0.02, 0.03, 0.04, 100.0]

        response = self.client.send_command("AT+CPIN?")
        self.assertTrue(response.is_ok)
        self.assertFalse(response.is_error)
        self.assertIn("OK", response.raw)

    def test_send_command_write_failure_returns_error(self) -> None:
        self.mock_serial.write.return_value = False

        response = self.client.send_command("AT")
        self.assertTrue(response.is_error)
        self.assertFalse(response.is_ok)

    def test_send_command_calls_cleanup(self) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [b"OK\r\n", b"", b"", b"", b"", b"", b"", b"", b"", b"", b""]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 100.0]):
            self.client.send_command("AT")
        self.mock_cleanup.clear_buffer.assert_called()

    def test_send_command_no_cleanup_no_crash(self) -> None:
        client = ATClient(serial_adapter=self.mock_serial, cleanup_manager=None)
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [b"OK\r\n", b"", b"", b"", b"", b"", b"", b"", b"", b"", b""]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 100.0]):
            response = client.send_command("AT")
        self.assertTrue(response.is_ok)

    @patch("app.infrastructure.serial.at_client.time.sleep", return_value=None)
    @patch("app.infrastructure.serial.at_client.time.time")
    def test_send_ussd_success(self, mock_time: MagicMock, mock_sleep: MagicMock) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [
            b'+CUSD: 0,"Response text"\r\n',
            b"OK\r\n",
            b"",
            b"",
        ]
        mock_time.side_effect = [0.0, 0.01, 0.02, 0.03, 0.04, 100.0]

        response = self.client.send_ussd("*123#")
        self.assertTrue(response.is_ok)
        self.assertIn("+CUSD", response.raw)

    def test_send_ussd_publishes_via_cleanup(self) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [b"OK\r\n"]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 100.0]):
            self.client.send_ussd("*123#")
        self.mock_cleanup.close_session.assert_called()
        self.mock_cleanup.clear_buffer.assert_called()

    def test_cancel_ussd_sends_at_cusd_2(self) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [b"OK\r\n"]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 100.0]):
            self.client.cancel_ussd()
        write_args = self.mock_serial.write.call_args[0][0]
        self.assertIn(b"AT+CUSD=2", write_args)

    def test_check_modem_true_when_ok(self) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [b"OK\r\n"]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 100.0]):
            result = self.client.check_modem()
        self.assertTrue(result)

    def test_check_modem_false_when_error(self) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [b"ERROR\r\n"]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 100.0]):
            result = self.client.check_modem()
        self.assertFalse(result)

    def test_check_sim_returns_raw(self) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [
            b"+CPIN: READY\r\n",
            b"OK\r\n",
        ]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 0.02, 0.03, 100.0]):
            raw = self.client.check_sim()
        self.assertIn("+CPIN: READY", raw)

    def test_parse_response_ok(self) -> None:
        resp = self.client._parse_response("OK")
        self.assertTrue(resp.is_ok)
        self.assertFalse(resp.is_error)
        self.assertFalse(resp.timeout)

    def test_parse_response_error(self) -> None:
        resp = self.client._parse_response("ERROR")
        self.assertFalse(resp.is_ok)
        self.assertTrue(resp.is_error)

    def test_parse_response_timeout(self) -> None:
        resp = self.client._parse_response("")
        self.assertFalse(resp.is_ok)
        self.assertFalse(resp.is_error)
        self.assertTrue(resp.timeout)

    def test_at_response_success_property(self) -> None:
        resp = self.client._parse_response("OK")
        self.assertTrue(resp.success)

    def test_at_response_not_success_on_error(self) -> None:
        resp = self.client._parse_response("ERROR")
        self.assertFalse(resp.success)

    def test_send_ussd_builds_correct_command(self) -> None:
        self.mock_serial.write.return_value = True
        self.mock_serial.readline.side_effect = [b"OK\r\n"]

        with patch("app.infrastructure.serial.at_client.time.time", side_effect=[0.0, 0.01, 100.0]):
            self.client.send_ussd("185")
        write_args = self.mock_serial.write.call_args[0][0]
        self.assertIn(b'AT+CUSD=1,"185",15', write_args)


if __name__ == "__main__":
    unittest.main()
