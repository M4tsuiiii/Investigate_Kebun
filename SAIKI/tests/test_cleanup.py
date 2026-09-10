"""Tests for worker/cleanup.py — CleanupManager and StepExecutor."""

import unittest
from unittest.mock import MagicMock, patch, call

from worker.cleanup import CleanupManager, StepExecutor
from app.domain.constants import (
    USSD_SESSION_FENCE_TIMEOUT_SECONDS,
    DIAL_COOLDOWN_SECONDS,
    USSD_GRACE_READ_INITIAL_WAIT,
)


class TestCleanupManager(unittest.TestCase):
    """Tests for CleanupManager class."""

    def setUp(self):
        self.modem = MagicMock()
        self.cleanup = CleanupManager(self.modem)

    def test_close_session_sends_at_cusd_2(self):
        """close_session should send AT+CUSD=2 to cancel active session."""
        self.cleanup.close_session()
        self.modem.send_at.assert_called_once_with(
            "AT+CUSD=2", timeout=USSD_SESSION_FENCE_TIMEOUT_SECONDS
        )

    def test_close_session_no_modem(self):
        """close_session with no modem should not raise."""
        cleanup = CleanupManager(None)
        cleanup.close_session()
        self.assertTrue(True)

    def test_close_session_exception_ignored(self):
        """close_session should swallow modem exceptions (best effort)."""
        self.modem.send_at.side_effect = Exception("serial error")
        self.cleanup.close_session()
        self.assertTrue(True)

    def test_clear_buffer_calls_reset_methods(self):
        """clear_buffer should call reset_input_buffer and reset_output_buffer."""
        self.cleanup.clear_buffer()
        self.modem.reset_input_buffer.assert_called_once()
        self.modem.reset_output_buffer.assert_called_once()

    def test_clear_buffer_no_modem(self):
        """clear_buffer with no modem should not raise."""
        cleanup = CleanupManager(None)
        cleanup.clear_buffer()
        self.assertTrue(True)

    def test_clear_buffer_exception_ignored(self):
        """clear_buffer should swallow modem exceptions."""
        self.modem.reset_input_buffer.side_effect = Exception("error")
        self.cleanup.clear_buffer()
        self.assertTrue(True)

    @patch("worker.cleanup.time.sleep")
    def test_cooldown_waits_default_duration(self, mock_sleep):
        """cooldown() should wait for DIAL_COOLDOWN_SECONDS by default."""
        self.cleanup.cooldown()
        mock_sleep.assert_called_once_with(DIAL_COOLDOWN_SECONDS)

    @patch("worker.cleanup.time.sleep")
    def test_cooldown_waits_custom_duration(self, mock_sleep):
        """cooldown(seconds=2.5) should wait for 2.5 seconds."""
        self.cleanup.cooldown(seconds=2.5)
        mock_sleep.assert_called_once_with(2.5)

    @patch("worker.cleanup.time.sleep")
    def test_full_cleanup_executes_sequence(self, mock_sleep):
        """full_cleanup should: close session → sleep grace → clear buffer → cooldown."""
        self.cleanup.full_cleanup()

        calls = mock_sleep.call_args_list
        self.assertEqual(len(calls), 2)
        mock_sleep.assert_any_call(USSD_GRACE_READ_INITIAL_WAIT)
        mock_sleep.assert_any_call(DIAL_COOLDOWN_SECONDS)
        self.modem.send_at.assert_called_once()
        self.modem.reset_input_buffer.assert_called_once()
        self.modem.reset_output_buffer.assert_called_once()

    def test_set_modem_injects_new_modem(self):
        """set_modem should replace internal modem reference."""
        new_modem = MagicMock()
        self.cleanup.set_modem(new_modem)
        self.cleanup.close_session()
        new_modem.send_at.assert_called_once()


class TestStepExecutor(unittest.TestCase):
    """Tests for StepExecutor class."""

    def setUp(self):
        self.modem = MagicMock()
        self.cleanup = CleanupManager(self.modem)
        self.executor = StepExecutor(self.modem, self.cleanup)

    def test_execute_sends_command_receives_response_cleanup(self):
        """execute should: send → receive → close_session → clear_buffer → cooldown."""
        self.modem.send_ussd.return_value = "OK"

        with patch("worker.cleanup.time.sleep"):
            result = self.executor.execute("*123#")

        self.assertEqual(result, "OK")
        self.modem.send_ussd.assert_called_once_with("*123#", timeout=10.0)
        self.modem.send_at.assert_called_once()
        self.modem.reset_input_buffer.assert_called_once()
        self.modem.reset_output_buffer.assert_called_once()

    def test_execute_returns_none_on_exception(self):
        """execute should return None and still cleanup on exception."""
        self.modem.send_ussd.side_effect = Exception("timeout")

        with patch("worker.cleanup.time.sleep"):
            result = self.executor.execute("*123#")

        self.assertIsNone(result)
        self.modem.send_at.assert_called_once()
        self.modem.reset_input_buffer.assert_called_once()

    def test_execute_custom_timeout(self):
        """execute with custom timeout should pass it to send_ussd."""
        self.modem.send_ussd.return_value = "data"

        with patch("worker.cleanup.time.sleep"):
            self.executor.execute("*123#", timeout=15.0)

        self.modem.send_ussd.assert_called_once_with("*123#", timeout=15.0)

    def test_execute_no_modem_returns_none(self):
        """execute with no modem should return None."""
        executor = StepExecutor(None, self.cleanup)
        result = executor.execute("*123#")
        self.assertIsNone(result)

    def test_execute_at_sends_at_command_cleanup(self):
        """execute_at should: send AT command → clear buffer."""
        self.modem.send_at.return_value = "OK"

        with patch("worker.cleanup.time.sleep"):
            result = self.executor.execute_at("AT+CPIN?")

        self.assertEqual(result, "OK")
        self.modem.send_at.assert_called_once_with("AT+CPIN?", timeout=2.0)
        self.modem.reset_input_buffer.assert_called_once()
        self.modem.reset_output_buffer.assert_called_once()

    def test_execute_at_on_exception_still_cleanup(self):
        """execute_at should still cleanup on exception."""
        self.modem.send_at.side_effect = Exception("error")

        with patch("worker.cleanup.time.sleep"):
            result = self.executor.execute_at("AT+CPIN?")

        self.assertIsNone(result)
        self.modem.reset_input_buffer.assert_called_once()

    def test_execute_at_no_modem_returns_none(self):
        """execute_at with no modem should return None."""
        executor = StepExecutor(None, self.cleanup)
        result = executor.execute_at("AT")
        self.assertIsNone(result)

    def test_execute_at_custom_timeout(self):
        """execute_at with custom timeout should pass it to send_at."""
        self.modem.send_at.return_value = "AT OK"

        with patch("worker.cleanup.time.sleep"):
            self.executor.execute_at("AT", timeout=5.0)

        self.modem.send_at.assert_called_once_with("AT", timeout=5.0)


if __name__ == "__main__":
    unittest.main()
