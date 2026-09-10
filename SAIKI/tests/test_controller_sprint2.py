"""Tests for worker/ui/controller.py Sprint 2 changes."""

import unittest
from unittest.mock import MagicMock, patch, call

from worker.ui.controller import UIController
from worker.ui.events import CommandEvent, UIEvent
from worker.rules import AutoRunConfig
from worker.db_lookup import DbLookup


def _make_controller():
    """Helper to create UIController with mocked dependencies."""
    event_bus = MagicMock()
    worker_manager = MagicMock()
    auto_run_config = AutoRunConfig()
    automation_engine = MagicMock()
    db_lookup = MagicMock(spec=DbLookup)

    # Track subscribers so we can simulate events
    subscribers = {}
    def track_subscribe(event_name, callback):
        subscribers[event_name] = callback

    event_bus.subscribe.side_effect = track_subscribe

    controller = UIController(event_bus, worker_manager, auto_run_config, automation_engine, db_lookup)
    return controller, event_bus, worker_manager, auto_run_config, automation_engine, subscribers


class TestAutoRunToggle(unittest.TestCase):
    """Tests for UIController._handle_auto_run_toggle."""

    def test_sets_enabled_from_payload(self):
        """_handle_auto_run_toggle should set enabled when payload contains 'enabled'."""
        controller, _, _, auto_run_config, _, subs = _make_controller()

        subs[CommandEvent.AUTO_RUN_TOGGLE.value]({"enabled": True})

        self.assertTrue(auto_run_config.auto_run_enabled)

    def test_sets_disabled_from_payload(self):
        """_handle_auto_run_toggle should disable when payload contains enabled=False."""
        controller, _, _, auto_run_config, _, subs = _make_controller()

        subs[CommandEvent.AUTO_RUN_TOGGLE.value]({"enabled": False})

        self.assertFalse(auto_run_config.auto_run_enabled)

    def test_toggles_when_no_payload(self):
        """_handle_auto_run_toggle should toggle when payload has no 'enabled' key."""
        controller, _, _, auto_run_config, _, subs = _make_controller()

        subs[CommandEvent.AUTO_RUN_TOGGLE.value]({})

        self.assertTrue(auto_run_config.auto_run_enabled)

    def test_toggles_again_on_second_call(self):
        """_handle_auto_run_toggle should toggle back on second call."""
        controller, _, _, auto_run_config, _, subs = _make_controller()

        subs[CommandEvent.AUTO_RUN_TOGGLE.value]({})
        subs[CommandEvent.AUTO_RUN_TOGGLE.value]({})

        self.assertFalse(auto_run_config.auto_run_enabled)

    def test_publishes_auto_run_changed(self):
        """_handle_auto_run_toggle should publish AUTO_RUN_CHANGED event."""
        controller, event_bus, _, _, _, subs = _make_controller()

        subs[CommandEvent.AUTO_RUN_TOGGLE.value]({"enabled": True})

        event_bus.publish.assert_any_call(UIEvent.AUTO_RUN_CHANGED.value, {
            "enabled": True,
        })


class TestModemOnline(unittest.TestCase):
    """Tests for UIController._handle_modem_online."""

    def test_calls_worker_set_modem_online_true(self):
        """_handle_modem_online should call worker.set_modem_online(True)."""
        controller, _, worker_manager, _, _, subs = _make_controller()

        worker = MagicMock()
        worker_manager.get_worker.return_value = worker

        subs["modem.online"]({"port": "COM1"})

        worker_manager.get_worker.assert_called_with("COM1")
        worker.set_modem_online.assert_called_once_with(True)


class TestModemOffline(unittest.TestCase):
    """Tests for UIController._handle_modem_offline."""

    def test_calls_worker_set_modem_online_false(self):
        """_handle_modem_offline should call worker.set_modem_online(False)."""
        controller, _, worker_manager, _, _, subs = _make_controller()

        worker = MagicMock()
        worker_manager.get_worker.return_value = worker

        subs["modem.offline"]({"port": "COM1"})

        worker_manager.get_worker.assert_called_with("COM1")
        worker.set_modem_online.assert_called_once_with(False)

    def test_missing_port_no_error(self):
        """_handle_modem_offline should not crash with missing port."""
        controller, _, worker_manager, _, _, subs = _make_controller()
        subs["modem.offline"]({})
        worker_manager.get_worker.assert_not_called()


class TestModemAppeared(unittest.TestCase):
    """Tests for UIController._handle_modem_appeared."""

    def test_creates_worker(self):
        """_handle_modem_appeared should call create_worker."""
        controller, _, worker_manager, _, _, subs = _make_controller()

        subs["modem.appeared"]({"port": "COM3"})

        worker_manager.create_worker.assert_called_once_with("COM3")

    def test_missing_port_no_error(self):
        """_handle_modem_appeared should not crash with missing port."""
        controller, _, worker_manager, _, _, subs = _make_controller()
        subs["modem.appeared"]({})
        worker_manager.create_worker.assert_not_called()


class TestModemDisappeared(unittest.TestCase):
    """Tests for UIController._handle_modem_disappeared."""

    def test_destroys_worker(self):
        """_handle_modem_disappeared should call destroy_worker."""
        controller, _, worker_manager, _, _, subs = _make_controller()

        subs["modem.disappeared"]({"port": "COM3"})

        worker_manager.destroy_worker.assert_called_once_with("COM3")

    def test_missing_port_no_error(self):
        """_handle_modem_disappeared should not crash with missing port."""
        controller, _, worker_manager, _, _, subs = _make_controller()
        subs["modem.disappeared"]({})
        worker_manager.destroy_worker.assert_not_called()


