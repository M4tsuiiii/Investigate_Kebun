"""Tests for UIController — bridges EventBus events to worker actions."""

import unittest
from unittest.mock import MagicMock, patch

from worker.ui.controller import UIController
from worker.ui.events import CommandEvent, UIEvent
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig
from worker.db_lookup import DbLookup


def _make_controller():
    event_bus = MagicMock()
    worker_manager = MagicMock(spec=WorkerManager)
    auto_run_config = AutoRunConfig()
    automation_engine = MagicMock()
    db_lookup = MagicMock(spec=DbLookup)
    controller = UIController(
        event_bus=event_bus,
        worker_manager=worker_manager,
        auto_run_config=auto_run_config,
        automation_engine=automation_engine,
        db_lookup=db_lookup,
    )
    return controller, event_bus, worker_manager, auto_run_config, automation_engine, db_lookup


class TestUIControllerSubscriptions(unittest.TestCase):
    """Test UIController subscribes to correct CommandEvents."""

    def setUp(self):
        """Create fresh UIController before each test."""
        self.controller, self.event_bus, self.worker_manager, _, _, _ = _make_controller()

    def test_subscribes_to_port_on(self):
        """Verify subscribes to PORT_ON command event."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.PORT_ON.value in c for c in calls))

    def test_subscribes_to_port_off(self):
        """Verify subscribes to PORT_OFF command event."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.PORT_OFF.value in c for c in calls))

    def test_subscribes_to_restart_all(self):
        """Verify subscribes to RESTART_ALL command event."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.RESTART_ALL.value in c for c in calls))

    def test_subscribes_to_stop_all(self):
        """Verify subscribes to STOP_ALL command event."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.STOP_ALL.value in c for c in calls))

    def test_subscribes_to_mass_reaktivasi(self):
        """Verify subscribes to MASS_REAKTIVASI command event."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.MASS_REAKTIVASI.value in c for c in calls))

    def test_subscribes_to_mass_cek_nomor(self):
        """Verify subscribes to MASS_CEK_NOMOR command event."""
        calls = [str(c) for c in self.event_bus.subscribe.call_args_list]
        self.assertTrue(any(CommandEvent.MASS_CEK_NOMOR.value in c for c in calls))


class TestUIControllerPortActions(unittest.TestCase):
    """Test UIController port on/off handler logic."""

    def setUp(self):
        """Create fresh UIController with mock worker_manager."""
        self.controller, self.event_bus, self.worker_manager, _, _, _ = _make_controller()
        self.mock_worker = MagicMock()
        self.worker_manager.get_worker.return_value = self.mock_worker

    def test_handle_port_on_starts_worker(self):
        """Verify _handle_port_on calls worker.start()."""
        self.controller._handle_port_on({"port": "COM3"})
        self.mock_worker.start.assert_called_once()

    def test_handle_port_on_no_port(self):
        """Verify _handle_port_on does nothing without port."""
        self.controller._handle_port_on({})
        self.mock_worker.start.assert_not_called()

    def test_handle_port_on_unknown_port(self):
        """Verify _handle_port_on does nothing for unknown port."""
        self.worker_manager.get_worker.return_value = None
        self.controller._handle_port_on({"port": "COM99"})

    def test_handle_port_off_stops_worker(self):
        """Verify _handle_port_off calls worker.stop()."""
        self.controller._handle_port_off({"port": "COM3"})
        self.mock_worker.stop.assert_called_once()

    def test_handle_port_off_no_port(self):
        """Verify _handle_port_off does nothing without port."""
        self.controller._handle_port_off({})
        self.mock_worker.stop.assert_not_called()

    def test_handle_port_off_unknown_port(self):
        """Verify _handle_port_off does nothing for unknown port."""
        self.worker_manager.get_worker.return_value = None
        self.controller._handle_port_off({"port": "COM99"})


class TestUIControllerGlobalActions(unittest.TestCase):
    """Test UIController global command handlers."""

    def setUp(self):
        """Create fresh UIController with mock worker_manager."""
        self.controller, self.event_bus, self.worker_manager, _, self.automation_engine, _ = _make_controller()

    def test_handle_restart_all(self):
        """Verify _handle_restart_all enqueues hardware_restart for all workers."""
        mock_worker = MagicMock()
        self.worker_manager.workers = {"COM3": mock_worker}
        self.controller._handle_restart_all({})
        self.automation_engine.enqueue_workflow.assert_called()

    def test_handle_stop_all(self):
        """Verify _handle_stop_all calls worker_manager.stop_all() and automation_engine.stop()."""
        self.controller._handle_stop_all({})
        self.worker_manager.stop_all.assert_called_once()
        self.automation_engine.stop.assert_called_once()

    def test_handle_reset_modem(self):
        """Verify _handle_reset_modem uses automation_engine."""
        self.controller._handle_reset_modem({"port": "COM3"})
        self.automation_engine.handle_trigger.assert_called_once()
        self.automation_engine.enqueue_workflow.assert_called_once_with("COM3", "hardware_reset", priority=5)

    def test_handle_force_retry(self):
        """Verify _handle_force_retry calls worker.force_retry()."""
        mock_worker = MagicMock()
        self.worker_manager.get_worker.return_value = mock_worker
        self.controller._handle_force_retry({"port": "COM3"})
        mock_worker.force_retry.assert_called_once()


class TestUIControllerMassActions(unittest.TestCase):
    """Test UIController mass action handlers."""

    def setUp(self):
        """Create fresh UIController with mock worker_manager."""
        self.controller, self.event_bus, self.worker_manager, _, self.automation_engine, _ = _make_controller()

    def test_handle_mass_reaktivasi_enqueues_workflows(self):
        """Verify _handle_mass_reaktivasi enqueues workflow for each worker."""
        self.worker_manager.get_active_ports.return_value = []
        self.controller._handle_mass_reaktivasi({})
        self.worker_manager.workers = {"COM1": MagicMock(), "COM2": MagicMock()}
        self.worker_manager.get_active_ports.return_value = ["COM1", "COM2"]
        self.controller._handle_mass_reaktivasi({})
        self.assertTrue(self.automation_engine.enqueue_workflow.call_count >= 1)

    def test_handle_mass_cek_nomor_enqueues_workflows(self):
        """Verify _handle_mass_cek_nomor enqueues workflow for each worker."""
        self.worker_manager.workers = {"COM1": MagicMock()}
        self.worker_manager.get_active_ports.return_value = ["COM1"]
        self.controller._handle_mass_cek_nomor({})
        self.automation_engine.enqueue_workflow.assert_called_with("COM1", "check_number", priority=10, trigger_id=2)


class TestUIControllerConfig(unittest.TestCase):
    """Test UIController settings handlers."""

    def setUp(self):
        """Create fresh UIController with mock worker_manager."""
        self.controller, self.event_bus, self.worker_manager, _, _, _ = _make_controller()

    def test_handle_save_config_updates_settings(self):
        """Verify _handle_save_config stores settings."""
        self.controller._handle_save_config({"baud_rate": 115200})
        settings = self.controller.get_settings()
        self.assertEqual(settings["baud_rate"], 115200)

    def test_handle_save_config_publishes_event(self):
        """Verify _handle_save_config publishes SETTINGS_CHANGED event."""
        self.controller._handle_save_config({"key": "value"})
        self.event_bus.publish.assert_called_with(
            UIEvent.SETTINGS_CHANGED.value, {"key": "value"},
        )

    def test_get_settings_returns_copy(self):
        """Verify get_settings returns a copy, not internal dict."""
        self.controller._settings["key"] = "value"
        settings = self.controller.get_settings()
        settings["new_key"] = "new_value"
        self.assertNotIn("new_key", self.controller._settings)


if __name__ == "__main__":
    unittest.main()
