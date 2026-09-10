"""Tests for worker/cpin_runtime.py — CpinRuntime.

CpinRuntime polls AT+CPIN? and publishes state transitions via EventBus.
Tests use mocked at_client and event_bus to verify polling logic without hardware.
"""

import unittest
import threading
from unittest.mock import MagicMock, patch, PropertyMock

from app.domain.enums import CpinState
from worker.cpin_runtime import CpinRuntime


def _make_response(raw: str) -> MagicMock:
    resp = MagicMock()
    resp.raw = raw
    return resp


class TestCpinRuntime(unittest.TestCase):
    """Test CpinRuntime — AT+CPIN? polling and event publishing."""

    def setUp(self) -> None:
        self.mock_at = MagicMock()
        self.mock_event_bus = MagicMock()
        self.runtime = CpinRuntime(
            port_id="COM3",
            at_client=self.mock_at,
            event_bus=self.mock_event_bus,
        )

    def test_initial_state_is_unknown(self) -> None:
        self.assertEqual(self.runtime.cpin_state, CpinState.UNKNOWN)

    def test_poll_once_updates_state(self) -> None:
        self.mock_at.send_command.return_value = _make_response("OK\r\n+CPIN: READY")
        self.runtime._poll_once()
        self.assertEqual(self.runtime.cpin_state, CpinState.READY)

    def test_poll_once_publishes_event_on_change(self) -> None:
        self.mock_at.send_command.return_value = _make_response("OK\r\n+CPIN: READY")
        self.runtime._poll_once()
        self.mock_event_bus.publish.assert_called_once()
        args = self.mock_event_bus.publish.call_args
        self.assertEqual(args[0][0], "cpin.transition")
        payload = args[0][1]
        self.assertEqual(payload["old"], CpinState.UNKNOWN.value)
        self.assertEqual(payload["new"], CpinState.READY.value)
        self.assertEqual(payload["port"], "COM3")

    def test_poll_once_no_publish_on_same_state(self) -> None:
        self.mock_at.send_command.return_value = _make_response("OK\r\n+CPIN: NOT INSERTED")
        self.runtime._poll_once()
        self.mock_event_bus.publish.assert_called_once()
        self.mock_event_bus.publish.reset_mock()

        self.mock_at.send_command.return_value = _make_response("OK\r\n+CPIN: NOT INSERTED")
        self.runtime._poll_once()
        self.mock_event_bus.publish.assert_not_called()

    def test_poll_once_no_event_bus_no_crash(self) -> None:
        runtime = CpinRuntime(
            port_id="COM3",
            at_client=self.mock_at,
            event_bus=None,
        )
        self.mock_at.send_command.return_value = _make_response("OK\r\n+CPIN: READY")
        runtime._poll_once()
        self.assertEqual(runtime.cpin_state, CpinState.READY)

    def test_poll_once_no_at_client_no_crash(self) -> None:
        runtime = CpinRuntime(
            port_id="COM3",
            at_client=None,
            event_bus=self.mock_event_bus,
        )
        runtime._poll_once()
        self.assertEqual(runtime.cpin_state, CpinState.UNKNOWN)
        self.mock_event_bus.publish.assert_not_called()

    def test_start_creates_thread(self) -> None:
        self.runtime.start()
        self.assertIsNotNone(self.runtime._thread)
        self.assertTrue(self.runtime._thread.is_alive())
        self.runtime.stop()
        self.runtime._thread.join(timeout=2.0)

    def test_stop_clears_running(self) -> None:
        self.runtime.start()
        self.assertTrue(self.runtime._running.is_set())
        self.runtime.stop()
        self.assertFalse(self.runtime._running.is_set())
        self.runtime._thread.join(timeout=2.0)

    def test_cpin_state_property_returns_current(self) -> None:
        self.assertEqual(self.runtime.cpin_state, CpinState.UNKNOWN)
        self.mock_at.send_command.return_value = _make_response("OK\r\n+CPIN: READY")
        self.runtime._poll_once()
        self.assertEqual(self.runtime.cpin_state, CpinState.READY)


if __name__ == "__main__":
    unittest.main()
