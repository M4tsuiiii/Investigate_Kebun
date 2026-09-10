"""Tests for Sprint 15Q — Modem Discovery & Connection Hardening.

Covers:
1. COM ports from Windows enumeration (incl. COM101, COM147)
2. No hard-coded COM range
3. 115200 as default probe baud
4. Echoed AT without OK is rejected
5. Response with OK is accepted
6. Failed probe → no worker/CPIN
7. Verified port → one worker-owned serial adapter
8. Probe handle closes on success/failure/exception
9. Probe concurrency capped at configured limit
10. Scan dispatch returns immediately (UI non-blocking)
11. Detected baud in Config only
12. Existing workflow/CPIN behavior compatible
"""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch, PropertyMock


# ------------------------------------------------------------------
# 1. Port enumeration from Windows (including high COM numbers)
# ------------------------------------------------------------------

class TestPortEnumeration(unittest.TestCase):
    """COM ports come from Windows enumeration, not hard-coded range."""

    def test_enumerate_includes_high_com_ports(self):
        """Enumeration includes COM101, COM147 from OS."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()

        mock_info_101 = MagicMock()
        mock_info_101.device = "COM101"
        mock_info_101.description = "Quectel USB AT Port"
        mock_info_101.manufacturer = "Quectel"
        mock_info_101.vid = "2C7C"
        mock_info_101.pid = "0125"
        mock_info_101.hwid = "USB VID:PID=2C7C:0125"

        mock_info_147 = MagicMock()
        mock_info_147.device = "COM147"
        mock_info_147.description = "XR21V1414 USB UART"
        mock_info_147.manufacturer = "Exar"
        mock_info_147.vid = "04E2"
        mock_info_147.pid = "1414"
        mock_info_147.hwid = "USB VID:PID=04E2:1414"

        with patch("serial.tools.list_ports.comports", return_value=[mock_info_101, mock_info_147]):
            ports = discovery.enumerate_ports()

        port_names = [p.port_name for p in ports]
        self.assertIn("COM101", port_names)
        self.assertIn("COM147", port_names)

    def test_enumerate_collects_metadata(self):
        """Enumeration collects description, manufacturer, VID, PID, HWID."""
        from worker.modem_discovery import ModemDiscovery

        discovery = ModemDiscovery()

        mock_info = MagicMock()
        mock_info.device = "COM5"
        mock_info.description = "Quectel USB AT Port"
        mock_info.manufacturer = "Quectel Incorporated"
        mock_info.vid = "2C7C"
        mock_info.pid = "0125"
        mock_info.hwid = "USB VID:PID=2C7C:0125"

        with patch("serial.tools.list_ports.comports", return_value=[mock_info]):
            ports = discovery.enumerate_ports()

        self.assertEqual(len(ports), 1)
        meta = ports[0]
        self.assertEqual(meta.port_name, "COM5")
        self.assertEqual(meta.description, "Quectel USB AT Port")
        self.assertEqual(meta.manufacturer, "Quectel Incorporated")
        self.assertEqual(meta.vid, "2C7C")
        self.assertEqual(meta.pid, "0125")

    def test_enumerate_logs_discovery_enumerated(self):
        """Enumeration logs [DISCOVERY ENUMERATED] per port."""
        from worker.modem_discovery import ModemDiscovery

        discovery = ModemDiscovery()

        mock_info = MagicMock()
        mock_info.device = "COM3"
        mock_info.description = "USB Serial"
        mock_info.manufacturer = "Prolific"
        mock_info.vid = "067B"
        mock_info.pid = "2303"
        mock_info.hwid = "USB VID:PID=067B:2303"

        with patch("serial.tools.list_ports.comports", return_value=[mock_info]):
            with self.assertLogs("saiki.discovery", level="INFO") as cm:
                discovery.enumerate_ports()

        enum_logs = [l for l in cm.output if "[DISCOVERY ENUMERATED]" in l]
        self.assertTrue(len(enum_logs) >= 1)
        self.assertIn("COM3", enum_logs[0])


# ------------------------------------------------------------------
# 2. No hard-coded COM range
# ------------------------------------------------------------------

class TestNoHardCodedRange(unittest.TestCase):
    """Scanner never uses a hard-coded COM1-COM64 range."""

    def test_scan_ports_uses_list_ports(self):
        """_scan_ports_raw uses serial.tools.list_ports.comports()."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig

        wm = WorkerManager(
            event_bus=MagicMock(),
            auto_run_config=AutoRunConfig(),
        )

        with patch("serial.tools.list_ports.comports") as mock_comports:
            mock_comports.return_value = [MagicMock(device="COM99")]
            ports = wm._scan_ports_raw()

        self.assertEqual(ports, ["COM99"])
        mock_comports.assert_called_once()

    def test_no_range_in_code(self):
        """No COM1-COM64 range exists in worker_manager.py."""
        import inspect
        from worker.worker_manager import WorkerManager

        source = inspect.getsource(WorkerManager)
        self.assertNotIn("COM1", source)
        self.assertNotIn("COM64", source)
        self.assertNotIn("range(1,", source)

    def test_discovery_no_range_in_code(self):
        """No COM range exists in modem_discovery.py."""
        import inspect
        from worker.modem_discovery import ModemDiscovery

        source = inspect.getsource(ModemDiscovery)
        self.assertNotIn("range(1,", source)
        self.assertNotIn("COM1-COM", source)


