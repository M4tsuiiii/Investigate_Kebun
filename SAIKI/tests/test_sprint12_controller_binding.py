"""Tests for Sprint 12 — Controller Binding for UI Parity.

Tests for PORT_EXCLUDE/PORT_INCLUDE handlers, mass action routing,
and auto-run toggle in the controller.
"""

import unittest
from unittest.mock import MagicMock, patch, call

from worker.ui.controller import UIController
from worker.ui.events import CommandEvent, UIEvent
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig
from worker.db_lookup import DbLookup
from automation.engine import AutomationEngine


def _make_controller():
    """Create a UIController with mocked dependencies."""
    event_bus = MagicMock()
    worker_manager = MagicMock(spec=WorkerManager)
    auto_run_config = AutoRunConfig()
    automation_engine = MagicMock(spec=AutomationEngine)
    db_lookup = MagicMock(spec=DbLookup)
    controller = UIController(
        event_bus=event_bus,
        worker_manager=worker_manager,
        auto_run_config=auto_run_config,
        automation_engine=automation_engine,
        db_lookup=db_lookup,
    )
    return controller, event_bus, worker_manager, auto_run_config, automation_engine, db_lookup


class TestControllerExcludeInclude(unittest.TestCase):
    """Test PORT_EXCLUDE and PORT_INCLUDE handlers."""

    def setUp(self):
        self.controller, self.event_bus, self.worker_manager, _, _, _ = _make_controller()

    def test_subscribes_to_port_exclude(self):
        """Verify controller subscribes to PORT_EXCLUDE."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.PORT_EXCLUDE.value in c for c in calls))

    def test_subscribes_to_port_include(self):
        """Verify controller subscribes to PORT_INCLUDE."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.PORT_INCLUDE.value in c for c in calls))

    def test_exclude_calls_worker_manager(self):
        """Test exclude handler calls worker_manager.exclude_port."""
        self.controller._handle_port_exclude({"port": "COM3"})
        self.worker_manager.exclude_port.assert_called_once_with("COM3")

    def test_exclude_publishes_port_excluded(self):
        """Test exclude handler publishes PORT_EXCLUDED event."""
        self.controller._handle_port_exclude({"port": "COM3"})
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any(UIEvent.PORT_EXCLUDED.value in c for c in calls))

    def test_include_calls_worker_manager(self):
        """Test include handler calls worker_manager.include_port."""
        self.controller._handle_port_include({"port": "COM3"})
        self.worker_manager.include_port.assert_called_once_with("COM3")

    def test_include_publishes_port_included(self):
        """Test include handler publishes PORT_INCLUDED event."""
        self.controller._handle_port_include({"port": "COM3"})
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any(UIEvent.PORT_INCLUDED.value in c for c in calls))

    def test_exclude_with_no_port_does_nothing(self):
        """Test exclude with empty payload does nothing."""
        self.controller._handle_port_exclude({})
        self.worker_manager.exclude_port.assert_not_called()

    def test_include_with_no_port_does_nothing(self):
        """Test include with empty payload does nothing."""
        self.controller._handle_port_include({})
        self.worker_manager.include_port.assert_not_called()


