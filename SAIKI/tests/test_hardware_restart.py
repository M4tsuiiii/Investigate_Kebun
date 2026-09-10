"""Tests for worker/hardware_restart.py — HardwareRestart class."""

import unittest
from unittest.mock import MagicMock, patch, call

from app.domain.enums import CpinState
from app.domain.constants import STABILIZATION_SECONDS, CPIN_POLL_TIMEOUT
from worker.hardware_restart import HardwareRestart


class TestHardwareRestartRestartModem(unittest.TestCase):
    """Tests for HardwareRestart.restart_modem."""

    def setUp(self):
        self.modem = MagicMock()
        self.event_bus = MagicMock()
        self.hr = HardwareRestart(self.modem, self.event_bus)

    @patch("worker.hardware_restart.time.sleep")
    def test_sends_atz_and_waits(self, mock_sleep):
        """restart_modem should send ATZ then wait for stabilization."""
        self.modem.send_at.return_value = "OK"

        result = self.hr.restart_modem()

        self.assertTrue(result)
        self.modem.send_at.assert_called_once_with("ATZ", timeout=5.0)
        mock_sleep.assert_called_once_with(STABILIZATION_SECONDS)

    @patch("worker.hardware_restart.time.sleep")
    def test_returns_true_on_response(self, mock_sleep):
        """restart_modem should return True when modem responds."""
        self.modem.send_at.return_value = "OK"
        self.assertTrue(self.hr.restart_modem())

    @patch("worker.hardware_restart.time.sleep")
    def test_returns_false_on_exception(self, mock_sleep):
        """restart_modem should return False on exception."""
        self.modem.send_at.side_effect = Exception("error")
        self.assertFalse(self.hr.restart_modem())

    @patch("worker.hardware_restart.time.sleep")
    def test_returns_false_on_none_response(self, mock_sleep):
        """restart_modem should return False when response is None."""
        self.modem.send_at.return_value = None
        self.assertFalse(self.hr.restart_modem())

    @patch("worker.hardware_restart.time.sleep")
    def test_no_modem_returns_false(self, mock_sleep):
        """restart_modem with no modem should return False."""
        hr = HardwareRestart(None)
        self.assertFalse(hr.restart_modem())


class TestHardwareRestartWaitOnline(unittest.TestCase):
    """Tests for HardwareRestart.wait_online."""

    def setUp(self):
        self.modem = MagicMock()
        self.hr = HardwareRestart(self.modem)

    @patch("worker.hardware_restart.time.sleep")
    def test_polls_until_response(self, mock_sleep):
        """wait_online should poll AT until modem responds."""
        self.modem.send_at.side_effect = [None, None, "OK"]

        result = self.hr.wait_online(timeout=10.0)

        self.assertTrue(result)
        self.assertEqual(self.modem.send_at.call_count, 3)
        self.modem.send_at.assert_called_with("AT", timeout=2.0)

    @patch("worker.hardware_restart.time.sleep")
    def test_timeout_returns_false(self, mock_sleep):
        """wait_online should return False after timeout."""
        self.modem.send_at.return_value = None

        result = self.hr.wait_online(timeout=0.1)

        self.assertFalse(result)

    @patch("worker.hardware_restart.time.sleep")
    def test_no_modem_returns_false(self, mock_sleep):
        """wait_online with no modem should return False."""
        hr = HardwareRestart(None)
        self.assertFalse(hr.wait_online(timeout=5.0))

    @patch("worker.hardware_restart.time.sleep")
    def test_exception_continues_polling(self, mock_sleep):
        """wait_online should continue polling through exceptions."""
        self.modem.send_at.side_effect = [Exception("err"), "OK"]

        result = self.hr.wait_online(timeout=10.0)
        self.assertTrue(result)


