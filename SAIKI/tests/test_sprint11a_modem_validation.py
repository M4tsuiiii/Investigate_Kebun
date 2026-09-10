"""Tests for Sprint 11A — Modem Validation.

Tests for ModemValidator: valid modem, invalid device, timeout, retry logic.
"""

import unittest
from unittest.mock import MagicMock, patch
import time

from app.domain.enums import ValidationResult, PortState
from worker.modem_validator import ModemValidator, PortValidationResult
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig


class TestModemValidator(unittest.TestCase):
    """Test ModemValidator AT command validation."""

    def _make_validator(self, timeout=0.1, retries=2):
        return ModemValidator(timeout=timeout, retries=retries)

    def _make_adapter(self, response_bytes=b"OK\r\n", open_ok=True):
        """Create a mock adapter with configured responses."""
        adapter = MagicMock()
        adapter.open.return_value = open_ok
        adapter.readline.return_value = response_bytes
        adapter.in_waiting = len(response_bytes)
        adapter.read.return_value = response_bytes
        adapter.write.return_value = True
        adapter.reset_input_buffer.return_value = None
        adapter.close.return_value = None
        return adapter

    def _make_factory(self, adapter):
        """Create a factory that always returns the same adapter."""
        return MagicMock(return_value=adapter)

    def test_valid_modem_returns_ok(self):
        """Port responding with OK is VALID_MODEM."""
        validator = self._make_validator()
        adapter = self._make_adapter(b"+CPIN: READY\r\nOK\r\n")
        factory = self._make_factory(adapter)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.VALID_MODEM)
        self.assertEqual(result.port_id, "COM3")
        self.assertIn("OK", result.response)

    def test_invalid_device_no_ok(self):
        """Port responding without OK is INVALID_DEVICE."""
        validator = self._make_validator()
        adapter = self._make_adapter(b"GARBAGE DATA\r\n")
        factory = self._make_factory(adapter)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.INVALID_DEVICE)

    def test_timeout_device(self):
        """Port returning empty response is UNRESPONSIVE."""
        validator = self._make_validator()
        adapter = self._make_adapter(b"")
        factory = self._make_factory(adapter)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.UNRESPONSIVE)

    def test_factory_returns_none(self):
        """Factory returning None is INVALID_DEVICE."""
        validator = self._make_validator()
        factory = MagicMock(return_value=None)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.INVALID_DEVICE)

    def test_factory_raises_exception(self):
        """Factory raising exception is UNRESPONSIVE."""
        validator = self._make_validator()
        factory = MagicMock(side_effect=Exception("Serial port busy"))
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.UNRESPONSIVE)
        self.assertIn("Serial port busy", result.error)

    def test_serial_open_fails(self):
        """Serial open() returning False is UNRESPONSIVE."""
        validator = self._make_validator()
        adapter = self._make_adapter(open_ok=False)
        factory = self._make_factory(adapter)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.UNRESPONSIVE)

    def test_retry_on_failure(self):
        """Validator retries on failure before giving up."""
        validator = self._make_validator(retries=3)
        fail_adapter = self._make_adapter(b"")
        ok_adapter = self._make_adapter(b"OK\r\n")
        call_count = [0]

        def factory(port_id):
            call_count[0] += 1
            if call_count[0] <= 2:
                return fail_adapter
            return ok_adapter

        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.VALID_MODEM)
        self.assertEqual(result.attempts, 3)

    def test_max_retries_exceeded(self):
        """Validator gives up after max retries."""
        validator = self._make_validator(retries=2)
        adapter = self._make_adapter(b"")
        factory = self._make_factory(adapter)
        result = validator.validate("COM3", factory)
        self.assertEqual(result.status, ValidationResult.UNRESPONSIVE)
        self.assertEqual(result.attempts, 2)

    def test_at_command_written(self):
        """Validator writes AT command to serial."""
        validator = self._make_validator()
        adapter = self._make_adapter(b"OK\r\n")
        factory = self._make_factory(adapter)
        validator.validate("COM3", factory)
        adapter.write.assert_called_with(b"AT\r\n")

    def test_serial_closed_after_validation(self):
        """Serial port is closed after validation."""
        validator = self._make_validator()
        adapter = self._make_adapter(b"OK\r\n")
        factory = self._make_factory(adapter)
        validator.validate("COM3", factory)
        adapter.close.assert_called()

    def test_result_dataclass_fields(self):
        """PortValidationResult has all expected fields."""
        result = PortValidationResult(
            port_id="COM3",
            status=ValidationResult.VALID_MODEM,
            response="OK",
            attempts=1,
        )
        self.assertEqual(result.port_id, "COM3")
        self.assertEqual(result.status, ValidationResult.VALID_MODEM)
        self.assertEqual(result.response, "OK")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.error, "")


class TestWorkerManagerValidation(unittest.TestCase):
    """Test WorkerManager integrates ModemValidator correctly."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()

    def tearDown(self):
        if hasattr(self, "manager"):
            self.manager.stop_all()

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

    def test_valid_modem_creates_worker(self):
        """Only VALID_MODEM ports get workers created."""
        validator = ModemValidator(timeout=0.1, retries=1)
        adapter = self._make_ok_adapter()
        factory = MagicMock(return_value=adapter)

        manager = self._make_manager(validator=validator, serial_factory=factory)
        with patch.object(manager, "scan_once", return_value=["COM3"]):
            manager._scan_and_update()

        self.assertIn("COM3", manager.workers)
        self.assertEqual(manager.get_port_state("COM3"), PortState.ACTIVE)

    def test_invalid_device_no_worker(self):
        """INVALID_DEVICE ports do not get workers."""
        validator = ModemValidator(timeout=0.1, retries=1)
        adapter = MagicMock()
        adapter.open.return_value = True
        adapter.readline.return_value = b"GARBAGE\r\n"
        adapter.in_waiting = 7
        adapter.read.return_value = b"GARBAGE\r\n"
        adapter.write.return_value = True
        factory = MagicMock(return_value=adapter)

        manager = self._make_manager(validator=validator, serial_factory=factory)
        with patch.object(manager, "scan_once", return_value=["COM3"]):
            manager._scan_and_update()

        self.assertNotIn("COM3", manager.workers)
        self.assertNotIn("COM3", manager.get_all_port_states())

    def test_validation_result_stored(self):
        """Validation results are stored for startup report."""
        validator = ModemValidator(timeout=0.1, retries=1)
        adapter = self._make_ok_adapter()
        factory = MagicMock(return_value=adapter)

        manager = self._make_manager(validator=validator, serial_factory=factory)
        with patch.object(manager, "scan_once", return_value=["COM3"]):
            manager._scan_and_update()

        results = manager.get_validation_results()
        self.assertIn("COM3", results)
        self.assertEqual(results["COM3"].status, ValidationResult.VALID_MODEM)

    def test_no_serial_factory_skips_validation(self):
        """Without serial factory, ports are marked UNRESPONSIVE."""
        manager = self._make_manager()
        with patch.object(manager, "scan_once", return_value=["COM3"]):
            manager._scan_and_update()

        results = manager.get_validation_results()
        self.assertIn("COM3", results)
        self.assertEqual(results["COM3"].status, ValidationResult.UNRESPONSIVE)


if __name__ == "__main__":
    unittest.main()