class TestControllerAutoRunToggle(unittest.TestCase):
    """Test AUTO_RUN_TOGGLE handler."""

    def setUp(self):
        self.controller, self.event_bus, _, self.auto_run_config, _, _ = _make_controller()

    def test_subscribes_to_auto_run_toggle(self):
        """Verify controller subscribes to AUTO_RUN_TOGGLE."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.AUTO_RUN_TOGGLE.value in c for c in calls))

    def test_toggle_with_enabled_true(self):
        """Test toggle with enabled=True sets config."""
        self.controller._handle_auto_run_toggle({"enabled": True})
        self.assertTrue(self.auto_run_config.auto_run_enabled)

    def test_toggle_with_enabled_false(self):
        """Test toggle with enabled=False disables."""
        self.controller._handle_auto_run_toggle({"enabled": False})
        self.assertFalse(self.auto_run_config.auto_run_enabled)

    def test_toggle_without_enabled_toggles(self):
        """Test toggle without enabled parameter toggles state."""
        initial = self.auto_run_config.auto_run_enabled
        self.controller._handle_auto_run_toggle({})
        self.assertNotEqual(self.auto_run_config.auto_run_enabled, initial)

    def test_toggle_publishes_auto_run_changed(self):
        """Test toggle publishes AUTO_RUN_CHANGED event."""
        self.controller._handle_auto_run_toggle({"enabled": True})
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any(UIEvent.AUTO_RUN_CHANGED.value in c for c in calls))


class TestControllerMassActions(unittest.TestCase):
    """Test mass action handlers use get_active_ports()."""

    def setUp(self):
        self.controller, self.event_bus, self.worker_manager, _, self.automation_engine, _ = _make_controller()

    def test_mass_cek_nomor_uses_active_ports(self):
        """Test mass check uses get_active_ports, not all workers."""
        self.worker_manager.get_active_ports.return_value = ["COM3", "COM5"]
        self.controller._handle_mass_cek_nomor({})
        self.worker_manager.get_active_ports.assert_called_once()
        self.assertEqual(self.automation_engine.enqueue_workflow.call_count, 2)

    def test_mass_reaktivasi_uses_active_ports(self):
        """Test mass reactivation uses get_active_ports, not all workers."""
        self.worker_manager.get_active_ports.return_value = ["COM3"]
        self.controller._handle_mass_reaktivasi({})
        self.worker_manager.get_active_ports.assert_called_once()
        self.assertEqual(self.automation_engine.enqueue_workflow.call_count, 1)

    def test_mass_cek_nomor_skips_excluded(self):
        """Test mass check skips excluded ports."""
        self.worker_manager.get_active_ports.return_value = ["COM3"]
        self.controller._handle_mass_cek_nomor({})
        self.automation_engine.enqueue_workflow.assert_called_once_with("COM3", "check_data", priority=10)

    def test_mass_reaktivasi_skips_excluded(self):
        """Test mass reactivation skips excluded ports."""
        self.worker_manager.get_active_ports.return_value = ["COM3"]
        self.controller._handle_mass_reaktivasi({})
        self.automation_engine.enqueue_workflow.assert_called_once_with("COM3", "reactivate_full", priority=10)

    def test_mass_publishes_progress(self):
        """Test mass actions publish MASS_PROGRESS event."""
        self.worker_manager.get_active_ports.return_value = ["COM3", "COM5"]
        self.controller._handle_mass_cek_nomor({})
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any(UIEvent.MASS_PROGRESS.value in c for c in calls))


class TestControllerDatabaseLookups(unittest.TestCase):
    """Test database lookup handlers."""

    def setUp(self):
        self.controller, self.event_bus, _, _, _, self.db_lookup = _make_controller()

    def test_subscribes_to_db_lookup_nik(self):
        """Verify controller subscribes to DB_LOOKUP_NIK."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.DB_LOOKUP_NIK.value in c for c in calls))

    def test_subscribes_to_db_lookup_kk(self):
        """Verify controller subscribes to DB_LOOKUP_KK."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.DB_LOOKUP_KK.value in c for c in calls))

    def test_lookup_nik_calls_db(self):
        """Test NIK lookup calls db_lookup.lookup_nik."""
        self.db_lookup.lookup_nik.return_value = {"found": True}
        self.controller._handle_db_lookup_nik({"port": "COM3", "msisdn": "081234"})
        self.db_lookup.lookup_nik.assert_called_once_with("081234")

    def test_lookup_nik_publishes_result(self):
        """Test NIK lookup publishes DB_LOOKUP_RESULT."""
        self.db_lookup.lookup_nik.return_value = {"found": True}
        self.controller._handle_db_lookup_nik({"port": "COM3", "msisdn": "081234"})
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any(UIEvent.DB_LOOKUP_RESULT.value in c for c in calls))

    def test_lookup_nik_with_empty_payload(self):
        """Test NIK lookup with empty payload does nothing."""
        self.controller._handle_db_lookup_nik({})
        self.db_lookup.lookup_nik.assert_not_called()

    def test_lookup_kk_calls_db(self):
        """Test KK lookup calls db_lookup.lookup_kk."""
        self.db_lookup.lookup_kk.return_value = {"found": True}
        self.controller._handle_db_lookup_kk({"port": "COM3", "nik": "320123"})
        self.db_lookup.lookup_kk.assert_called_once_with("320123")

    def test_lookup_kk_publishes_result(self):
        """Test KK lookup publishes DB_LOOKUP_RESULT."""
        self.db_lookup.lookup_kk.return_value = {"found": True}
        self.controller._handle_db_lookup_kk({"port": "COM3", "nik": "320123"})
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any(UIEvent.DB_LOOKUP_RESULT.value in c for c in calls))


if __name__ == "__main__":
    unittest.main()
