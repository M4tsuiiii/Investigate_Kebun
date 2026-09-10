"""Tests for worker/port_worker.py Sprint 2 changes."""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock, call

from app.domain.enums import CpinState, PortStatus
from worker.port_worker import PortWorker
from worker.rules import AutoRunConfig


def _make_worker(port_id="COM1"):
    """Helper to create a PortWorker with mocked dependencies."""
    event_bus = MagicMock()
    auto_run_config = AutoRunConfig()
    worker = PortWorker(port_id, event_bus, auto_run_config)
    return worker, event_bus, auto_run_config


class TestSetModemOnline(unittest.TestCase):
    """Tests for PortWorker.set_modem_online."""

    def test_sets_flag_true(self):
        """set_modem_online(True) should set modem_online flag."""
        worker, event_bus, _ = _make_worker()
        worker.set_modem_online(True)
        self.assertTrue(worker.modem_online)

    def test_sets_flag_false(self):
        """set_modem_online(False) should clear modem_online flag."""
        worker, _, _ = _make_worker()
        worker.set_modem_online(True)
        worker.set_modem_online(False)
        self.assertFalse(worker.modem_online)


class TestTickModemOffline(unittest.TestCase):
    """Tests for _tick when modem is offline."""

    @patch("worker.port_worker.time.sleep")
    def test_modem_offline_sleeps_no_action(self, mock_sleep):
        """_tick should sleep and return when modem is offline."""
        worker, _, _ = _make_worker()
        worker.set_modem_online(False)
        worker._tick()
        mock_sleep.assert_called_with(1.0)


class TestTickReset(unittest.TestCase):
    """Tests for _tick handling reset."""

    @patch("worker.port_worker.time.sleep")
    def test_reset_triggers_hardware_restart(self, mock_sleep):
        """_tick with reset flag should execute hardware restart."""
        worker, _, _ = _make_worker()
        worker.set_modem_online(True)
        worker._state.request_reset()

        with patch.object(worker, "_execute_hardware_restart") as mock_hr:
            worker._tick()
            mock_hr.assert_called_once()


class TestTickSingleAction(unittest.TestCase):
    """Tests for _tick handling single action."""

    @patch("worker.port_worker.time.sleep")
    def test_single_action_executes_step(self, mock_sleep):
        """_tick with single action should execute the step."""
        worker, _, _ = _make_worker()
        worker.set_modem_online(True)
        worker._state.set_single_action("cek_nomor")

        with patch.object(worker, "_execute_step") as mock_step:
            worker._tick()
            mock_step.assert_called_once_with("cek_nomor")


class TestTickForceRetry(unittest.TestCase):
    """Tests for _tick handling force retry."""

    @patch("worker.port_worker.time.sleep")
    def test_force_retry_executes_step(self, mock_sleep):
        """_tick with force_retry should execute cek_nomor step."""
        worker, _, _ = _make_worker()
        worker.set_modem_online(True)
        worker._state.set_force_retry()

        with patch.object(worker, "_execute_step") as mock_step:
            worker._tick()
            mock_step.assert_called_once_with("cek_nomor")


class TestTickAutoRunBlocked(unittest.TestCase):
    """Tests for _tick when auto-run is blocked."""

    @patch("worker.port_worker.time.sleep")
    def test_auto_run_blocked_no_action(self, mock_sleep):
        """_tick should not execute auto-run when blocked by rules."""
        worker, _, auto_run_config = _make_worker()
        worker.set_modem_online(True)
        auto_run_config.set_enabled(False)
        worker._state.queue_auto_run()

        with patch.object(worker, "_execute_auto_run") as mock_ar:
            worker._tick()
            mock_ar.assert_not_called()


class TestTickAutoRunAllowed(unittest.TestCase):
    """Tests for _tick when auto-run is allowed."""

    @patch("worker.port_worker.time.sleep")
    def test_auto_run_allowed_executes(self, mock_sleep):
        """_tick should execute auto-run when allowed by rules."""
        worker, _, auto_run_config = _make_worker()
        worker.set_modem_online(True)
        auto_run_config.set_enabled(True)
        worker._state.queue_auto_run()

        with patch.object(worker, "_execute_auto_run") as mock_ar:
            worker._tick()
            mock_ar.assert_called_once()