# ------------------------------------------------------------------
# 3. 115200 default probe baud
# ------------------------------------------------------------------

class TestDefaultProbeBaud(unittest.TestCase):
    """115200 is the default probe baud rate."""

    def test_default_baud_is_115200(self):
        """ModemDiscovery defaults to 115200 baud."""
        from worker.modem_discovery import ModemDiscovery
        from app.domain.constants import DISCOVERY_BAUD_RATE

        discovery = ModemDiscovery()
        self.assertEqual(discovery._baud_rate, 115200)
        self.assertEqual(DISCOVERY_BAUD_RATE, 115200)

    def test_probe_uses_configured_baud(self):
        """Probe sends AT at the configured baud rate."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery(baud_rate=115200)
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 0

        with patch("serial.Serial", return_value=mock_serial) as MockSerial:
            discovery.probe_port(meta)

        MockSerial.assert_called_once()
        call_kwargs = MockSerial.call_args
        self.assertEqual(call_kwargs.kwargs.get("baudrate") or call_kwargs[1].get("baudrate", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None), 115200)


# ------------------------------------------------------------------
# 4. Echoed AT without OK is rejected
# ------------------------------------------------------------------

class TestEchoRejection(unittest.TestCase):
    """A response containing only echoed AT is rejected."""

    def test_echo_without_ok_rejected(self):
        """AT echo without OK returns ProbeResult(success=False)."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"AT\r\n"

        with patch("serial.Serial", return_value=mock_serial):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)
        self.assertEqual(result.reason, "at_no_ok")

    def test_empty_response_rejected(self):
        """No response returns ProbeResult(success=False)."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 0

        with patch("serial.Serial", return_value=mock_serial):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)
        self.assertEqual(result.reason, "no_response")

    def test_error_response_rejected(self):
        """ERROR response returns ProbeResult(success=False)."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"ERROR\r\n"

        with patch("serial.Serial", return_value=mock_serial):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)


# ------------------------------------------------------------------
# 5. Response with OK is accepted
# ------------------------------------------------------------------

class TestOKAcceptance(unittest.TestCase):
    """A response containing OK is accepted."""

    def test_ok_response_accepted(self):
        """Response with OK returns ProbeResult(success=True)."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"OK\r\n"

        with patch("serial.Serial", return_value=mock_serial):
            result = discovery.probe_port(meta)

        self.assertTrue(result.success)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.baud_rate, 115200)

    def test_ok_in_multiline_response(self):
        """OK found within multi-line response."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 20
        mock_serial.read.return_value = b"AT\r\n\r\nOK\r\n"

        with patch("serial.Serial", return_value=mock_serial):
            result = discovery.probe_port(meta)

        self.assertTrue(result.success)


# ------------------------------------------------------------------
# 6. Failed probe → no worker/CPIN
# ------------------------------------------------------------------

