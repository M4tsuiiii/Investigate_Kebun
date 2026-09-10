"""Tests for worker/mass_action.py — coordinated mass operations across ports."""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.domain.enums import PortStatus
from worker.mass_action import MassAction, MassActionProgress


class TestMassActionProgress(unittest.TestCase):
    """Tests for MassActionProgress tracking class."""

    def setUp(self):
        """Create fresh MassActionProgress for each test."""
        self.progress = MassActionProgress("cek_nomor", 3)

    def test_record_success_increments_completed_and_success(self):
        """record_success should increment both completed and success counters."""
        self.progress.record_success("COM1")
        self.assertEqual(self.progress.completed, 1)
        self.assertEqual(self.progress.success, 1)
        self.assertEqual(self.progress.failed, 0)

    def test_record_failure_increments_completed_and_failed(self):
        """record_failure should increment both completed and failed counters."""
        self.progress.record_failure("COM1", "timeout")
        self.assertEqual(self.progress.completed, 1)
        self.assertEqual(self.progress.failed, 1)
        self.assertEqual(self.progress.success, 0)

    def test_snapshot_returns_correct_data(self):
        """snapshot should return a dict with all progress fields."""
        self.progress.record_success("COM1")
        self.progress.record_failure("COM2", "error")
        snap = self.progress.snapshot()

        self.assertEqual(snap["action_name"], "cek_nomor")
        self.assertEqual(snap["total"], 3)
        self.assertEqual(snap["completed"], 2)
        self.assertEqual(snap["success"], 1)
        self.assertEqual(snap["failed"], 1)
        self.assertFalse(snap["is_complete"])
        self.assertIn("elapsed", snap)
        self.assertIn("port_results", snap)
        self.assertEqual(snap["port_results"]["COM1"], "success")
        self.assertEqual(snap["port_results"]["COM2"], "failed: error")

    def test_is_complete_when_completed_equals_total(self):
        """is_complete should be True when completed count equals total."""
        self.progress.record_success("COM1")
        self.progress.record_success("COM2")
        self.assertFalse(self.progress.is_complete)
        self.progress.record_success("COM3")
        self.assertTrue(self.progress.is_complete)

    def test_is_complete_false_when_under_total(self):
        """is_complete should be False when completed count is less than total."""
        self.progress.record_success("COM1")
        self.assertFalse(self.progress.is_complete)

    def test_multiple_record_success(self):
        """Multiple record_success calls should accumulate correctly."""
        for i in range(3):
            self.progress.record_success(f"COM{i + 1}")
        self.assertEqual(self.progress.completed, 3)
        self.assertEqual(self.progress.success, 3)
        self.assertEqual(self.progress.failed, 0)
        self.assertTrue(self.progress.is_complete)

    def test_mixed_success_and_failure(self):
        """Mixed success and failure records should track independently."""
        self.progress.record_success("COM1")
        self.progress.record_failure("COM2", "modem offline")
        self.progress.record_success("COM3")
        self.assertEqual(self.progress.completed, 3)
        self.assertEqual(self.progress.success, 2)
        self.assertEqual(self.progress.failed, 1)
        self.assertTrue(self.progress.is_complete)

    def test_snapshot_port_results_are_copy(self):
        """snapshot should return a copy of port_results, not the internal dict."""
        self.progress.record_success("COM1")
        snap = self.progress.snapshot()
        snap["port_results"]["COM1"] = "modified"
        snap2 = self.progress.snapshot()
        self.assertEqual(snap2["port_results"]["COM1"], "success")

    def test_action_name_property(self):
        """action_name property should return the action name passed at init."""
        self.assertEqual(self.progress.action_name, "cek_nomor")

    def test_total_property(self):
        """total property should return the total passed at init."""
        self.assertEqual(self.progress.total, 3)

    def test_elapsed_is_nonnegative(self):
        """elapsed property should return a non-negative float."""
        self.assertGreaterEqual(self.progress.elapsed, 0.0)

    def test_record_failure_default_reason(self):
        """record_failure should accept empty reason string."""
        self.progress.record_failure("COM1")
        snap = self.progress.snapshot()
        self.assertEqual(snap["port_results"]["COM1"], "failed: ")

    def test_port_results_keyed_by_port_id(self):
        """port_results dict should be keyed by port_id string."""
        self.progress.record_success("COM1")
        self.progress.record_failure("COM2", "err")
        snap = self.progress.snapshot()
        self.assertIn("COM1", snap["port_results"])
        self.assertIn("COM2", snap["port_results"])


