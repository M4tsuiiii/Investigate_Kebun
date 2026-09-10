"""Sprint 15K Tests — P1 Stability Transplant + Beta Stats.

Verifies:
- P1-001: Confirmation poll before state flip (READY→bad)
- P1-002: Flush serial buffer before CPIN query
- P1-003: Reset cleanup on hardware restart/disconnect
- Beta stats tracking per port
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock, call

from app.domain.enums import CpinState


# ======================================================================
# Helpers
# ======================================================================

def _make_at_client(raw_response="OK\r\n"):
    """Create mock ATClient returning given raw response."""
    at_client = MagicMock()
    resp = MagicMock()
    resp.raw = raw_response
    at_client.send_command.return_value = resp
    return at_client


def _make_serial():
    """Create mock SerialAdapter with flush methods."""
    serial = MagicMock()
    serial.reset_input_buffer = MagicMock()
    serial.reset_output_buffer = MagicMock()
    return serial


def _make_event_bus():
    """Create mock EventBus."""
    bus = MagicMock()
    return bus


# ======================================================================
# P1-001: Confirmation Poll Before State Flip
# ======================================================================

class TestConfirmationPoll(unittest.TestCase):
    """P1-001: When READY and raw shows bad state, confirmation poll fires."""

    def test_confirmation_poll_triggered_on_ready_to_not_ready(self):
        """READY + NOT_READY raw → confirmation poll → still NOT_READY → transition."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("NOT READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM1", at_client, event_bus)
        rt._current_state = CpinState.READY

        # Manually call _poll_once
        rt._running.set()
        rt._poll_once()

        # Should have sent 2 AT+CPIN? commands (main + confirmation)
        self.assertEqual(at_client.send_command.call_count, 2)
        # State should have flipped to NOT_READY
        self.assertEqual(rt.cpin_state, CpinState.NOT_READY)

    def test_confirmation_poll_prevented_on_ready_return(self):
        """READY + NOT_READY raw → confirmation poll → READY → IGNORE."""
        from worker.cpin_runtime import CpinRuntime

        # First call returns NOT READY, second call returns READY
        resp_bad = MagicMock()
        resp_bad.raw = "NOT READY\r\nOK\r\n"
        resp_good = MagicMock()
        resp_good.raw = "READY\r\nOK\r\n"
        at_client = MagicMock()
        at_client.send_command.side_effect = [resp_bad, resp_good]

        event_bus = _make_event_bus()
        rt = CpinRuntime("COM2", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        # Should have sent 2 AT+CPIN? commands
        self.assertEqual(at_client.send_command.call_count, 2)
        # State should remain READY (prevented)
        self.assertEqual(rt.cpin_state, CpinState.READY)
        # Beta stats should show prevented
        self.assertEqual(rt._beta_stats.confirmation_poll_triggered, 1)
        self.assertEqual(rt._beta_stats.confirmation_poll_prevented, 1)

    def test_no_confirmation_poll_when_not_ready(self):
        """NOT_READY + NOT_READY raw → no confirmation poll (not from READY)."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("NOT READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM3", at_client, event_bus)
        rt._current_state = CpinState.NOT_READY

        rt._running.set()
        rt._poll_once()

        # Should have sent only 1 AT+CPIN? command (no confirmation)
        self.assertEqual(at_client.send_command.call_count, 1)

    def test_no_confirmation_poll_when_ready_stays_ready(self):
        """READY + READY raw → no confirmation poll (no bad state)."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM4", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        # Should have sent only 1 AT+CPIN? command
        self.assertEqual(at_client.send_command.call_count, 1)
        self.assertEqual(rt.cpin_state, CpinState.READY)

    def test_confirmation_poll_for_unknown_at_threshold(self):
        """READY + UNKNOWN raw (at threshold) → confirmation poll fires."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("UNKNOWN\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM5", at_client, event_bus)
        rt._current_state = CpinState.READY
        # Set unknown_count to threshold so confirmation triggers
        rt._unknown_count = 3

        rt._running.set()
        rt._poll_once()

        # Confirmation poll should fire (unknown >= threshold)
        self.assertEqual(at_client.send_command.call_count, 2)

    def test_confirmation_poll_log_format(self):
        """Confirmation poll produces correct log format."""
        from worker.cpin_runtime import CpinRuntime

        resp_bad = MagicMock()
        resp_bad.raw = "NOT READY\r\nOK\r\n"
        resp_good = MagicMock()
        resp_good.raw = "READY\r\nOK\r\n"
        at_client = MagicMock()
        at_client.send_command.side_effect = [resp_bad, resp_good]

        event_bus = _make_event_bus()
        rt = CpinRuntime("COM6", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        with self.assertLogs("saiki.cpin", level="INFO") as cm:
            rt._poll_once()

        confirm_logs = [l for l in cm.output if "[CONFIRMATION POLL]" in l]
        self.assertTrue(len(confirm_logs) >= 3)  # triggered + result + action
        # Check PORT= and ACTION= are present
        port_logs = [l for l in confirm_logs if "PORT=COM6" in l]
        self.assertTrue(len(port_logs) >= 1)
        action_logs = [l for l in confirm_logs if "ACTION=" in l]
        self.assertTrue(len(action_logs) >= 1)

    def test_check_confirmation_needed_returns_false_for_non_ready(self):
        """_check_confirmation_needed returns False when previous is not READY."""
        from worker.cpin_runtime import CpinRuntime

        rt = CpinRuntime("COM7", _make_at_client(), _make_event_bus())
        rt._current_state = CpinState.NOT_READY

        needs, candidate = rt._check_confirmation_needed(CpinState.NOT_READY, CpinState.UNKNOWN)
        self.assertFalse(needs)

    def test_check_confirmation_needed_returns_false_for_below_threshold(self):
        """_check_confirmation_needed returns False when UNKNOWN below threshold."""
        from worker.cpin_runtime import CpinRuntime

        rt = CpinRuntime("COM8", _make_at_client(), _make_event_bus())
        rt._current_state = CpinState.READY
        rt._unknown_count = 1  # Below threshold (3)

        needs, candidate = rt._check_confirmation_needed(CpinState.READY, CpinState.UNKNOWN)
        self.assertFalse(needs)

    def test_check_confirmation_needed_returns_true_for_at_threshold(self):
        """_check_confirmation_needed returns True when UNKNOWN at threshold."""
        from worker.cpin_runtime import CpinRuntime

        rt = CpinRuntime("COM9", _make_at_client(), _make_event_bus())
        rt._current_state = CpinState.READY
        rt._unknown_count = 3  # At threshold

        needs, candidate = rt._check_confirmation_needed(CpinState.READY, CpinState.UNKNOWN)
        self.assertTrue(needs)
        self.assertEqual(candidate, CpinState.UNKNOWN)

    def test_check_confirmation_needed_for_not_inserted_at_threshold(self):
        """_check_confirmation_needed returns True when NOT_INSERTED at threshold."""
        from worker.cpin_runtime import CpinRuntime

        rt = CpinRuntime("COM10", _make_at_client(), _make_event_bus())
        rt._current_state = CpinState.READY
        rt._removal_confirm_count = 2  # At threshold

        needs, candidate = rt._check_confirmation_needed(CpinState.READY, CpinState.NOT_INSERTED)
        self.assertTrue(needs)
        self.assertEqual(candidate, CpinState.NOT_INSERTED)


# ======================================================================
# P1-002: Flush Serial Buffer Before CPIN Query
# ======================================================================

class TestBufferFlush(unittest.TestCase):
    """P1-002: Serial buffers are flushed before every CPIN query."""

    def test_flush_called_before_cpin_query(self):
        """_flush_buffers is called before AT+CPIN? in _poll_once."""
        from worker.cpin_runtime import CpinRuntime

        serial = _make_serial()
        at_client = _make_at_client("READY\r\nOK\r\n")
        # Wire serial into at_client._serial
        at_client._serial = serial

        event_bus = _make_event_bus()
        rt = CpinRuntime("COM11", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        # Serial flush methods should have been called
        serial.reset_input_buffer.assert_called()
        serial.reset_output_buffer.assert_called()

    def test_flush_count_tracked_in_beta_stats(self):
        """Buffer flush count is tracked in beta stats."""
        from worker.cpin_runtime import CpinRuntime

        serial = _make_serial()
        at_client = _make_at_client("READY\r\nOK\r\n")
        at_client._serial = serial

        rt = CpinRuntime("COM12", at_client, _make_event_bus())
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        # Flush count should be at least 1
        self.assertGreaterEqual(rt._beta_stats.buffer_flush_count, 1)

    def test_flush_logged(self):
        """Buffer flush produces [BUFFER FLUSH] log."""
        from worker.cpin_runtime import CpinRuntime

        serial = _make_serial()
        at_client = _make_at_client("READY\r\nOK\r\n")
        at_client._serial = serial

        rt = CpinRuntime("COM13", at_client, _make_event_bus())
        rt._current_state = CpinState.READY

        rt._running.set()
        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            rt._poll_once()

        flush_logs = [l for l in cm.output if "[BUFFER FLUSH]" in l]
        self.assertTrue(len(flush_logs) >= 1)
        self.assertIn("PORT=COM13", flush_logs[0])
        self.assertIn("BEFORE_CPIN=YES", flush_logs[0])

    def test_flush_during_confirmation_poll(self):
        """Flush also fires during confirmation poll."""
        from worker.cpin_runtime import CpinRuntime

        serial = _make_serial()
        resp_bad = MagicMock()
        resp_bad.raw = "NOT READY\r\nOK\r\n"
        resp_good = MagicMock()
        resp_good.raw = "READY\r\nOK\r\n"
        at_client = MagicMock()
        at_client.send_command.side_effect = [resp_bad, resp_good]
        at_client._serial = serial

        rt = CpinRuntime("COM14", at_client, _make_event_bus())
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        # flush should be called at least twice (main + confirmation)
        self.assertGreaterEqual(serial.reset_input_buffer.call_count, 2)

    def test_flush_no_serial_adapter(self):
        """Flush is safe when no serial adapter is wired."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("READY\r\nOK\r\n")
        # No _serial attribute
        at_client._serial = None

        rt = CpinRuntime("COM15", at_client, _make_event_bus())
        rt._current_state = CpinState.READY

        rt._running.set()
        # Should not raise
        rt._poll_once()
        self.assertEqual(rt.cpin_state, CpinState.READY)


# ======================================================================
# P1-003: Reset Cleanup Rule
# ======================================================================

class TestResetCleanup(unittest.TestCase):
    """P1-003: Stabilization counters reset on disconnect/restart."""

    def test_reset_stabilization_clears_all_counters(self):
        """reset_stabilization clears all stabilization counters."""
        from worker.cpin_runtime import CpinRuntime

        rt = CpinRuntime("COM16", _make_at_client(), _make_event_bus())
        # Set some values
        rt._unknown_count = 5
        rt._checking_count = 3
        rt._removal_confirm_count = 2
        rt._pending_removal = True

        rt.reset_stabilization()

        self.assertEqual(rt._unknown_count, 0)
        self.assertEqual(rt._checking_count, 0)
        self.assertEqual(rt._removal_confirm_count, 0)
        self.assertFalse(rt._pending_removal)

    def test_reset_stabilization_logged(self):
        """reset_stabilization produces [RESET CLEANUP] log."""
        from worker.cpin_runtime import CpinRuntime

        rt = CpinRuntime("COM17", _make_at_client(), _make_event_bus())

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            rt.reset_stabilization()

        cleanup_logs = [l for l in cm.output if "[RESET CLEANUP]" in l]
        self.assertEqual(len(cleanup_logs), 1)
        self.assertIn("PORT=COM17", cleanup_logs[0])
        self.assertIn("CPIN_RUNTIME_RESET=YES", cleanup_logs[0])

    def test_connect_resets_stabilization(self):
        """PortWorker.connect() resets CpinRuntime stabilization."""
        from worker.port_worker import PortWorker
        from worker.rules import AutoRunConfig

        event_bus = _make_event_bus()
        config = AutoRunConfig()
        worker = PortWorker("COM18", event_bus, config)

        # Create mock serial/at_client
        serial = _make_serial()
        at_client = _make_at_client("OK\r\n")
        at_client._serial = serial

        worker.connect(serial, at_client)

        # CpinRuntime should have been created and reset
        self.assertIsNotNone(worker._cpin_runtime)
        self.assertEqual(worker._cpin_runtime._unknown_count, 0)
        self.assertEqual(worker._cpin_runtime._checking_count, 0)
        self.assertEqual(worker._cpin_runtime._removal_confirm_count, 0)

    def test_disconnect_resets_stabilization(self):
        """PortWorker.disconnect() resets CpinRuntime stabilization."""
        from worker.port_worker import PortWorker
        from worker.rules import AutoRunConfig

        event_bus = _make_event_bus()
        config = AutoRunConfig()
        worker = PortWorker("COM19", event_bus, config)

        serial = _make_serial()
        at_client = _make_at_client("OK\r\n")
        at_client._serial = serial

        worker.connect(serial, at_client)

        # Set some stabilization values
        worker._cpin_runtime._unknown_count = 5
        worker._cpin_runtime._checking_count = 3

        worker.disconnect()

        # After disconnect, stabilization should be reset
        self.assertEqual(worker._cpin_runtime._unknown_count, 0)
        self.assertEqual(worker._cpin_runtime._checking_count, 0)

    def test_restart_resets_stabilization(self):
        """PortWorker.restart() resets CpinRuntime stabilization."""
        from worker.port_worker import PortWorker
        from worker.rules import AutoRunConfig

        event_bus = _make_event_bus()
        config = AutoRunConfig()
        worker = PortWorker("COM20", event_bus, config)

        serial = _make_serial()
        at_client = _make_at_client("OK\r\n")
        at_client._serial = serial

        worker.connect(serial, at_client)

        # Set some stabilization values
        worker._cpin_runtime._unknown_count = 5

        # restart() calls stop(), reset, hardware_restart, start()
        # We mock _execute_hardware_restart to avoid actual AT commands
        with patch.object(worker, '_execute_hardware_restart'):
            worker.restart()

        # After restart, stabilization should be reset
        self.assertEqual(worker._cpin_runtime._unknown_count, 0)


# ======================================================================
# Beta Stats
# ======================================================================

class TestBetaStats(unittest.TestCase):
    """Beta stats tracking per port."""

    def test_beta_stats_initial_values(self):
        """BetaStats initializes with all zeros."""
        from worker.cpin_runtime import BetaStats

        stats = BetaStats()
        self.assertEqual(stats.ready_count, 0)
        self.assertEqual(stats.not_ready_count, 0)
        self.assertEqual(stats.unknown_count, 0)
        self.assertEqual(stats.ready_to_not_ready, 0)
        self.assertEqual(stats.not_ready_to_ready, 0)
        self.assertEqual(stats.confirmation_poll_triggered, 0)
        self.assertEqual(stats.confirmation_poll_prevented, 0)
        self.assertEqual(stats.buffer_flush_count, 0)
        self.assertEqual(stats.cpin_poll_count, 0)

    def test_beta_stats_format_report(self):
        """BetaStats.format_report produces correct format."""
        from worker.cpin_runtime import BetaStats

        stats = BetaStats()
        stats.ready_count = 10
        stats.not_ready_count = 2
        stats.unknown_count = 1

        report = stats.format_report("COM104")
        self.assertIn("[BETA STATS] PORT=COM104", report)
        self.assertIn("READY_COUNT=10", report)
        self.assertIn("NOT_READY_COUNT=2", report)
        self.assertIn("UNKNOWN_COUNT=1", report)

    def test_beta_stats_tracks_state_changes(self):
        """CpinRuntime tracks state changes in beta stats."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM21", at_client, event_bus)
        rt._current_state = CpinState.UNKNOWN  # Start at UNKNOWN

        rt._running.set()
        rt._poll_once()

        # Should track: UNKNOWN→READY transition
        self.assertEqual(rt._beta_stats.ready_count, 1)
        self.assertEqual(rt._beta_stats.not_ready_to_ready, 0)  # From UNKNOWN, not NOT_READY

    def test_beta_stats_tracks_ready_to_not_ready(self):
        """Beta stats track READY→NOT_READY transitions."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("NOT READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM22", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        self.assertEqual(rt._beta_stats.ready_to_not_ready, 1)
        self.assertEqual(rt._beta_stats.not_ready_count, 1)

    def test_beta_stats_poll_count_increments(self):
        """CPIN poll count increments on each poll."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM23", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()
        self.assertEqual(rt._beta_stats.cpin_poll_count, 1)

        rt._poll_once()
        self.assertEqual(rt._beta_stats.cpin_poll_count, 2)

    def test_port_worker_beta_stats_report(self):
        """PortWorker exposes beta_stats_report property."""
        from worker.port_worker import PortWorker
        from worker.rules import AutoRunConfig

        event_bus = _make_event_bus()
        config = AutoRunConfig()
        worker = PortWorker("COM24", event_bus, config)

        serial = _make_serial()
        at_client = _make_at_client("OK\r\n")
        at_client._serial = serial

        worker.connect(serial, at_client)

        report = worker.beta_stats_report
        self.assertIn("[BETA STATS] PORT=COM24", report)
        self.assertIn("CPIN_POLL_COUNT=", report)

    def test_port_worker_beta_stats_no_runtime(self):
        """PortWorker.beta_stats_report works when no CpinRuntime."""
        from worker.port_worker import PortWorker
        from worker.rules import AutoRunConfig

        event_bus = _make_event_bus()
        config = AutoRunConfig()
        worker = PortWorker("COM25", event_bus, config)

        report = worker.beta_stats_report
        self.assertIn("NO_CPIN_RUNTIME=YES", report)


# ======================================================================
# Integration: Full Poll Cycle
# ======================================================================

class TestFullPollCycle(unittest.TestCase):
    """Integration tests for complete poll cycles."""

    def test_full_cycle_ready_stays_ready(self):
        """Full cycle: READY + READY → stays READY, no confirmation."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM30", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        self.assertEqual(rt.cpin_state, CpinState.READY)
        self.assertEqual(at_client.send_command.call_count, 1)
        self.assertEqual(rt._beta_stats.cpin_poll_count, 1)

    def test_full_cycle_ready_to_not_ready_confirmed(self):
        """Full cycle: READY + NOT_READY → confirmation → still NOT_READY → transition."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("NOT READY\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM31", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        self.assertEqual(rt.cpin_state, CpinState.NOT_READY)
        self.assertEqual(at_client.send_command.call_count, 2)
        self.assertEqual(rt._beta_stats.confirmation_poll_triggered, 1)
        self.assertEqual(rt._beta_stats.confirmation_poll_prevented, 0)

    def test_full_cycle_ready_to_not_ready_prevented(self):
        """Full cycle: READY + NOT_READY → confirmation → READY → IGNORE."""
        from worker.cpin_runtime import CpinRuntime

        resp_bad = MagicMock()
        resp_bad.raw = "NOT READY\r\nOK\r\n"
        resp_good = MagicMock()
        resp_good.raw = "READY\r\nOK\r\n"
        at_client = MagicMock()
        at_client.send_command.side_effect = [resp_bad, resp_good]

        event_bus = _make_event_bus()
        rt = CpinRuntime("COM32", at_client, event_bus)
        rt._current_state = CpinState.READY

        rt._running.set()
        rt._poll_once()

        self.assertEqual(rt.cpin_state, CpinState.READY)
        self.assertEqual(rt._beta_stats.confirmation_poll_prevented, 1)

    def test_full_cycle_ready_to_not_inserted(self):
        """Full cycle: READY + NOT_INSERTED → confirmation → still NOT_INSERTED → transition."""
        from worker.cpin_runtime import CpinRuntime

        at_client = _make_at_client("NOT INSERTED\r\nOK\r\n")
        event_bus = _make_event_bus()
        rt = CpinRuntime("COM33", at_client, event_bus)
        rt._current_state = CpinState.READY
        # Set removal count to threshold so confirmation triggers
        rt._removal_confirm_count = 2

        rt._running.set()
        rt._poll_once()

        self.assertEqual(rt.cpin_state, CpinState.NOT_INSERTED)
        self.assertEqual(at_client.send_command.call_count, 2)


if __name__ == "__main__":
    unittest.main()