class TestEventSubscription(unittest.TestCase):
    """Tests for UIController._subscribe_events."""

    def test_subscribes_to_all_modem_events(self):
        """_subscribe_events should subscribe to modem.online, offline, appeared, disappeared."""
        controller, event_bus, _, _, _, _ = _make_controller()

        event_bus.subscribe.assert_any_call("modem.online", controller._handle_modem_online)
        event_bus.subscribe.assert_any_call("modem.offline", controller._handle_modem_offline)
        event_bus.subscribe.assert_any_call("modem.appeared", controller._handle_modem_appeared)
        event_bus.subscribe.assert_any_call("modem.disappeared", controller._handle_modem_disappeared)

    def test_subscribes_to_auto_run_toggle(self):
        """_subscribe_events should subscribe to auto_run_toggle command."""
        controller, event_bus, _, _, _, _ = _make_controller()

        event_bus.subscribe.assert_any_call(
            CommandEvent.AUTO_RUN_TOGGLE.value,
            controller._handle_auto_run_toggle,
        )

    def test_subscribes_to_port_commands(self):
        """_subscribe_events should subscribe to port on/off commands."""
        controller, event_bus, _, _, _, _ = _make_controller()

        event_bus.subscribe.assert_any_call(
            CommandEvent.PORT_ON.value, controller._handle_port_on
        )
        event_bus.subscribe.assert_any_call(
            CommandEvent.PORT_OFF.value, controller._handle_port_off
        )


class TestPortActions(unittest.TestCase):
    """Tests for port action handlers."""

    def test_handle_port_on_starts_worker(self):
        """_handle_port_on should start the worker."""
        controller, _, worker_manager, _, _, subs = _make_controller()

        worker = MagicMock()
        worker_manager.get_worker.return_value = worker

        subs[CommandEvent.PORT_ON.value]({"port": "COM1"})
        worker.start.assert_called_once()

    def test_handle_port_off_stops_worker(self):
        """_handle_port_off should stop the worker."""
        controller, _, worker_manager, _, _, subs = _make_controller()

        worker = MagicMock()
        worker_manager.get_worker.return_value = worker

        subs[CommandEvent.PORT_OFF.value]({"port": "COM1"})
        worker.stop.assert_called_once()

    def test_handle_reset_modem_uses_automation_engine(self):
        """_handle_reset_modem should use automation_engine for hardware reset."""
        controller, _, worker_manager, _, automation_engine, subs = _make_controller()

        worker = MagicMock()
        worker_manager.get_worker.return_value = worker

        subs[CommandEvent.RESET_MODEM.value]({"port": "COM1"})
        automation_engine.handle_trigger.assert_called_once()
        automation_engine.enqueue_workflow.assert_called_once_with("COM1", "hardware_reset", priority=5)

    def test_handle_force_retry_sets_force_retry(self):
        """_handle_force_retry should call worker.force_retry()."""
        controller, _, worker_manager, _, _, subs = _make_controller()

        worker = MagicMock()
        worker_manager.get_worker.return_value = worker

        subs[CommandEvent.FORCE_RETRY.value]({"port": "COM1"})
        worker.force_retry.assert_called_once()

    def test_handle_mass_reaktivasi_delegates_to_automation_engine(self):
        """_handle_mass_reaktivasi should enqueue workflows via automation_engine."""
        controller, _, worker_manager, _, automation_engine, subs = _make_controller()

        worker_manager.workers = {"COM1": MagicMock(), "COM2": MagicMock()}
        worker_manager.get_active_ports.return_value = ["COM1", "COM2"]

        subs[CommandEvent.MASS_REAKTIVASI.value]({})
        self.assertEqual(automation_engine.enqueue_workflow.call_count, 2)
        automation_engine.enqueue_workflow.assert_any_call("COM1", "reactivate_full", priority=10)
        automation_engine.enqueue_workflow.assert_any_call("COM2", "reactivate_full", priority=10)

    def test_handle_mass_cek_nomor_delegates_to_automation_engine(self):
        """_handle_mass_cek_nomor should enqueue workflows via automation_engine."""
        controller, _, worker_manager, _, automation_engine, subs = _make_controller()

        worker_manager.workers = {"COM1": MagicMock(), "COM2": MagicMock()}
        worker_manager.get_active_ports.return_value = ["COM1", "COM2"]

        subs[CommandEvent.MASS_CEK_NOMOR.value]({})
        self.assertEqual(automation_engine.enqueue_workflow.call_count, 2)
        automation_engine.enqueue_workflow.assert_any_call("COM1", "check_data", priority=10)
        automation_engine.enqueue_workflow.assert_any_call("COM2", "check_data", priority=10)


class TestSaveConfig(unittest.TestCase):
    """Tests for _handle_save_config."""

    def test_updates_settings(self):
        """_handle_save_config should store settings."""
        controller, _, _, _, _, subs = _make_controller()

        subs[CommandEvent.SAVE_CONFIG.value]({"baud_rate": 115200})

        self.assertEqual(controller.get_settings(), {"baud_rate": 115200})

    def test_publishes_settings_changed(self):
        """_handle_save_config should publish SETTINGS_CHANGED event."""
        controller, event_bus, _, _, _, subs = _make_controller()

        subs[CommandEvent.SAVE_CONFIG.value]({"baud_rate": 115200})

        event_bus.publish.assert_any_call(UIEvent.SETTINGS_CHANGED.value, {
            "baud_rate": 115200,
        })


if __name__ == "__main__":
    unittest.main()