class TestMassActionGetEligiblePorts(unittest.TestCase):
    """Tests for MassAction.get_eligible_ports filtering logic."""

    def setUp(self):
        """Create fresh MassAction with mock event bus."""
        self.event_bus = MagicMock()
        self.mass_action = MassAction(self.event_bus)

    def _make_worker(self, is_alive=True, modem_online=True):
        """Helper to create a mock worker with given flags."""
        worker = MagicMock()
        worker.is_alive = is_alive
        worker.modem_online = modem_online
        return worker

    def test_filters_by_is_alive(self):
        """get_eligible_ports should exclude workers where is_alive is False."""
        workers = {
            "COM1": self._make_worker(is_alive=True, modem_online=True),
            "COM2": self._make_worker(is_alive=False, modem_online=True),
        }
        eligible = self.mass_action.get_eligible_ports(workers)
        self.assertEqual(eligible, ["COM1"])

    def test_filters_by_modem_online(self):
        """get_eligible_ports should exclude workers where modem_online is False."""
        workers = {
            "COM1": self._make_worker(is_alive=True, modem_online=True),
            "COM2": self._make_worker(is_alive=True, modem_online=False),
        }
        eligible = self.mass_action.get_eligible_ports(workers)
        self.assertEqual(eligible, ["COM1"])

    def test_returns_empty_when_no_eligible(self):
        """get_eligible_ports should return empty list when no workers qualify."""
        workers = {
            "COM1": self._make_worker(is_alive=False, modem_online=False),
            "COM2": self._make_worker(is_alive=True, modem_online=False),
        }
        eligible = self.mass_action.get_eligible_ports(workers)
        self.assertEqual(eligible, [])

    def test_returns_all_when_all_eligible(self):
        """get_eligible_ports should return all port IDs when all qualify."""
        workers = {
            "COM1": self._make_worker(is_alive=True, modem_online=True),
            "COM2": self._make_worker(is_alive=True, modem_online=True),
            "COM3": self._make_worker(is_alive=True, modem_online=True),
        }
        eligible = self.mass_action.get_eligible_ports(workers)
        self.assertEqual(eligible, ["COM1", "COM2", "COM3"])

    def test_returns_empty_for_empty_workers(self):
        """get_eligible_ports should return empty list for empty input."""
        eligible = self.mass_action.get_eligible_ports({})
        self.assertEqual(eligible, [])


class TestMassActionStartMassNumberCheck(unittest.TestCase):
    """Tests for MassAction.start_mass_number_check."""

    def setUp(self):
        """Create fresh MassAction with mock event bus."""
        self.event_bus = MagicMock()
        self.mass_action = MassAction(self.event_bus)

    def _make_worker(self, port_name, is_alive=True, modem_online=True, status=PortStatus.READY):
        """Helper to create a mock worker."""
        worker = MagicMock()
        worker.is_alive = is_alive
        worker.modem_online = modem_online
        worker.state.status = status
        worker.state.status_detail = ""
        return worker

    def test_creates_thread_and_publishes_events(self):
        """start_mass_number_check should create a daemon thread and set progress."""
        worker = self._make_worker("COM1", status=PortStatus.BUSY)

        def complete_later():
            time.sleep(0.3)
            worker.state.status = PortStatus.READY

        threading.Thread(target=complete_later, daemon=True).start()
        workers = {"COM1": worker}

        self.mass_action.start_mass_number_check(workers)

        self.assertIsNotNone(self.mass_action._thread)
        self.assertTrue(self.mass_action._thread.daemon)
        self.assertEqual(self.mass_action._thread.name, "MassCekNomor")
        self.assertIsNotNone(self.mass_action.progress)
        self.mass_action._thread.join(timeout=5.0)

    def test_no_eligible_ports_publishes_complete(self):
        """start_mass_number_check with no eligible ports publishes complete event."""
        worker = self._make_worker("COM1", is_alive=False)
        workers = {"COM1": worker}

        self.mass_action.start_mass_number_check(workers)

        self.event_bus.publish.assert_any_call("mass.action.complete", {
            "action": "cek_nomor",
            "total": 0,
            "success": 0,
            "failed": 0,
            "message": "No eligible ports",
        })

    def test_does_not_start_if_already_running(self):
        """start_mass_number_check should return early if already running."""
        worker = self._make_worker("COM1", status=PortStatus.BUSY)
        workers = {"COM1": worker}

        self.mass_action.start_mass_number_check(workers)
        self.assertTrue(self.mass_action.is_running)
        second_event_bus = MagicMock()
        self.mass_action._event_bus = second_event_bus
        self.mass_action.start_mass_number_check(workers)

        second_event_bus.publish.assert_not_called()

    def test_is_running_true_during_execution(self):
        """is_running should be True while the mass action thread is alive."""
        worker = self._make_worker("COM1", status=PortStatus.BUSY)

        def complete_later():
            time.sleep(0.5)
            worker.state.status = PortStatus.READY

        threading.Thread(target=complete_later, daemon=True).start()
        workers = {"COM1": worker}

        self.mass_action.start_mass_number_check(workers)
        self.assertTrue(self.mass_action.is_running)
        self.mass_action._thread.join(timeout=5.0)

    def test_waits_for_worker_completion(self):
        """start_mass_number_check should wait for worker to finish before recording."""
        worker = self._make_worker("COM1", status=PortStatus.BUSY)

        def complete_later():
            time.sleep(0.2)
            worker.state.status = PortStatus.READY

        threading.Thread(target=complete_later, daemon=True).start()
        workers = {"COM1": worker}

        self.mass_action.start_mass_number_check(workers)
        self.mass_action._thread.join(timeout=5.0)

        self.assertFalse(self.mass_action.is_running)
        publish_calls = [
            c for c in self.event_bus.publish.call_args_list
            if c[0][0] == "mass.action.complete"
        ]
        self.assertTrue(len(publish_calls) > 0)
        final_data = publish_calls[0][0][1]
        self.assertEqual(final_data["success"], 1)
        self.assertEqual(final_data["total"], 1)

    def test_records_failure_on_exception(self):
        """start_mass_number_check should record failure if worker raises exception."""
        worker = self._make_worker("COM1")
        worker.set_single_action.side_effect = RuntimeError("modem crash")
        workers = {"COM1": worker}

        self.mass_action.start_mass_number_check(workers)
        self.mass_action._thread.join(timeout=5.0)

        publish_calls = [
            c for c in self.event_bus.publish.call_args_list
            if c[0][0] == "mass.action.complete"
        ]
        self.assertTrue(len(publish_calls) > 0)
        final_data = publish_calls[0][0][1]
        self.assertEqual(final_data["failed"], 1)


