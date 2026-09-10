"""Tests for worker/port_worker.py Sprint 5 changes.

PortWorker is the per-port runtime engine owning serial connection, AT client,
CPIN monitor, USSD runtime, cleanup manager, and hardware state machine.
All hardware is fully mocked — no real serial, no real sleep.
"""

import unittest
import threading
from unittest.mock import MagicMock, patch, PropertyMock, call

from app.domain.enums import CpinState, PortStatus
from app.domain.state_machine.hw_sm import HwState
from worker.port_worker import PortWorker
from worker.rules import AutoRunConfig


def _make_at_client(
    modem_ok: bool = True,
    cpin_raw: str = "+CPIN: READY",
) -> MagicMock:
    mock_at = MagicMock()
    mock_at.check_modem.return_value = modem_ok
    mock_at.check_sim.return_value = cpin_raw

    cpin_resp = MagicMock()
    cpin_resp.raw = cpin_raw
    cpin_resp.success = True

    ok_resp = MagicMock()
    ok_resp.raw = "OK"
    ok_resp.success = True

    mock_at.send_command.return_value = cpin_resp
    mock_at.send_ussd.return_value = ok_resp
    return mock_at


def _make_serial() -> MagicMock:
    mock_ser = MagicMock()
    mock_ser.is_open = True
    return mock_ser


def _make_config(enabled: bool = False) -> AutoRunConfig:
    config = AutoRunConfig()
    config.set_enabled(enabled)
    return config