class TestExecuteHardwareRestart(unittest.TestCase):
    """Tests for PortWorker._execute_hardware_restart."""

    @patch("worker.cpin_runtime.CpinRuntime.start")
    @patch("worker.port_worker.time.sleep")
    def test_chains_restart_online_check_sim_detect_evaluate(self, mock_sleep, mock_cpin_start):
        """_execute_hardware_restart should chain full restart flow."""
        worker, _, auto_run_config = _make_worker()
        serial = MagicMock()
        at_client = MagicMock()

        cpin_response = MagicMock()
        cpin_response.raw = "+CPIN: READY"

        at_client.send_command.side_effect = ["OK", "OK", cpin_response]  # ATE0, ATZ, AT+CPIN?
        at_client.check_modem.return_value = True

        worker.connect(serial, at_client)
        auto_run_config.set_enabled(True)

        worker._execute_hardware_restart()

        self.assertTrue(worker.modem_online)

    @patch("worker.cpin_runtime.CpinRuntime.start")
    @patch("worker.port_worker.time.sleep")
    def test_automation_queues_auto_run(self, mock_sleep, mock_cpin_start):
        """_execute_hardware_restart should queue auto-run when action=automation."""
        worker, _, auto_run_config = _make_worker()
        serial = MagicMock()
        at_client = MagicMock()

        cpin_response = MagicMock()
        cpin_response.raw = "+CPIN: READY"

        at_client.send_command.side_effect = ["OK", "OK", cpin_response]  # ATE0, ATZ, AT+CPIN?
        at_client.check_modem.return_value = True

        worker.connect(serial, at_client)
        auto_run_config.set_enabled(True)

        worker._execute_hardware_restart()

        self.assertTrue(worker._state.consume_auto_run())

    @patch("worker.cpin_runtime.CpinRuntime.start")
    @patch("worker.port_worker.time.sleep")
    def test_standby_does_not_queue(self, mock_sleep, mock_cpin_start):
        """_execute_hardware_restart should NOT queue auto-run when standby."""
        worker, _, auto_run_config = _make_worker()
        serial = MagicMock()
        at_client = MagicMock()

        cpin_response = MagicMock()
        cpin_response.raw = "+CPIN: SIM NOT INSERTED"

        at_client.send_command.side_effect = ["OK", "OK", cpin_response]  # ATE0, ATZ, AT+CPIN?
        at_client.check_modem.return_value = True

        worker.connect(serial, at_client)
        auto_run_config.set_enabled(True)

        worker._execute_hardware_restart()

        self.assertFalse(worker._state.consume_auto_run())


class TestExecuteAutoRun(unittest.TestCase):
    """Tests for PortWorker._execute_auto_run."""

    @patch("worker.cpin_runtime.CpinRuntime.start")
    @patch("worker.port_worker.time.sleep")
    def test_step_by_step(self, mock_sleep, mock_cpin_start):
        """_execute_auto_run should execute all 5 steps."""
        worker, _, auto_run_config = _make_worker()
        serial = MagicMock()
        at_client = MagicMock()
        worker.connect(serial, at_client)
        auto_run_config.set_enabled(True)
        worker.set_modem_online(True)
        worker._running.set()

        with patch.object(worker, "_execute_step") as mock_step:
            worker._execute_auto_run()
            self.assertEqual(mock_step.call_count, 5)

    @patch("worker.cpin_runtime.CpinRuntime.start")
    @patch("worker.port_worker.time.sleep")
    def test_stops_when_modem_goes_offline(self, mock_sleep, mock_cpin_start):
        """_execute_auto_run should break when modem goes offline mid-sequence."""
        worker, _, _ = _make_worker()
        serial = MagicMock()
        at_client = MagicMock()
        worker.connect(serial, at_client)
        worker._running.set()

        call_count = [0]

        def go_offline(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                worker.set_modem_online(False)

        with patch.object(worker, "_execute_step", side_effect=go_offline):
            worker._execute_auto_run()
            self.assertLess(call_count[0], 5)


class TestExecuteStep(unittest.TestCase):
    """Tests for PortWorker._execute_step."""

    @patch("worker.cpin_runtime.CpinRuntime.start")
    @patch("worker.port_worker.time.sleep")
    def test_uses_at_client(self, mock_sleep, mock_cpin_start):
        """_execute_step should delegate to AT client."""
        worker, _, _ = _make_worker()
        serial = MagicMock()
        at_client = MagicMock()
        worker.connect(serial, at_client)

        with patch.object(worker, "_check_sim", return_value=CpinState.READY):
            worker._execute_step("cek_nomor")
            at_client.send_command.assert_called_with("AT", timeout=3.0)

    @patch("worker.port_worker.time.sleep")
    def test_publishes_busy_status(self, mock_sleep):
        """_execute_step should publish BUSY status before execution."""
        worker, event_bus, _ = _make_worker()

        worker._execute_step("cek_nomor")

        event_bus.publish.assert_any_call("ui.port.update", {
            "port": "COM1",
            "status": PortStatus.BUSY.value,
            "detail": "Executing: cek_nomor",
        })

    @patch("worker.port_worker.time.sleep")
    def test_publishes_ready_status_after(self, mock_sleep):
        """_execute_step should publish READY status after execution."""
        worker, event_bus, _ = _make_worker()

        worker._execute_step("cek_nomor")

        event_bus.publish.assert_any_call("ui.port.update", {
            "port": "COM1",
            "status": PortStatus.READY.value,
            "detail": "Done: cek_nomor",
        })


class TestPortWorkerProperties(unittest.TestCase):
    """Tests for PortWorker properties."""

    def test_port_id_property(self):
        """port_id should return the port identifier."""
        worker, _, _ = _make_worker("COM5")
        self.assertEqual(worker.port_id, "COM5")

    def test_state_property(self):
        """state should return PortWorkerState instance."""
        worker, _, _ = _make_worker()
        self.assertIsNotNone(worker.state)

    def test_is_alive_when_no_thread(self):
        """is_alive should be False when thread is None."""
        worker, _, _ = _make_worker()
        self.assertFalse(worker.is_alive)

    @patch("worker.cpin_runtime.CpinRuntime.start")
    def test_connect_wires_components(self, mock_cpin_start):
        """connect should wire serial, at_client, and cleanup."""
        worker, _, _ = _make_worker()
        serial = MagicMock()
        at_client = MagicMock()
        worker.connect(serial, at_client)
        self.assertIsNotNone(worker._at_client)
        self.assertIsNotNone(worker._cleanup)
        self.assertEqual(worker._cleanup._modem, serial)


if __name__ == "__main__":
    unittest.main()
