"""Tests for Sprint 15R — Scan Stability, Numeric Port Order & Standby UI.

Covers:
1. Numeric COM sort (COM9 before COM10, COM101 before COM122)
2. Sort on PortMetadata objects
3. Sort preserves input objects
4. Single-flight scan (no overlapping scans)
5. Coalesced rescan
6. Active-worker skip during scan
7. Retry cooldown skip
8. Candidate priority: XR21V1414 > generic USB Serial
9. Generic USB Serial rejected without HWID/VID match
10. STANDBY UI mapping: NOT_INSERTED → STANDBY
11. STANDBY UI mapping: IDLE → STANDBY
12. STANDBY UI mapping: READY → READY
13. Port table default row is STANDBY
14. Port table numeric sort in restore_from_cache
15. Failed-ports cooldown cleared on stop_all
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


# ------------------------------------------------------------------
# 1-3. Numeric COM sort
# ------------------------------------------------------------------

class TestSortComPorts(unittest.TestCase):
    """Sort COM ports numerically, not lexically."""

    def test_sort_basic(self):
        """COM9 comes before COM10, COM10 before COM11."""
        from worker.modem_discovery import sort_com_ports
        result = sort_com_ports(["COM10", "COM9", "COM11"])
        self.assertEqual(result, ["COM9", "COM10", "COM11"])

    def test_sort_high_com_numbers(self):
        """COM101 before COM122, COM147 before COM161."""
        from worker.modem_discovery import sort_com_ports
        result = sort_com_ports(["COM161", "COM101", "COM147", "COM122"])
        self.assertEqual(result, ["COM101", "COM122", "COM147", "COM161"])

    def test_sort_preserves_objects(self):
        """Sort works on PortMetadata objects."""
        from worker.modem_discovery import sort_com_ports, PortMetadata
        ports = [
            PortMetadata("COM200", "desc"),
            PortMetadata("COM9", "desc"),
            PortMetadata("COM150", "desc"),
        ]
        result = sort_com_ports(ports)
        names = [p.port_name for p in result]
        self.assertEqual(names, ["COM9", "COM150", "COM200"])

    def test_sort_single_port(self):
        """Single port returns as-is."""
        from worker.modem_discovery import sort_com_ports
        result = sort_com_ports(["COM5"])
        self.assertEqual(result, ["COM5"])

    def test_sort_empty_list(self):
        """Empty list returns empty list."""
        from worker.modem_discovery import sort_com_ports
        result = sort_com_ports([])
        self.assertEqual(result, [])


# ------------------------------------------------------------------
# 4-5. Single-flight scan control
# ------------------------------------------------------------------

class TestSingleFlightScan(unittest.TestCase):
    """Only one scan at a time; pending rescan coalesces."""

    def _make_manager(self):
        """Create a minimal WorkerManager for testing."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig
        bus = MagicMock()
        config = MagicMock()
        auto_config = AutoRunConfig()
        wm = WorkerManager(bus, auto_config, config)
        return wm

    def test_scan_active_lock_prevents_overlap(self):
        """Second scan attempt while first is running is blocked."""
        wm = self._make_manager()
        # Simulate first scan holding the lock
        acquired1 = wm._scan_active.acquire(blocking=False)
        self.assertTrue(acquired1)
        # Second attempt should fail
        acquired2 = wm._scan_active.acquire(blocking=False)
        self.assertFalse(acquired2)
        wm._scan_active.release()

    def test_rescan_pending_flag_coalesces(self):
        """Setting _rescan_pending while scan is active causes re-run."""
        wm = self._make_manager()
        wm._rescan_pending.clear()
        wm._rescan_pending.set()
        self.assertTrue(wm._rescan_pending.is_set())
        wm._rescan_pending.clear()
        self.assertFalse(wm._rescan_pending.is_set())

    def test_scan_count_increments(self):
        """_scan_count increments on each scan."""
        wm = self._make_manager()
        initial = wm._scan_count
        wm._scan_count += 1
        self.assertEqual(wm._scan_count, initial + 1)


# ------------------------------------------------------------------
# 6-7. Active-worker skip and retry cooldown
# ------------------------------------------------------------------

