"""Tests for worker/ussd_runtime.py — UssdRuntime.

UssdRuntime handles USSD dial commands, response classification, and cooldown.
Tests use mocked at_client and event_bus; sleep is patched to avoid real delays.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.domain.enums import UssdClass
from worker.ussd_runtime import UssdRuntime


def _make_response(raw: str, success: bool = True) -> MagicMock:
    resp = MagicMock()
    resp.raw = raw
    resp.success = success
    return resp


class TestUssdRuntime(unittest.TestCase):
    """Test UssdRuntime — USSD dial, classify, cooldown."""

    def setUp(self) -> None:
        self.mock_at = MagicMock()
        self.mock_event_bus = MagicMock()
        self.runtime = UssdRuntime(
            port_id="COM3",
            at_client=self.mock_at,
            event_bus=self.mock_event_bus,
        )

    @patch("worker.ussd_runtime.time.sleep", return_value=None)
    def test_dial_returns_raw_on_success(self, mock_sleep: MagicMock) -> None:
        self.mock_at.send_ussd.return_value = _make_response(
            '+CUSD: 0,"Nomor Anda: 081234567890"', success=True
        )
        result = self.runtime.dial("*123#")
        self.assertEqual(result, '+CUSD: 0,"Nomor Anda: 081234567890"')

    @patch("worker.ussd_runtime.time.sleep", return_value=None)
    def test_dial_returns_none_on_failure(self, mock_sleep: MagicMock) -> None:
        self.mock_at.send_ussd.return_value = _make_response(
            "ERROR", success=False
        )
        result = self.runtime.dial("*123#")
        self.assertIsNone(result)

    @patch("worker.ussd_runtime.time.sleep", return_value=None)
    def test_dial_returns_none_with_no_at_client(self, mock_sleep: MagicMock) -> None:
        runtime = UssdRuntime(port_id="COM3", at_client=None, event_bus=self.mock_event_bus)
        result = runtime.dial("*123#")
        self.assertIsNone(result)

    @patch("worker.ussd_runtime.time.sleep", return_value=None)
    def test_dial_publishes_ussd_response_event(self, mock_sleep: MagicMock) -> None:
        self.mock_at.send_ussd.return_value = _make_response(
            '+CUSD: 0,"Data: 2GB"', success=True
        )
        self.runtime.dial("*888#")
        self.mock_event_bus.publish.assert_called_once()
        args = self.mock_event_bus.publish.call_args
        self.assertEqual(args[0][0], "ussd.response")
        payload = args[0][1]
        self.assertEqual(payload["port"], "COM3")
        self.assertEqual(payload["code"], "*888#")
        self.assertEqual(payload["raw"], '+CUSD: 0,"Data: 2GB"')
        self.assertTrue(payload["success"])

    def test_classify_empty_returns_empty_payload(self) -> None:
        result = self.runtime.classify("")
        self.assertEqual(result, UssdClass.EMPTY_PAYLOAD)

    def test_classify_cusd_with_payload_returns_payload(self) -> None:
        result = self.runtime.classify('+CUSD: 0,"Nomor Anda: 081234567890"')
        self.assertEqual(result, UssdClass.PAYLOAD)

    def test_classify_cusd_without_payload_returns_status_only(self) -> None:
        result = self.runtime.classify("+CUSD: 0")
        self.assertEqual(result, UssdClass.STATUS_ONLY)

    def test_classify_ok_returns_at_ok(self) -> None:
        result = self.runtime.classify("OK")
        self.assertEqual(result, UssdClass.AT_OK)

    def test_classify_other_returns_partial(self) -> None:
        result = self.runtime.classify("some random response")
        self.assertEqual(result, UssdClass.PARTIAL)

    @patch("worker.ussd_runtime.time.sleep", return_value=None)
    def test_dial_calls_send_ussd_on_at_client(self, mock_sleep: MagicMock) -> None:
        self.mock_at.send_ussd.return_value = _make_response("OK", success=True)
        self.runtime.dial("*100#")
        self.mock_at.send_ussd.assert_called_once_with("*100#", timeout=30.0)


if __name__ == "__main__":
    unittest.main()
