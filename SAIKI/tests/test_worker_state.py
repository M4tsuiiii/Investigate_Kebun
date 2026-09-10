"""Tests for PortWorkerState — thread-safe per-port mutable state."""

import unittest
import threading

from worker.state import PortWorkerState
from app.domain.enums import CpinState, PortStatus
from app.domain.constants import CPIN_UNKNOWN_THRESHOLD, CPIN_CHECKING_THRESHOLD


class TestPortWorkerState(unittest.TestCase):
    """Test PortWorkerState RLock thread safety and atomic operations."""

    def setUp(self):
        """Create fresh state before each test."""
        self.state = PortWorkerState(port_name="COM3")

    def test_initial_state(self):
        """Verify initial state has correct defaults."""
        self.assertEqual(self.state.port_name, "COM3")
        self.assertFalse(self.state.consume_auto_run())
        self.assertFalse(self.state.consume_force_retry())
        self.assertFalse(self.state.consume_reset())
        self.assertIsNone(self.state.consume_single_action())

    def test_consume_auto_run_atomic(self):
        """Verify consume_auto_run reads and clears atomically."""
        self.state.queue_auto_run()
        self.assertTrue(self.state.consume_auto_run())
        self.assertFalse(self.state.consume_auto_run())

    def test_consume_single_action_atomic(self):
        """Verify consume_single_action reads and clears atomically."""
        self.state.set_single_action("cek_nomor")
        result = self.state.consume_single_action()
        self.assertEqual(result, "cek_nomor")
        self.assertIsNone(self.state.consume_single_action())

    def test_consume_force_retry_atomic(self):
        """Verify consume_force_retry reads and clears atomically."""
        self.state.set_force_retry()
        self.assertTrue(self.state.consume_force_retry())
        self.assertFalse(self.state.consume_force_retry())

    def test_consume_reset_atomic(self):
        """Verify consume_reset reads and clears atomically."""
        self.state.request_reset()
        self.assertTrue(self.state.consume_reset())
        self.assertFalse(self.state.consume_reset())

    def test_increment_unknown_threshold(self):
        """Verify increment_unknown returns True at threshold."""
        for _ in range(CPIN_UNKNOWN_THRESHOLD - 1):
            self.assertFalse(self.state.increment_unknown())
        self.assertTrue(self.state.increment_unknown())

    def test_increment_checking_threshold(self):
        """Verify increment_checking returns True at threshold."""
        for _ in range(CPIN_CHECKING_THRESHOLD - 1):
            self.assertFalse(self.state.increment_checking())
        self.assertTrue(self.state.increment_checking())

    def test_reset_cpin_counters(self):
        """Verify reset_cpin_counters clears all CPIN counters."""
        for _ in range(CPIN_UNKNOWN_THRESHOLD):
            self.state.increment_unknown()
        self.state.reset_cpin_counters()
        snap = self.state.snapshot()
        self.assertEqual(snap["unknown_failure_count"], 0)
        self.assertEqual(snap["cpin_failure_count"], 0)

    def test_request_reset_clears_all_pending(self):
        """Verify request_reset clears all pending actions (HR-010)."""
        self.state.queue_auto_run()
        self.state.set_single_action("cek_nomor")
        self.state.set_force_retry()
        self.state.request_reset()
        self.assertTrue(self.state.consume_reset())
        self.assertFalse(self.state.consume_auto_run())
        self.assertIsNone(self.state.consume_single_action())
        self.assertFalse(self.state.consume_force_retry())

    def test_snapshot_atomicity(self):
        """Verify snapshot returns consistent state."""
        self.state.queue_auto_run()
        self.state.set_force_retry()
        snap = self.state.snapshot()
        self.assertTrue(snap["pending_auto_run"])
        self.assertTrue(snap["force_retry"])
        self.assertEqual(snap["port_name"], "COM3")

    def test_rlock_thread_safety(self):
        """Verify concurrent access does not corrupt state."""
        errors = []

        def worker():
            try:
                for _ in range(500):
                    self.state.queue_auto_run()
                    self.state.consume_auto_run()
                    self.state.increment_unknown()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_concurrent_snapshot_and_mutation(self):
        """Verify snapshot during concurrent mutation does not crash."""
        errors = []

        def mutate():
            try:
                for _ in range(200):
                    self.state.queue_auto_run()
                    self.state.consume_auto_run()
                    self.state.increment_unknown()
            except Exception as e:
                errors.append(e)

        def snapshotter():
            try:
                for _ in range(200):
                    self.state.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mutate) for _ in range(2)]
        threads += [threading.Thread(target=snapshotter) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_set_cpin_state(self):
        """Verify set_cpin_state updates state and returns change flag."""
        self.assertTrue(self.state.set_cpin_state(CpinState.READY))
        self.assertEqual(self.state.cpin_state, CpinState.READY)
        self.assertFalse(self.state.set_cpin_state(CpinState.READY))

    def test_set_status(self):
        """Verify set_status updates port status."""
        self.state.set_status(PortStatus.BUSY, "Processing")
        self.assertEqual(self.state.status, PortStatus.BUSY)
        self.assertEqual(self.state.status_detail, "Processing")

    def test_card_data_operations(self):
        """Verify set_card_data and clear_card_data."""
        self.state.set_card_data(nomor="08123", nik="3201", kk="5678", masa_aktif="2025-12")
        snap = self.state.snapshot()
        self.assertEqual(snap["nomor"], "08123")
        self.assertEqual(snap["nik"], "3201")
        self.state.clear_card_data()
        snap = self.state.snapshot()
        self.assertEqual(snap["nomor"], "-")

    def test_card_cycle_operations(self):
        """Verify require_card_cycle and clear_card_cycle."""
        self.state.require_card_cycle()
        snap = self.state.snapshot()
        self.assertTrue(snap["awaiting_card_cycle"])
        self.state.clear_card_cycle()
        snap = self.state.snapshot()
        self.assertFalse(snap["awaiting_card_cycle"])

    def test_prompt_recovery(self):
        """Verify prompt recovery counter increments and resets."""
        self.assertFalse(self.state.increment_prompt_recovery())
        self.assertTrue(self.state.increment_prompt_recovery())
        self.state.reset_prompt_recovery()
        snap = self.state.snapshot()
        self.assertEqual(snap["prompt_recovery_count"], 0)

    def test_set_current_baud(self):
        """Verify set_current_baud updates baud rate."""
        self.state.set_current_baud(115200)
        self.assertEqual(self.state.current_baud, 115200)


if __name__ == "__main__":
    unittest.main()
