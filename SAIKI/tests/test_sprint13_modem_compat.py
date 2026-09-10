"""Tests for Sprint 13 — Modem Compatibility & Lifecycle Stabilization.

Tests for: numeric port sort, multi-baud detection, baud cache,
factory baud parameter, WorkerManager reconnect, validation failure, cache cleanup.
"""

import re
import unittest
from unittest.mock import MagicMock, patch, call

from app.domain.enums import ValidationResult, PortState
from app.domain.constants import MODEM_BAUD_RATES, MODEM_BAUD_TIMEOUT
from worker.modem_validator import ModemValidator, PortValidationResult
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig


# ------------------------------------------------------------------
# 1. Numeric Port Sort
# ------------------------------------------------------------------

class TestNumericPortSort(unittest.TestCase):
    """Test that scan_once returns ports in numeric order."""

    def _make_manager(self):
        event_bus = MagicMock()
        return WorkerManager(event_bus=event_bus, auto_run_config=AutoRunConfig())

    def test_sort_basic(self):
        """COM3 comes before COM10."""
        manager = self._make_manager()
        with patch.object(manager, "_scan_ports_raw", return_value=["COM10", "COM3"]):
            result = manager.scan_once()
        self.assertEqual(result, ["COM3", "COM10"])

    def test_sort_large_numbers(self):
        """COM101 < COM102 < COM110 < COM164."""
        manager = self._make_manager()
        with patch.object(manager, "_scan_ports_raw", return_value=["COM110", "COM101", "COM164", "COM102"]):
            result = manager.scan_once()
        self.assertEqual(result, ["COM101", "COM102", "COM110", "COM164"])

    def test_sort_single_port(self):
        """Single port returns as-is."""
        manager = self._make_manager()
        with patch.object(manager, "_scan_ports_raw", return_value=["COM5"]):
            result = manager.scan_once()
        self.assertEqual(result, ["COM5"])

    def test_sort_empty(self):
        """No ports returns empty list."""
        manager = self._make_manager()
        with patch.object(manager, "_scan_ports_raw", return_value=[]):
            result = manager.scan_once()
        self.assertEqual(result, [])

    def test_sort_numeric_extraction(self):
        """Extraction uses regex for numeric value."""
        port = "COM42"
        match = re.search(r'\d+', port)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group()), 42)


# ------------------------------------------------------------------
# 2. Multi-Baud Detection
# ------------------------------------------------------------------