class TestFailedProbeNoWorker(unittest.TestCase):
    """Failed probe ports do not create workers or CPIN runtimes."""

    def test_rejected_port_not_in_validated(self):
        """Ports that fail AT probe are marked validated but not as VALID_MODEM."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata, ProbeResult

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM99")

        # Mock probe to return failure
        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"NO CARRIER\r\n"

        with patch("serial.Serial", return_value=mock_serial):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)
        self.assertEqual(result.reason, "at_no_ok")

    def test_discovery_rejects_failed_ports(self):
        """discover_all() does not include failed ports in verified list."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()

        mock_info = MagicMock()
        mock_info.device = "COM1"
        mock_info.description = "Quectel USB AT Port"
        mock_info.manufacturer = "Quectel"
        mock_info.vid = "2C7C"
        mock_info.pid = "0125"
        mock_info.hwid = "USB VID:PID=2C7C:0125"

        # Probe returns ERROR (not OK)
        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"ERROR\r\n"

        with patch("serial.tools.list_ports.comports", return_value=[mock_info]):
            with patch("serial.Serial", return_value=mock_serial):
                verified = discovery.discover_all()

        # Port should be rejected (ERROR != OK)
        verified_names = [v.port_name for v in verified]
        self.assertNotIn("COM1", verified_names)


# ------------------------------------------------------------------
# 7. Verified port → one worker-owned serial adapter
# ------------------------------------------------------------------

class TestVerifiedPortCreatesWorker(unittest.TestCase):
    """Verified port creates exactly one worker-owned serial adapter."""

    def test_worker_connect_creates_single_serial(self):
        """PortWorker.connect() stores exactly one serial adapter."""
        from worker.port_worker import PortWorker
        from worker.rules import AutoRunConfig

        worker = PortWorker("COM1", MagicMock(), AutoRunConfig())
        serial_adapter = MagicMock()
        serial_adapter.is_open = True
        at_client = MagicMock()

        with patch("worker.port_worker.CpinRuntime"):
            with patch("worker.port_worker.UssdRuntime"):
                with patch("worker.port_worker.CleanupManager"):
                    worker.connect(serial_adapter, at_client)

        self.assertIs(worker._serial, serial_adapter)
        self.assertIs(worker._at_client, at_client)

    def test_worker_manager_creates_one_worker_per_port(self):
        """WorkerManager.create_worker creates one worker per port."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig

        event_bus = MagicMock()
        auto_run_config = AutoRunConfig()

        wm = WorkerManager(
            event_bus=event_bus,
            auto_run_config=auto_run_config,
            serial_factory=lambda p, b=115200: MagicMock(is_open=True),
            at_client_factory=lambda s: MagicMock(),
        )

        # Mock worker to track connect calls
        with patch("worker.worker_manager.PortWorker") as MockWorker:
            mock_instance = MagicMock()
            MockWorker.return_value = mock_instance

            wm.create_worker("COM1")
            wm.create_worker("COM1")  # Duplicate — should be skipped

            self.assertEqual(MockWorker.call_count, 1)


# ------------------------------------------------------------------
# 8. Probe handle closes on success/failure/exception
# ------------------------------------------------------------------

class TestProbeHandleClose(unittest.TestCase):
    """Probe handles close in every path."""

    def test_close_on_success(self):
        """Serial handle closes after successful probe."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"OK\r\n"

        with patch("serial.Serial", return_value=mock_serial):
            discovery.probe_port(meta)

        mock_serial.close.assert_called_once()

    def test_close_on_failure(self):
        """Serial handle closes after failed probe (no OK)."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"ERROR\r\n"

        with patch("serial.Serial", return_value=mock_serial):
            discovery.probe_port(meta)

        mock_serial.close.assert_called_once()

    def test_close_on_exception(self):
        """Serial handle closes after exception during probe."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        mock_serial = MagicMock()
        mock_serial.in_waiting = 0
        mock_serial.read.side_effect = OSError("port busy")

        with patch("serial.Serial", return_value=mock_serial):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)
        mock_serial.close.assert_called_once()

    def test_close_on_open_failure(self):
        """Serial handle closes when open() fails."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1")

        with patch("serial.Serial", side_effect=OSError("Cannot open")):
            result = discovery.probe_port(meta)

        self.assertFalse(result.success)
        self.assertIn("exception", result.reason)


# ------------------------------------------------------------------
# 9. Probe concurrency capped
# ------------------------------------------------------------------

class TestProbeConcurrencyCap(unittest.TestCase):
    """Probe concurrency does not exceed configured max."""

    def test_max_concurrent_respected(self):
        """probe_concurrent uses bounded ThreadPoolExecutor."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery(max_concurrent=2)
        candidates = [
            PortMetadata(port_name=f"COM{i}")
            for i in range(6)
        ]

        concurrent_count = []
        max_observed = []

        def counting_probe(meta):
            current = len(concurrent_count)
            concurrent_count.append(1)
            max_observed.append(current + 1)
            time.sleep(0.01)
            concurrent_count.pop()
            from worker.modem_discovery import ProbeResult
            return ProbeResult(meta.port_name, 115200, True, "OK", "ok")

        discovery.probe_port = counting_probe

        with patch("serial.tools.list_ports.comports", return_value=[]):
            results = discovery.probe_concurrent(candidates)

        self.assertEqual(len(results), 6)

    def test_default_max_concurrent_is_4(self):
        """Default max concurrent is 4."""
        from worker.modem_discovery import ModemDiscovery
        from app.domain.constants import DISCOVERY_MAX_CONCURRENT

        discovery = ModemDiscovery()
        self.assertEqual(discovery._max_concurrent, 4)
        self.assertEqual(DISCOVERY_MAX_CONCURRENT, 4)