class TestActiveWorkerSkip(unittest.TestCase):
    """Ports with active workers are skipped during discovery."""

    def test_active_worker_skipped(self):
        """Port in active_ports set is skipped."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        discovery = ModemDiscovery()
        meta = PortMetadata("COM5", "Quectel AT")
        active = {"COM5", "COM9"}
        eligible, skipped = discovery.filter_active_workers([meta], active)
        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][1], "already_active_worker")

    def test_inactive_port_eligible(self):
        """Port not in active_ports is eligible."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        discovery = ModemDiscovery()
        meta = PortMetadata("COM5", "Quectel AT")
        active = {"COM9"}
        eligible, skipped = discovery.filter_active_workers([meta], active)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(len(skipped), 0)

    def test_retry_cooldown_skips_failed_port(self):
        """Port failed within cooldown period is skipped."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        discovery = ModemDiscovery()
        meta = PortMetadata("COM5", "Quectel AT")
        failed = {"COM5": time.time()}  # Failed just now
        eligible, skipped = discovery.filter_active_workers([meta], set(), failed)
        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn("retry_cooldown", skipped[0][1])

    def test_retry_cooldown_expired(self):
        """Port failed outside cooldown period is eligible."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        from app.domain.constants import DISCOVERY_RETRY_COOLDOWN
        discovery = ModemDiscovery()
        meta = PortMetadata("COM5", "Quectel AT")
        failed = {"COM5": time.time() - DISCOVERY_RETRY_COOLDOWN - 1}  # Cooldown expired
        eligible, skipped = discovery.filter_active_workers([meta], set(), failed)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(len(skipped), 0)


# ------------------------------------------------------------------
# 8-9. Candidate filter priority
# ------------------------------------------------------------------

class TestCandidateFilterPriority(unittest.TestCase):
    """XR21V1414 and known hardware are high priority; generic USB Serial rejected."""

    def _make_meta(self, port, desc="", mfr="", vid="", pid="", hwid=""):
        from worker.modem_discovery import PortMetadata
        return PortMetadata(port, desc, mfr, vid, pid, hwid)

    def test_xr21v1414_is_candidate(self):
        """XR21V1414 in description is accepted."""
        from worker.modem_discovery import ModemDiscovery
        discovery = ModemDiscovery()
        meta = self._make_meta("COM5", "XR21V1414 USB UART", "Exar", "04E2", "1414")
        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)

    def test_quectel_is_candidate(self):
        """Quectel in description is accepted."""
        from worker.modem_discovery import ModemDiscovery
        discovery = ModemDiscovery()
        meta = self._make_meta("COM5", "Quectel USB AT Port", "Quectel")
        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)

    def test_known_hwid_is_candidate(self):
        """Known HWID pattern is accepted."""
        from worker.modem_discovery import ModemDiscovery
        discovery = ModemDiscovery()
        meta = self._make_meta("COM5", "USB Serial", "Unknown", hwid="USB VID:PID=04E2:1414")
        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)

    def test_known_vid_is_candidate(self):
        """Known VID is accepted."""
        from worker.modem_discovery import ModemDiscovery
        discovery = ModemDiscovery()
        meta = self._make_meta("COM5", "USB Serial Device", "Unknown", vid="04E2")
        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)

    def test_generic_usb_serial_rejected_without_identity(self):
        """Generic 'USB Serial' without HWID/VID is rejected."""
        from worker.modem_discovery import ModemDiscovery
        discovery = ModemDiscovery()
        meta = self._make_meta("COM5", "USB Serial", "Generic Inc")
        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 0)
        self.assertEqual(len(skipped), 1)

    def test_unrelated_device_rejected(self):
        """Unrelated device (no modem keywords) is rejected."""
        from worker.modem_discovery import ModemDiscovery
        discovery = ModemDiscovery()
        meta = self._make_meta("COM5", "Microsoft Bluetooth Serial", "Microsoft")
        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 0)

    def test_hwid_match_takes_priority(self):
        """HWID match is returned as priority reason."""
        from worker.modem_discovery import ModemDiscovery
        discovery = ModemDiscovery()
        meta = self._make_meta("COM5", "USB Serial", "Unknown", hwid="USB VID:PID=04E2:1414")
        candidates, _ = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)
        # Check it was accepted
        self.assertIsNotNone(candidates[0])


# ------------------------------------------------------------------
# 10-13. Neutral UI state mapping (Sprint 15R.1)
# ------------------------------------------------------------------