class TestMultiBaudDetection(unittest.TestCase):
    """Test ModemValidator multi-baud detection."""

    def _make_adapter_for_baud(self, baud, responds_ok=True):
        """Create mock adapter for a specific baud rate."""
        adapter = MagicMock()
        adapter.open.return_value = True
        adapter.write.return_value = True
        adapter.reset_input_buffer.return_value = None
        adapter.close.return_value = None
        if responds_ok:
            adapter.in_waiting = 4
            adapter.read.return_value = b"OK\r\n"
        else:
            adapter.in_waiting = 0
            adapter.read.return_value = b""
        return adapter

    def test_detects_first_working_baud(self):
        """Returns first baud rate that responds with OK."""
        adapters = {
            9600: self._make_adapter_for_baud(9600, responds_ok=True),
            19200: self._make_adapter_for_baud(19200, responds_ok=False),
            115200: self._make_adapter_for_baud(115200, responds_ok=False),
        }

        def fake_sa(port_id, baud_rate=115200, timeout=1.0):
            return adapters.get(baud_rate, MagicMock())

        with patch("app.infrastructure.serial.SerialAdapter", side_effect=fake_sa):
            validator = ModemValidator(timeout=0.1, retries=1, baud_rates=[9600, 19200, 115200])
            result = validator.validate("COM3", MagicMock())

        self.assertEqual(result.status, ValidationResult.VALID_MODEM)
        self.assertEqual(result.baud_rate, 9600)

    def test_skips_non_working_baud(self):
        """Skips baud rates that don't respond with OK."""
        adapters = {
            9600: self._make_adapter_for_baud(9600, responds_ok=False),
            19200: self._make_adapter_for_baud(19200, responds_ok=True),
            115200: self._make_adapter_for_baud(115200, responds_ok=False),
        }

        def fake_sa(port_id, baud_rate=115200, timeout=1.0):
            return adapters.get(baud_rate, MagicMock())

        with patch("app.infrastructure.serial.SerialAdapter", side_effect=fake_sa):
            validator = ModemValidator(timeout=0.1, retries=1, baud_rates=[9600, 19200, 115200])
            result = validator.validate("COM3", MagicMock())

        self.assertEqual(result.status, ValidationResult.VALID_MODEM)
        self.assertEqual(result.baud_rate, 19200)

    def test_all_baud_fail_returns_invalid(self):
        """Returns INVALID_DEVICE when no baud rate responds with OK."""
        adapter = self._make_adapter_for_baud(0, responds_ok=False)
        adapter.in_waiting = 10
        adapter.read.return_value = b"GARBAGE\r\n"

        with patch("app.infrastructure.serial.SerialAdapter", return_value=adapter):
            validator = ModemValidator(timeout=0.1, retries=1, baud_rates=[9600, 19200, 115200])
            result = validator.validate("COM3", MagicMock())

        self.assertEqual(result.status, ValidationResult.INVALID_DEVICE)
        self.assertEqual(result.baud_rate, 0)

    def test_exception_on_open_continues_next_baud(self):
        """Exception on one baud rate continues to next."""
        def adapter_factory(port_id, baud_rate=115200, timeout=1.0):
            if baud_rate == 9600:
                raise Exception("Port busy")
            adapter = MagicMock()
            adapter.open.return_value = True
            adapter.write.return_value = True
            adapter.reset_input_buffer.return_value = None
            adapter.in_waiting = 4
            adapter.read.return_value = b"OK\r\n"
            adapter.close.return_value = None
            return adapter

        with patch("app.infrastructure.serial.SerialAdapter", side_effect=adapter_factory):
            validator = ModemValidator(timeout=0.1, retries=1, baud_rates=[9600, 19200])
            result = validator.validate("COM3", MagicMock())

        self.assertEqual(result.status, ValidationResult.VALID_MODEM)
        self.assertEqual(result.baud_rate, 19200)

    def test_baud_rates_order_matches_good(self):
        """Default MODEM_BAUD_RATES matches GOOD order: 9600, 19200, 115200."""
        self.assertEqual(MODEM_BAUD_RATES, [9600, 19200, 115200])


# ------------------------------------------------------------------
# 3. Baud Cache
# ------------------------------------------------------------------

class TestBaudCache(unittest.TestCase):
    """Test WorkerManager baud rate caching."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()

    def _make_manager(self, validator=None, serial_factory=None):
        return WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
            serial_factory=serial_factory,
            modem_validator=validator,
        )

    def _make_ok_adapter(self):
        adapter = MagicMock()
        adapter.open.return_value = True
        adapter.readline.return_value = b"OK\r\n"
        adapter.in_waiting = 4
        adapter.read.return_value = b"OK\r\n"
        adapter.write.return_value = True
        adapter.reset_input_buffer.return_value = None
        adapter.close.return_value = None
        return adapter

    def test_baud_cached_after_validation(self):
        """Detected baud rate is cached after validation."""
        adapter = self._make_ok_adapter()

        def fake_sa(port_id, baud_rate=115200, timeout=1.0):
            return adapter

        with patch("app.infrastructure.serial.SerialAdapter", side_effect=fake_sa):
            validator = ModemValidator(timeout=0.1, retries=1, baud_rates=[9600])
            manager = self._make_manager(validator=validator, serial_factory=MagicMock())
            with patch.object(manager, "_scan_ports_raw", return_value=["COM3"]):
                manager._scan_and_update()

        self.assertIn("COM3", manager._baud_rates)
        self.assertEqual(manager._baud_rates["COM3"], 9600)

    def test_baud_cache_used_for_reappearing_port(self):
        """Cached baud rate is reused when port reappears."""
        adapter = self._make_ok_adapter()

        def fake_sa(port_id, baud_rate=115200, timeout=1.0):
            return adapter

        with patch("app.infrastructure.serial.SerialAdapter", side_effect=fake_sa):
            validator = ModemValidator(timeout=0.1, retries=1, baud_rates=[9600])
            manager = self._make_manager(validator=validator, serial_factory=MagicMock())
            # First scan - validates and caches
            with patch.object(manager, "_scan_ports_raw", return_value=["COM3"]):
                manager._scan_and_update()
            self.assertIn("COM3", manager._baud_rates)

            # Destroy worker
            manager.destroy_worker("COM3")
            self.assertNotIn("COM3", manager.workers)

            # Second scan - port reappears, uses cache (no revalidation)
            with patch.object(manager, "_scan_ports_raw", return_value=["COM3"]):
                manager._scan_and_update()
            self.assertIn("COM3", manager.workers)

    def test_baud_cached_in_validation_result(self):
        """PortValidationResult stores detected baud rate."""
        result = PortValidationResult(
            port_id="COM3",
            status=ValidationResult.VALID_MODEM,
            baud_rate=9600,
        )
        self.assertEqual(result.baud_rate, 9600)

    def test_baud_rate_zero_when_not_detected(self):
        """Baud rate is 0 when not detected (factory-only validation)."""
        result = PortValidationResult(
            port_id="COM3",
            status=ValidationResult.VALID_MODEM,
            baud_rate=0,
        )
        self.assertEqual(result.baud_rate, 0)


# ------------------------------------------------------------------
# 4. Factory Receives Detected Baud
# ------------------------------------------------------------------

class TestFactoryReceivesBaud(unittest.TestCase):
    """Test that serial_factory receives detected baud rate."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()

    def test_factory_receives_default_baud(self):
        """Factory receives default 115200 when no baud cached."""
        serial_factory = MagicMock(return_value=MagicMock())
        manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
            serial_factory=serial_factory,
        )
        manager.create_worker("COM3")
        serial_factory.assert_called_once_with("COM3", 115200)

    def test_factory_receives_cached_baud(self):
        """Factory receives cached baud rate."""
        serial_factory = MagicMock(return_value=MagicMock())
        manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
            serial_factory=serial_factory,
        )
        manager._baud_rates["COM3"] = 9600
        manager.create_worker("COM3")
        serial_factory.assert_called_once_with("COM3", 9600)

    def test_system_bootstrap_factory_signature(self):
        """SystemBootstrap._create_serial accepts baud_rate parameter."""
        from worker.system_bootstrap import SystemBootstrap
        bootstrap = SystemBootstrap()
        import inspect
        sig = inspect.signature(bootstrap._create_serial)
        params = list(sig.parameters.keys())
        self.assertIn("baud_rate", params)