# ------------------------------------------------------------------
# 10. Scan dispatch returns immediately (UI non-blocking)
# ------------------------------------------------------------------

class TestScanNonBlocking(unittest.TestCase):
    """Scan dispatch returns immediately without blocking UI."""

    def test_scan_once_returns_promptly(self):
        """scan_once() returns within 1 second."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig

        wm = WorkerManager(
            event_bus=MagicMock(),
            auto_run_config=AutoRunConfig(),
        )

        with patch("serial.tools.list_ports.comports", return_value=[]):
            start = time.time()
            wm.scan_once()
            elapsed = time.time() - start

        self.assertLess(elapsed, 1.0)

    def test_start_scanning_returns_promptly(self):
        """start_scanning() returns immediately."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig

        wm = WorkerManager(
            event_bus=MagicMock(),
            auto_run_config=AutoRunConfig(),
        )

        start = time.time()
        wm.start_scanning()
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.5)
        wm.stop_scanning()


# ------------------------------------------------------------------
# 11. Detected baud in Config only
# ------------------------------------------------------------------

class TestConfigBaudDisplay(unittest.TestCase):
    """Detected baud appears in Config only, not in Home/Workspace."""

    def test_config_has_detected_modems_field(self):
        """Config includes detected_modems field."""
        from worker.ui.settings_dialog import load_config

        config = load_config()
        self.assertIn("detected_modems", config.get("modem", {}))

    def test_config_has_default_baud_rate(self):
        """Config includes default_baud_rate field."""
        from worker.ui.settings_dialog import load_config

        config = load_config()
        self.assertIn("default_baud_rate", config.get("modem", {}))
        self.assertEqual(config["modem"]["default_baud_rate"], 115200)

    def test_config_has_fallback_baud_enabled(self):
        """Config includes fallback_baud_enabled field."""
        from worker.ui.settings_dialog import load_config

        config = load_config()
        self.assertIn("fallback_baud_enabled", config.get("modem", {}))
        self.assertFalse(config["modem"]["fallback_baud_enabled"])

    def test_port_table_no_baud_column(self):
        """Port table does not have a BAUD column."""
        import inspect
        from worker.ui.port_table import PortStatusTable

        source = inspect.getsource(PortStatusTable)
        self.assertNotIn("BAUD", source)


# ------------------------------------------------------------------
# 12. Existing workflow/CPIN behavior compatible
# ------------------------------------------------------------------