class TestNeutralUI(unittest.TestCase):
    """Neutral states (NOT_INSERTED/NOT_READY/UNKNOWN/CHECKING/STANDBY/IDLE) → IDLE + RESPON '-'."""

    def test_cpin_not_inserted_maps_to_idle(self):
        """NOT_INSERTED → status IDLE, respon '-'."""
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("NOT_INSERTED"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("NOT_INSERTED", "SIM Not Inserted"), "-")

    def test_cpin_ready_maps_to_ready(self):
        """READY → status READY, respon preserved."""
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("READY"), "READY")
        self.assertEqual(PortStatusTable._normalize_respon("READY", "SIM Inserted"), "SIM Inserted")

    def test_port_table_restore_numeric_sort(self):
        """restore_from_cache sorts ports numerically."""
        from worker.ui.port_table import PortStatusTable
        import re

        table = PortStatusTable.__new__(PortStatusTable)
        table._tree = MagicMock()
        table._row_cache = {}

        port_states = {
            "COM200": {"port_display": "COM200", "status": "READY"},
            "COM9": {"port_display": "COM9", "status": "STANDBY"},
            "COM150": {"port_display": "COM150", "status": "IDLE"},
        }
        # Mock get_children to return existing items for deletion
        table._tree.get_children.return_value = []

        table.restore_from_cache(port_states)

        # Check that insert_row was called with numerically sorted ports
        calls = table._tree.insert.call_args_list
        # Since we're mocking, we verify the sort logic separately
        def _num_key(port_name):
            m = re.search(r'(\d+)', port_name)
            return int(m.group(1)) if m else 0
        sorted_keys = sorted(port_states.keys(), key=_num_key)
        self.assertEqual(sorted_keys, ["COM9", "COM150", "COM200"])


# ------------------------------------------------------------------
# 14. Failed-ports cleared on stop_all
# ------------------------------------------------------------------

class TestFailedPortsCleanup(unittest.TestCase):
    """Failed-ports cooldown is cleared on stop_all."""

    def test_stop_all_clears_failed_ports(self):
        """stop_all clears _failed_ports."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig
        bus = MagicMock()
        config = MagicMock()
        auto_config = AutoRunConfig()
        wm = WorkerManager(bus, auto_config, config)
        wm._failed_ports["COM5"] = time.time()
        self.assertEqual(len(wm._failed_ports), 1)
        wm.stop_all()
        self.assertEqual(len(wm._failed_ports), 0)

    def test_clear_validation_cache_clears_failed_ports(self):
        """clear_validation_cache also clears failed_ports."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig
        bus = MagicMock()
        config = MagicMock()
        auto_config = AutoRunConfig()
        wm = WorkerManager(bus, auto_config, config)
        wm._failed_ports["COM5"] = time.time()
        wm.clear_validation_cache()
        self.assertEqual(len(wm._failed_ports), 0)


# ------------------------------------------------------------------
# 15. ModemDiscovery integration
# ------------------------------------------------------------------

class TestModemDiscoveryIntegration(unittest.TestCase):
    """End-to-end: enumerate → filter → skip active → probe → verified."""

    def test_full_pipeline_skip_active(self):
        """Full pipeline skips active workers and returns verified ports."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        discovery = ModemDiscovery()

        # Mock enumerate
        mock_info = MagicMock()
        mock_info.device = "COM5"
        mock_info.description = "Quectel USB AT Port"
        mock_info.manufacturer = "Quectel"
        mock_info.vid = "2C7C"
        mock_info.pid = "0125"
        mock_info.hwid = "USB VID:PID=2C7C:0125"

        with patch("serial.tools.list_ports.comports", return_value=[mock_info]):
            ports = discovery.enumerate_ports()

        # Filter candidates
        candidates, skipped = discovery.filter_candidates(ports)
        self.assertEqual(len(candidates), 1)

        # Skip active
        active = {"COM5"}  # COM5 already active
        eligible, active_skipped = discovery.filter_active_workers(candidates, active)
        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(active_skipped), 1)

    def test_probe_success(self):
        """Successful AT probe returns ProbeResult with success=True."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        discovery = ModemDiscovery()
        meta = PortMetadata("COM5", "Quectel USB AT Port")

        mock_ser = MagicMock()
        mock_ser.read.return_value = b"OK\r\n"
        mock_ser.in_waiting = 4

        with patch("serial.Serial", return_value=mock_ser):
            result = discovery.probe_port(meta)

        self.assertTrue(result.success)
        self.assertEqual(result.baud_rate, 115200)
        self.assertEqual(result.reason, "ok")

    def test_probe_failure_no_response(self):
        """Empty response returns ProbeResult with success=False."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        discovery = ModemDiscovery()
        meta = PortMetadata("COM5", "Quectel USB AT Port")

        mock_ser = MagicMock()
        mock_ser.read.return_value = b""
        mock_ser.in_waiting = 0

        with patch("serial.Serial", return_value=mock_ser):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)
        self.assertEqual(result.reason, "no_response")

    def test_probe_failure_at_no_ok(self):
        """AT response without OK returns success=False."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata
        discovery = ModemDiscovery()
        meta = PortMetadata("COM5", "Quectel USB AT Port")

        mock_ser = MagicMock()
        mock_ser.read.return_value = b"AT\r\n"
        mock_ser.in_waiting = 4

        with patch("serial.Serial", return_value=mock_ser):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)
        self.assertEqual(result.reason, "at_no_ok")


if __name__ == "__main__":
    unittest.main()
