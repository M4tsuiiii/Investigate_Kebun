"""Tests for automation.state — AutomationState and AutomationStatus."""

import threading
import unittest

from automation.state import AutomationState, AutomationStatus


class TestAutomationStatus(unittest.TestCase):
    """Test AutomationStatus enum — port automation status."""

    def test_status_values(self) -> None:
        """Verify correct enum values."""
        self.assertEqual(AutomationStatus.IDLE.value, "IDLE")
        self.assertEqual(AutomationStatus.RUNNING.value, "RUNNING")
        self.assertEqual(AutomationStatus.STANDBY.value, "STANDBY")
        self.assertEqual(AutomationStatus.QUEUED.value, "QUEUED")
        self.assertEqual(AutomationStatus.RETRY_PENDING.value, "RETRY_PENDING")

    def test_status_member_count(self) -> None:
        """Verify expected member count."""
        self.assertEqual(len(AutomationStatus), 5)


class TestAutomationState(unittest.TestCase):
    """Test AutomationState — per-port thread-safe state tracking."""

    def test_initial_status_is_idle(self) -> None:
        """Verify new state starts as IDLE."""
        state = AutomationState(port="COM3")
        self.assertEqual(state.status, AutomationStatus.IDLE)

    def test_set_running(self) -> None:
        """Verify set_running transitions to RUNNING."""
        state = AutomationState(port="COM3")
        state.set_running("reactivate_full")
        self.assertEqual(state.status, AutomationStatus.RUNNING)
        self.assertEqual(state.current_workflow, "reactivate_full")

    def test_set_idle(self) -> None:
        """Verify set_idle transitions to IDLE and clears workflow."""
        state = AutomationState(port="COM3")
        state.set_running("check_data")
        state.set_idle()
        self.assertEqual(state.status, AutomationStatus.IDLE)
        self.assertEqual(state.current_workflow, "")

    def test_set_standby(self) -> None:
        """Verify set_standby transitions to STANDBY."""
        state = AutomationState(port="COM3")
        state.set_standby()
        self.assertEqual(state.status, AutomationStatus.STANDBY)
        self.assertEqual(state.current_workflow, "")

    def test_set_queued(self) -> None:
        """Verify set_queued transitions to QUEUED."""
        state = AutomationState(port="COM3")
        state.set_queued()
        self.assertEqual(state.status, AutomationStatus.QUEUED)

    def test_set_retry_pending(self) -> None:
        """Verify set_retry_pending transitions to RETRY_PENDING."""
        state = AutomationState(port="COM3")
        state.set_retry_pending()
        self.assertEqual(state.status, AutomationStatus.RETRY_PENDING)

    def test_is_idle_property(self) -> None:
        """Verify is_idle returns True only when IDLE."""
        state = AutomationState(port="COM3")
        self.assertTrue(state.is_idle)
        state.set_running("reactivate_full")
        self.assertFalse(state.is_idle)
        state.set_idle()
        self.assertTrue(state.is_idle)

    def test_is_running_property(self) -> None:
        """Verify is_running returns True only when RUNNING."""
        state = AutomationState(port="COM3")
        self.assertFalse(state.is_running)
        state.set_running("check_data")
        self.assertTrue(state.is_running)
        state.set_idle()
        self.assertFalse(state.is_running)

    def test_is_standby_property(self) -> None:
        """Verify is_standby returns True only when STANDBY."""
        state = AutomationState(port="COM3")
        self.assertFalse(state.is_standby)
        state.set_standby()
        self.assertTrue(state.is_standby)
        state.set_idle()
        self.assertFalse(state.is_standby)

    def test_current_workflow_tracks_running(self) -> None:
        """Verify current_workflow is set only for RUNNING status."""
        state = AutomationState(port="COM3")
        state.set_running("reactivate_fast")
        self.assertEqual(state.current_workflow, "reactivate_fast")
        state.set_idle()
        self.assertEqual(state.current_workflow, "")

    def test_record_result(self) -> None:
        """Verify record_result stores workflow outcome and grace."""
        state = AutomationState(port="COM3")
        state.record_result("reactivate_full", True, grace="2026-09-01")
        snap = state.snapshot()
        self.assertEqual(snap["last_workflow"], "reactivate_full")
        self.assertEqual(snap["last_success"], "True")
        self.assertEqual(snap["last_grace"], "2026-09-01")

    def test_record_result_without_grace(self) -> None:
        """Verify record_result without grace preserves old grace."""
        state = AutomationState(port="COM3")
        state.record_result("reactivate_full", True, grace="2026-09-01")
        state.record_result("check_data", False)
        snap = state.snapshot()
        self.assertEqual(snap["last_grace"], "2026-09-01")

    def test_snapshot_contains_all_fields(self) -> None:
        """Verify snapshot returns all expected keys."""
        state = AutomationState(port="COM3")
        snap = state.snapshot()
        expected_keys = {
            "port", "status", "current_workflow", "last_workflow",
            "last_success", "last_grace", "retry_count",
        }
        self.assertEqual(set(snap.keys()), expected_keys)
        self.assertEqual(snap["port"], "COM3")

    def test_thread_safety(self) -> None:
        """Verify concurrent state updates do not corrupt state."""
        state = AutomationState(port="COM3")
        errors: list[bool] = []

        def updater(n: int) -> None:
            try:
                for _ in range(100):
                    state.set_running(f"workflow_{n}")
                    state.set_idle()
                    state.set_standby()
                    state.set_queued()
                    state.set_retry_pending()
            except Exception:
                errors.append(True)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertFalse(errors)
        # After all updates, status should be one of the valid enum values
        self.assertIsInstance(state.status, AutomationStatus)

    def test_port_property(self) -> None:
        """Verify port property returns constructor argument."""
        state = AutomationState(port="COM5")
        self.assertEqual(state.port, "COM5")


if __name__ == "__main__":
    unittest.main()