class TestHardwareRestartDetectSim(unittest.TestCase):
    """Tests for HardwareRestart.detect_sim."""

    def setUp(self):
        self.modem = MagicMock()
        self.hr = HardwareRestart(self.modem)

    def test_ready_returns_cpin_ready(self):
        """detect_sim should return READY when response contains READY."""
        self.modem.send_at.return_value = "+CPIN: READY"
        self.assertEqual(self.hr.detect_sim(), CpinState.READY)

    def test_not_inserted_returns_cpin_not_inserted(self):
        """detect_sim should return NOT_INSERTED when response contains NOT INSERTED."""
        self.modem.send_at.return_value = "+CPIN: SIM NOT INSERTED"
        self.assertEqual(self.hr.detect_sim(), CpinState.NOT_INSERTED)

    def test_pin_required_returns_cpin_pin_required(self):
        """detect_sim should return PIN_REQUIRED when response contains PIN REQUIRED."""
        self.modem.send_at.return_value = "+CPIN: SIM PIN"
        self.assertEqual(self.hr.detect_sim(), CpinState.PIN_REQUIRED)

    def test_not_ready_returns_cpin_not_ready(self):
        """detect_sim should return NOT_READY for unrecognized responses."""
        self.modem.send_at.return_value = "+CPIN: ERROR"
        self.assertEqual(self.hr.detect_sim(), CpinState.NOT_READY)

    def test_none_response_returns_unknown(self):
        """detect_sim should return UNKNOWN on None response."""
        self.modem.send_at.return_value = None
        self.assertEqual(self.hr.detect_sim(), CpinState.UNKNOWN)

    def test_exception_returns_unknown(self):
        """detect_sim should return UNKNOWN on exception."""
        self.modem.send_at.side_effect = Exception("error")
        self.assertEqual(self.hr.detect_sim(), CpinState.UNKNOWN)

    def test_no_modem_returns_unknown(self):
        """detect_sim with no modem should return UNKNOWN."""
        hr = HardwareRestart(None)
        self.assertEqual(hr.detect_sim(), CpinState.UNKNOWN)

    def test_case_insensitive_ready(self):
        """detect_sim should handle lowercase response."""
        self.modem.send_at.return_value = "ready"
        self.assertEqual(self.hr.detect_sim(), CpinState.READY)


class TestHardwareRestartExecuteFullRestart(unittest.TestCase):
    """Tests for HardwareRestart.execute_full_restart."""

    def setUp(self):
        self.modem = MagicMock()
        self.hr = HardwareRestart(self.modem)

    @patch("worker.hardware_restart.time.sleep")
    def test_chains_restart_wait_detect(self, mock_sleep):
        """execute_full_restart should chain restart → wait → detect."""
        self.modem.send_at.side_effect = [
            "OK",   # ATZ (restart)
            "OK",   # AT (wait online)
            "+CPIN: READY",  # AT+CPIN? (detect)
        ]

        online, sim_state = self.hr.execute_full_restart()

        self.assertTrue(online)
        self.assertEqual(sim_state, CpinState.READY)

    @patch("worker.hardware_restart.time.sleep")
    def test_offline_returns_false_unknown(self, mock_sleep):
        """execute_full_restart should return (False, UNKNOWN) if offline."""
        self.modem.send_at.side_effect = [
            "OK",   # ATZ
            None,   # AT timeout
        ]

        online, sim_state = self.hr.execute_full_restart()

        self.assertFalse(online)
        self.assertEqual(sim_state, CpinState.UNKNOWN)


class TestHardwareRestartEvaluatePostRestart(unittest.TestCase):
    """Tests for HardwareRestart.evaluate_post_restart."""

    def setUp(self):
        self.hr = HardwareRestart(MagicMock())

    def test_online_ready_auto_run_on_returns_automation(self):
        """online + READY + auto_run ON → automation."""
        result = self.hr.evaluate_post_restart(
            online=True, sim_state=CpinState.READY, auto_run_enabled=True
        )
        self.assertEqual(result, "automation")

    def test_online_ready_auto_run_off_returns_standby(self):
        """online + READY + auto_run OFF → standby."""
        result = self.hr.evaluate_post_restart(
            online=True, sim_state=CpinState.READY, auto_run_enabled=False
        )
        self.assertEqual(result, "standby")

    def test_online_not_inserted_returns_standby(self):
        """online + NOT_INSERTED → standby."""
        result = self.hr.evaluate_post_restart(
            online=True, sim_state=CpinState.NOT_INSERTED, auto_run_enabled=True
        )
        self.assertEqual(result, "standby")

    def test_online_pin_required_returns_standby(self):
        """online + PIN_REQUIRED → standby."""
        result = self.hr.evaluate_post_restart(
            online=True, sim_state=CpinState.PIN_REQUIRED, auto_run_enabled=True
        )
        self.assertEqual(result, "standby")

    def test_offline_returns_standby(self):
        """offline → standby regardless of other state."""
        result = self.hr.evaluate_post_restart(
            online=False, sim_state=CpinState.READY, auto_run_enabled=True
        )
        self.assertEqual(result, "standby")

    def test_online_unknown_returns_standby(self):
        """online + UNKNOWN → standby."""
        result = self.hr.evaluate_post_restart(
            online=True, sim_state=CpinState.UNKNOWN, auto_run_enabled=True
        )
        self.assertEqual(result, "standby")

    def test_online_not_ready_returns_standby(self):
        """online + NOT_READY → standby."""
        result = self.hr.evaluate_post_restart(
            online=True, sim_state=CpinState.NOT_READY, auto_run_enabled=True
        )
        self.assertEqual(result, "standby")


if __name__ == "__main__":
    unittest.main()