class TestMassActionStartMassReactivation(unittest.TestCase):
    """Tests for MassAction.start_mass_reactivation."""

    def setUp(self):
        """Create fresh MassAction with mock event bus."""
        self.event_bus = MagicMock()
        self.mass_action = MassAction(self.event_bus)

    def _make_worker(self, port_name, is_alive=True, modem_online=True, status=PortStatus.READY):
        """Helper to create a mock worker."""
        worker = MagicMock()
        worker.is_alive = is_alive
        worker.modem_online = modem_online
        worker.state.status = status
        worker.state.status_detail = ""
        return worker

    def test_creates_thread_and_publishes_events(self):
        """start_mass_reactivation should create a daemon thread named MassReaktivasi."""
        worker = self._make_worker("COM1", status=PortStatus.BUSY)

        def complete_later():
            time.sleep(0.3)
            worker.state.status = PortStatus.READY

        threading.Thread(target=complete_later, daemon=True).start()
        workers = {"COM1": worker}

        self.mass_action.start_mass_reactivation(workers)

        self.assertIsNotNone(self.mass_action._thread)
        self.assertTrue(self.mass_action._thread.daemon)
        self.assertEqual(self.mass_action._thread.name, "MassReaktivasi")
        self.mass_action._thread.join(timeout=5.0)

    def test_no_eligible_ports_publishes_complete(self):
        """start_mass_reactivation with no eligible ports publishes complete event."""
        worker = self._make_worker("COM1", is_alive=False)
        workers = {"COM1": worker}

        self.mass_action.start_mass_reactivation(workers)

        self.event_bus.publish.assert_any_call("mass.action.complete", {
            "action": "reaktivasi",
            "total": 0,
            "success": 0,
            "failed": 0,
            "message": "No eligible ports",
        })

    def test_does_not_start_if_already_running(self):
        """start_mass_reactivation should return early if already running."""
        worker = self._make_worker("COM1", status=PortStatus.BUSY)
        workers = {"COM1": worker}

        self.mass_action.start_mass_reactivation(workers)
        self.assertTrue(self.mass_action.is_running)
        second_event_bus = MagicMock()
        self.mass_action._event_bus = second_event_bus
        self.mass_action.start_mass_reactivation(workers)

        second_event_bus.publish.assert_not_called()