class TestPortWorker(unittest.TestCase):
    """Test PortWorker — per-port runtime engine Sprint 5."""

    def setUp(self) -> None:
        self.event_bus = MagicMock()
        self.config = _make_config(enabled=False)
        self.worker = PortWorker(
            port_id="COM3",
            event_bus=self.event_bus,
            auto_run_config=self.config,
        )

    def test_connect_wires_components(self) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)

        self.assertIs(self.worker._serial, mock_serial)
        self.assertIs(self.worker._at_client, mock_at)
        self.assertIsNotNone(self.worker._cpin_runtime)
        self.assertIsNotNone(self.worker._ussd_runtime)
        self.assertIsNotNone(self.worker._cleanup)

    def test_disconnect_stops_cpin_and_closes_serial(self) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)

        self.worker.disconnect()
        self.worker._cpin_runtime.stop()
        mock_serial.close.assert_called()

    def test_disconnect_sets_modem_offline(self) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker.set_modem_online(True)

        self.worker.disconnect()
        self.assertFalse(self.worker.modem_online)

    def test_connect_transitions_hw_state(self) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)

        self.assertEqual(self.worker._hw_state.current_state, HwState.MODEM_DETECTED)

    def test_check_sim_returns_cpin_state(self) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client(cpin_raw="+CPIN: READY")
        self.worker.connect(mock_serial, mock_at)

        state = self.worker._check_sim()
        self.assertEqual(state, CpinState.READY)

    def test_check_sim_returns_unknown_with_no_at_client(self) -> None:
        state = self.worker._check_sim()
        self.assertEqual(state, CpinState.UNKNOWN)

    def test_modem_online_property(self) -> None:
        self.assertFalse(self.worker.modem_online)
        self.worker.set_modem_online(True)
        self.assertTrue(self.worker.modem_online)

    def test_set_modem_online_thread_safe(self) -> None:
        errors: list = []

        def toggle_worker() -> None:
            try:
                for _ in range(100):
                    self.worker.set_modem_online(True)
                    self.worker.set_modem_online(False)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=toggle_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_tick_does_nothing_when_modem_offline(self) -> None:
        self.worker.set_modem_online(False)
        self.worker._tick()
        self.assertFalse(self.worker._state.consume_reset())
        self.assertIsNone(self.worker._state.consume_single_action())

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_tick_executes_reset_when_pending(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker.set_modem_online(True)
        self.worker._state.request_reset()

        self.worker._tick()
        mock_at.send_command.assert_called()
        self.assertFalse(self.worker._state.consume_reset())

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_tick_executes_single_action_when_pending(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker.set_modem_online(True)
        self.worker._state.set_single_action("cek_nomor")

        self.worker._tick()
        mock_at.send_command.assert_called()

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_tick_executes_force_retry_when_pending(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker.set_modem_online(True)
        self.worker._state.set_force_retry()

        self.worker._tick()
        mock_at.send_command.assert_called()

    def test_tick_executes_auto_run_when_not_blocked(self) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker.set_modem_online(True)

        self.config.set_enabled(True)
        self.worker._state.queue_auto_run()

        with patch.object(self.worker, "_execute_auto_run") as mock_exec:
            self.worker._tick()
            mock_exec.assert_called_once()

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_execute_step_checks_sim_first(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client(cpin_raw="+CPIN: READY")
        self.worker.connect(mock_serial, mock_at)

        self.worker._execute_step("cek_nomor")
        cpin_calls = [c for c in mock_at.send_command.call_args_list
                      if "CPIN" in str(c)]
        self.assertTrue(len(cpin_calls) > 0)

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_execute_step_skips_action_when_sim_not_ready(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client(cpin_raw="+CPIN: NOT INSERTED")
        self.worker.connect(mock_serial, mock_at)
        mock_at.send_command.reset_mock()  # Reset after connect() to only count _execute_step calls

        self.worker._execute_step("cek_nomor")
        at_calls = [c for c in mock_at.send_command.call_args_list
                    if "AT" in str(c) and "CPIN" not in str(c)]
        self.assertEqual(len(at_calls), 0)

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_execute_step_cek_nomor_sends_at(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)

        self.worker._execute_step("cek_nomor")
        at_calls = [c for c in mock_at.send_command.call_args_list
                    if c[0][0] == "AT"]
        self.assertTrue(len(at_calls) > 0)

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_execute_step_cek_nik_dials_ussd(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)

        self.worker._execute_step("cek_nik")
        mock_at.send_ussd.assert_called()

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_execute_step_calls_cleanup(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker._cleanup = MagicMock()

        self.worker._execute_step("cek_nomor")
        self.worker._cleanup.full_cleanup.assert_called()

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_execute_auto_run_runs_all_steps(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker.set_modem_online(True)
        self.worker._running.set()

        with patch.object(self.worker, "_execute_step") as mock_step:
            self.worker._execute_auto_run()
            expected_steps = ["cek_nomor", "cek_status", "cek_nik", "cek_kk", "reaktivasi"]
            actual_steps = [c[0][0] for c in mock_step.call_args_list]
            self.assertEqual(actual_steps, expected_steps)

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_execute_auto_run_stops_on_modem_offline(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.worker._running.set()

        def toggle_offline(*args, **kwargs):
            self.worker.set_modem_online(False)

        with patch.object(self.worker, "_execute_step", side_effect=toggle_offline):
            self.worker._execute_auto_run()
        self.assertFalse(self.worker.modem_online)

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_hw_restart_sends_atz(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)

        self.worker._execute_hardware_restart()
        atz_calls = [c for c in mock_at.send_command.call_args_list
                     if "ATZ" in str(c)]
        self.assertTrue(len(atz_calls) > 0)

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_hw_restart_detects_sim(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)

        self.worker._execute_hardware_restart()
        mock_at.check_modem.assert_called()
        cpin_calls = [c for c in mock_at.send_command.call_args_list
                      if "CPIN" in str(c)]
        self.assertTrue(len(cpin_calls) > 0)

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_hw_restart_queues_auto_run_when_enabled(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.config.set_enabled(True)

        self.worker._execute_hardware_restart()
        self.assertTrue(self.worker._state.consume_auto_run())

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_hw_restart_standby_when_disabled(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client()
        self.worker.connect(mock_serial, mock_at)
        self.config.set_enabled(False)

        self.worker._execute_hardware_restart()
        self.assertFalse(self.worker._state.consume_auto_run())

    @patch("worker.port_worker.time.sleep", return_value=None)
    def test_hw_restart_gagal_when_modem_offline(self, mock_sleep: MagicMock) -> None:
        mock_serial = _make_serial()
        mock_at = _make_at_client(modem_ok=False)
        self.worker.connect(mock_serial, mock_at)

        self.worker._execute_hardware_restart()
        self.assertFalse(self.worker.modem_online)
        self.assertEqual(self.worker._state.status, PortStatus.GAGAL)

    def test_port_id_property(self) -> None:
        self.assertEqual(self.worker.port_id, "COM3")

    def test_state_property(self) -> None:
        self.assertIsNotNone(self.worker.state)
        self.assertEqual(self.worker.state.port_name, "COM3")

    def test_is_alive_false_when_no_thread(self) -> None:
        self.assertFalse(self.worker.is_alive)


if __name__ == "__main__":
    unittest.main()