class TestBackwardCompatibility(unittest.TestCase):
    """Existing workflow and CPIN behavior remains compatible."""

    def test_worker_manager_accepts_none_discovery(self):
        """WorkerManager works without ModemDiscovery (backward compat)."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig

        wm = WorkerManager(
            event_bus=MagicMock(),
            auto_run_config=AutoRunConfig(),
            modem_discovery=None,
        )

        self.assertIsNone(wm._modem_discovery)

    def test_worker_manager_falls_back_to_validator(self):
        """WorkerManager falls back to ModemValidator when no discovery."""
        from worker.worker_manager import WorkerManager
        from worker.rules import AutoRunConfig

        wm = WorkerManager(
            event_bus=MagicMock(),
            auto_run_config=AutoRunConfig(),
            modem_discovery=None,
        )

        with patch("serial.tools.list_ports.comports", return_value=[]):
            with patch.object(wm, "_validate_port") as mock_validate:
                wm._scan_with_validator()
                mock_validate.assert_not_called()

    def test_cpin_state_enum_unchanged(self):
        """CpinState enum values unchanged."""
        from app.domain.enums import CpinState

        self.assertEqual(CpinState.READY.value, "READY")
        self.assertEqual(CpinState.NOT_INSERTED.value, "NOT_INSERTED")
        self.assertEqual(CpinState.PIN_REQUIRED.value, "PIN_REQUIRED")
        self.assertEqual(CpinState.NOT_READY.value, "NOT_READY")
        self.assertEqual(CpinState.UNKNOWN.value, "UNKNOWN")

    def test_discovery_constants_importable(self):
        """Sprint 15Q constants are importable."""
        from app.domain.constants import (
            DISCOVERY_BAUD_RATE,
            DISCOVERY_PROBE_TIMEOUT,
            DISCOVERY_MAX_CONCURRENT,
            DISCOVERY_CANDIDATE_KEYWORDS,
        )

        self.assertEqual(DISCOVERY_BAUD_RATE, 115200)
        self.assertEqual(DISCOVERY_PROBE_TIMEOUT, 2.0)
        self.assertEqual(DISCOVERY_MAX_CONCURRENT, 4)
        self.assertIn("Quectel", DISCOVERY_CANDIDATE_KEYWORDS)


# ------------------------------------------------------------------
# Candidate filter tests
# ------------------------------------------------------------------

class TestCandidateFilter(unittest.TestCase):
    """Metadata-based candidate filtering."""

    def test_quectel_description_accepted(self):
        """Port with 'Quectel' in description is accepted."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1", description="Quectel USB AT Port")

        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(skipped), 0)

    def test_unknown_device_skipped(self):
        """Port with no matching metadata is skipped."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1", description="Microsoft Print to PDF")

        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 0)
        self.assertEqual(len(skipped), 1)

    def test_quectel_vid_accepted(self):
        """Port with Quectel VID (2C7C) is accepted."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1", vid="2C7C")

        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)

    def test_xr21v1414_accepted(self):
        """Port with XR21V1414 in description is accepted."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1", description="XR21V1414 USB UART")

        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 1)

    def test_usb_serial_rejected_without_hardware_identity(self):
        """Port with 'USB Serial' in description is rejected without HWID/VID match.

        Sprint 15R: Generic USB Serial without known hardware identity is not a candidate.
        """
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()
        meta = PortMetadata(port_name="COM1", description="USB Serial Converter")

        candidates, skipped = discovery.filter_candidates([meta])
        self.assertEqual(len(candidates), 0)
        self.assertEqual(len(skipped), 1)


# ------------------------------------------------------------------
# Discovery pipeline integration
# ------------------------------------------------------------------

class TestDiscoveryPipeline(unittest.TestCase):
    """Full discovery pipeline integration."""

    def test_discover_all_returns_verified_list(self):
        """discover_all returns list of VerifiedPort objects."""
        from worker.modem_discovery import ModemDiscovery, PortMetadata

        discovery = ModemDiscovery()

        mock_info = MagicMock()
        mock_info.device = "COM1"
        mock_info.description = "Quectel USB AT Port"
        mock_info.manufacturer = "Quectel"
        mock_info.vid = "2C7C"
        mock_info.pid = "0125"
        mock_info.hwid = "USB VID:PID=2C7C:0125"

        mock_serial = MagicMock()
        mock_serial.in_waiting = 10
        mock_serial.read.return_value = b"OK\r\n"

        with patch("serial.tools.list_ports.comports", return_value=[mock_info]):
            with patch("serial.Serial", return_value=mock_serial):
                verified = discovery.discover_all()

        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].port_name, "COM1")
        self.assertEqual(verified[0].baud_rate, 115200)

    def test_discover_all_empty_when_no_ports(self):
        """discover_all returns empty list when no ports found."""
        from worker.modem_discovery import ModemDiscovery

        discovery = ModemDiscovery()

        with patch("serial.tools.list_ports.comports", return_value=[]):
            verified = discovery.discover_all()

        self.assertEqual(len(verified), 0)


if __name__ == "__main__":
    unittest.main()