class TestMassActionIsRunning(unittest.TestCase):
    """Tests for MassAction.is_running property."""

    def setUp(self):
        """Create fresh MassAction with mock event bus."""
        self.event_bus = MagicMock()
        self.mass_action = MassAction(self.event_bus)

    def _make_worker(self, is_alive=True, modem_online=True, status=PortStatus.READY):
        """Helper to create a mock worker."""
        worker = MagicMock()
        worker.is_alive = is_alive
        worker.modem_online = modem_online
        worker.state.status = status
        worker.state.status_detail = ""
        return worker

    def test_is_running_false_initially(self):
        """is_running should be False before any action is started."""
        self.assertFalse(self.mass_action.is_running)

    def test_is_running_true_during_execution(self):
        """is_running should be True while a mass action thread is alive."""
        worker = self._make_worker(status=PortStatus.BUSY)

        def complete_later():
            time.sleep(0.5)
            worker.state.status = PortStatus.READY

        threading.Thread(target=complete_later, daemon=True).start()
        self.mass_action.start_mass_number_check({"COM1": worker})
        self.assertTrue(self.mass_action.is_running)
        self.mass_action._thread.join(timeout=5.0)

    def test_is_running_false_after_completion(self):
        """is_running should be False after the thread finishes."""
        worker = self._make_worker(status=PortStatus.READY)
        workers = {"COM1": worker}

        self.mass_action.start_mass_number_check(workers)
        self.mass_action._thread.join(timeout=5.0)
        self.assertFalse(self.mass_action.is_running)


class TestMassActionWaitForCompletion(unittest.TestCase):
    """Tests for MassAction._wait_for_completion."""

    def setUp(self):
        """Create fresh MassAction with mock event bus."""
        self.event_bus = MagicMock()
        self.mass_action = MassAction(self.event_bus)

    def _make_worker(self, status=PortStatus.BUSY):
        """Helper to create a mock worker with a mutable state."""
        worker = MagicMock()
        worker.state.status = status
        return worker

    def test_exits_on_status_change(self):
        """_wait_for_completion should exit when worker status is no longer BUSY."""
        worker = self._make_worker(status=PortStatus.BUSY)

        def change_status():
            time.sleep(0.1)
            worker.state.status = PortStatus.READY

        threading.Thread(target=change_status, daemon=True).start()
        start = time.time()
        self.mass_action._wait_for_completion(worker, timeout=5.0)
        elapsed = time.time() - start

        self.assertLess(elapsed, 2.0)

    def test_timeout_exits(self):
        """_wait_for_completion should exit after timeout even if still BUSY."""
        worker = self._make_worker(status=PortStatus.BUSY)
        start = time.time()
        self.mass_action._wait_for_completion(worker, timeout=0.3)
        elapsed = time.time() - start

        self.assertGreaterEqual(elapsed, 0.2)
        self.assertLess(elapsed, 2.0)

    def test_exits_immediately_when_not_busy(self):
        """_wait_for_completion should return immediately if worker is not BUSY."""
        worker = self._make_worker(status=PortStatus.READY)
        start = time.time()
        self.mass_action._wait_for_completion(worker, timeout=5.0)
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.5)

    def test_exits_on_checking_status(self):
        """_wait_for_completion should exit when status changes to non-BUSY."""
        worker = self._make_worker(status=PortStatus.CHECKING)

        def change_status():
            time.sleep(0.1)
            worker.state.status = PortStatus.IDLE

        threading.Thread(target=change_status, daemon=True).start()
        start = time.time()
        self.mass_action._wait_for_completion(worker, timeout=5.0)
        elapsed = time.time() - start
        self.assertLess(elapsed, 2.0)


class TestMassActionProgressThreadSafety(unittest.TestCase):
    """Thread safety tests for MassActionProgress."""

    def test_concurrent_record_success(self):
        """Concurrent record_success should not lose increments."""
        progress = MassActionProgress("cek_nomor", 100)
        barrier = threading.Barrier(10)

        def record():
            barrier.wait()
            for _ in range(10):
                progress.record_success("COM")

        threads = [threading.Thread(target=record) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(progress.completed, 100)
        self.assertEqual(progress.success, 100)

    def test_concurrent_record_failure(self):
        """Concurrent record_failure should not lose increments."""
        progress = MassActionProgress("cek_nomor", 50)
        barrier = threading.Barrier(5)

        def record():
            barrier.wait()
            for _ in range(10):
                progress.record_failure("COM", "err")

        threads = [threading.Thread(target=record) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(progress.completed, 50)
        self.assertEqual(progress.failed, 50)

    def test_concurrent_snapshot_reads(self):
        """Concurrent snapshot reads should not raise exceptions."""
        progress = MassActionProgress("cek_nomor", 5)
        progress.record_success("COM1")
        progress.record_success("COM2")

        barrier = threading.Barrier(10)
        results = []

        def read_snapshot():
            barrier.wait()
            results.append(progress.snapshot())

        threads = [threading.Thread(target=read_snapshot) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(len(results), 10)
        for snap in results:
            self.assertEqual(snap["completed"], 2)


if __name__ == "__main__":
    unittest.main()