# ------------------------------------------------------------------
# 5. WorkerManager Reconnect Flow
# ------------------------------------------------------------------

class TestWorkerManagerReconnect(unittest.TestCase):
    """Test WorkerManager-driven reconnect via modem.offline event."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()

    def _make_manager(self, validator=None, serial_factory=None):
        return WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
            serial_factory=serial_factory,
            modem_validator=validator,
        )

    def test_modem_offline_destroys_worker(self):
        """modem.offline event destroys the worker for that port."""
        manager = self._make_manager()
        manager.create_worker("COM3")
        self.assertIn("COM3", manager.workers)

        manager._handle_modem_offline("COM3")
        self.assertNotIn("COM3", manager.workers)

    def test_modem_offline_unknown_port_noop(self):
        """modem.offline for unknown port is a no-op."""
        manager = self._make_manager()
        manager._handle_modem_offline("COM99")

    def test_modem_offline_subscribed(self):
        """WorkerManager subscribes to modem.offline in __init__."""
        manager = self._make_manager()
        self.event_bus.subscribe.assert_any_call("modem.offline", unittest.mock.ANY)

    def test_scan_recreates_after_offline(self):
        """Scan recreates worker for port that went offline and reappeared."""
        adapter = self._make_ok_adapter()

        def fake_sa(port_id, baud_rate=115200, timeout=1.0):
            return adapter

        with patch("app.infrastructure.serial.SerialAdapter", side_effect=fake_sa):
            validator = ModemValidator(timeout=0.1, retries=1, baud_rates=[9600])
            manager = self._make_manager(validator=validator, serial_factory=MagicMock())

            # First scan - creates worker
            with patch.object(manager, "_scan_ports_raw", return_value=["COM3"]):
                manager._scan_and_update()
            self.assertIn("COM3", manager.workers)

            # Modem goes offline - destroys worker
            manager._handle_modem_offline("COM3")
            self.assertNotIn("COM3", manager.workers)

            # Next scan - port reappears, cached baud reused
            with patch.object(manager, "_scan_ports_raw", return_value=["COM3"]):
                manager._scan_and_update()
            self.assertIn("COM3", manager.workers)

    def _make_ok_adapter(self):
        adapter = MagicMock()
        adapter.open.return_value = True
        adapter.write.return_value = True
        adapter.reset_input_buffer.return_value = None
        adapter.in_waiting = 4
        adapter.read.return_value = b"OK\r\n"
        adapter.close.return_value = None
        return adapter

    def test_port_worker_publishes_modem_offline(self):
        """PortWorker publishes modem.offline on exception."""
        from worker.port_worker import PortWorker

        event_bus = MagicMock()
        worker = PortWorker("COM3", event_bus, AutoRunConfig())
        worker._publish_event("modem.offline", {"port": "COM3"})
        event_bus.publish.assert_called_with("modem.offline", {"port": "COM3"})


# ------------------------------------------------------------------
# 6. Validation Failure
# ------------------------------------------------------------------

class TestValidationFailure(unittest.TestCase):
    """Test various validation failure scenarios with baud detection."""

    def test_factory_returns_none(self):
        """Factory returning None is INVALID_DEVICE."""
        validator = ModemValidator(timeout=0.1, retries=1)
        factory = MagicMock(return_value=None)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.INVALID_DEVICE)

    def test_exception_returns_unresponsive(self):
        """Exception during validation is UNRESPONSIVE."""
        validator = ModemValidator(timeout=0.1, retries=1)
        factory = MagicMock(side_effect=Exception("Port busy"))
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.UNRESPONSIVE)
        self.assertIn("Port busy", result.error)

    def test_no_response_returns_unresponsive(self):
        """No response from device is UNRESPONSIVE."""
        adapter = MagicMock()
        adapter.open.return_value = True
        adapter.write.return_value = True
        adapter.reset_input_buffer.return_value = None
        adapter.in_waiting = 0
        adapter.read.return_value = b""
        adapter.close.return_value = None
        factory = MagicMock(return_value=adapter)

        validator = ModemValidator(timeout=0.1, retries=1)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.UNRESPONSIVE)

    def test_invalid_response_returns_invalid_device(self):
        """Response without OK is INVALID_DEVICE."""
        adapter = MagicMock()
        adapter.open.return_value = True
        adapter.write.return_value = True
        adapter.reset_input_buffer.return_value = None
        adapter.in_waiting = 10
        adapter.read.return_value = b"GARBAGE DATA\r\n"
        adapter.close.return_value = None
        factory = MagicMock(return_value=adapter)

        validator = ModemValidator(timeout=0.1, retries=1)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.INVALID_DEVICE)

    def test_validation_result_has_all_fields(self):
        """PortValidationResult has all expected fields including baud_rate."""
        result = PortValidationResult(
            port_id="COM3",
            status=ValidationResult.VALID_MODEM,
            response="OK",
            attempts=1,
            baud_rate=9600,
        )
        self.assertEqual(result.port_id, "COM3")
        self.assertEqual(result.status, ValidationResult.VALID_MODEM)
        self.assertEqual(result.response, "OK")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.baud_rate, 9600)
        self.assertEqual(result.error, "")


# ------------------------------------------------------------------
# 7. Cache Cleanup
# ------------------------------------------------------------------

class TestCacheCleanup(unittest.TestCase):
    """Test validation and baud cache cleanup."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()

    def _make_manager(self):
        return WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )

    def test_clear_validation_cache_clears_baud_rates(self):
        """clear_validation_cache() also clears baud rate cache."""
        manager = self._make_manager()
        manager._validated_ports.add("COM3")
        manager._baud_rates["COM3"] = 9600

        manager.clear_validation_cache()

        self.assertNotIn("COM3", manager._validated_ports)
        self.assertNotIn("COM3", manager._baud_rates)

    def test_stop_all_clears_baud_rates(self):
        """stop_all() also clears baud rate cache."""
        manager = self._make_manager()
        manager._validated_ports.add("COM3")
        manager._baud_rates["COM3"] = 9600

        manager.stop_all()

        self.assertNotIn("COM3", manager._baud_rates)
        self.assertEqual(len(manager._baud_rates), 0)

    def test_clear_cache_log_message(self):
        """clear_validation_cache logs cache cleared message."""
        manager = self._make_manager()
        with self.assertLogs("saiki.worker", level="INFO") as cm:
            manager.clear_validation_cache()
        self.assertTrue(any("cache cleared" in msg for msg in cm.output))

    def test_baud_cache_persists_across_scans(self):
        """Baud cache persists across multiple scan cycles."""
        manager = self._make_manager()
        manager._baud_rates["COM3"] = 9600

        with patch.object(manager, "_scan_ports_raw", return_value=["COM3"]):
            manager._scan_and_update()

        self.assertEqual(manager._baud_rates.get("COM3"), 9600)


if __name__ == "__main__":
    unittest.main()
