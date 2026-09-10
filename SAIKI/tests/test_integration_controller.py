"""Tests for UIController integration with AutomationEngine.

Verifies that UIController correctly routes events to AutomationEngine
and WorkerManager.
"""

import unittest
from unittest.mock import MagicMock, call

from worker.ui.event_bus import EventBus
from worker.ui.controller import UIController
from worker.ui.events import CommandEvent, UIEvent
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig
from worker.db_lookup import DbLookup
from automation.engine import AutomationEngine
from automation.policy import AutomationMode
from automation.triggers import Trigger
from automation.state import AutomationStatus
from workflow.registry import WorkflowRegistry


class TestControllerIntegration(unittest.TestCase):
    """Test UIController correctly routes to AutomationEngine."""

    def _make_controller(self):
        event_bus = EventBus()
        auto_run_config = AutoRunConfig()

        engine = MagicMock()
        state_mock = MagicMock()
        state_mock.status = AutomationStatus.IDLE
        state_mock.is_idle = True
        engine.get_state.return_value = state_mock

        worker_manager = MagicMock()
        worker_com1 = MagicMock()
        worker_com2 = MagicMock()
        worker_manager.workers = {"COM1": worker_com1, "COM2": worker_com2}
        worker_manager.get_active_ports.return_value = ["COM1", "COM2"]
        worker_manager.get_worker.side_effect = lambda port_id: worker_manager.workers.get(port_id)

        controller = UIController(
            event_bus=event_bus,
            worker_manager=worker_manager,
            auto_run_config=auto_run_config,
            automation_engine=engine,
            db_lookup=DbLookup(),
        )

        return controller, event_bus, engine, worker_manager, auto_run_config

    def test_mass_cek_nomor_routes_to_engine(self):
        """Mass cek nomor -> engine.enqueue_workflow for each port."""
        ctrl, event_bus, engine, wm, _ = self._make_controller()

        event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {})

        self.assertEqual(engine.enqueue_workflow.call_count, 2)

    def test_mass_reaktivasi_routes_to_engine(self):
        """Mass reaktivasi -> engine.enqueue_workflow for each port."""
        ctrl, event_bus, engine, wm, _ = self._make_controller()

        event_bus.publish(CommandEvent.MASS_REAKTIVASI.value, {})

        self.assertEqual(engine.enqueue_workflow.call_count, 2)

    def test_auto_run_toggle_updates_config(self):
        """Auto-run toggle -> config updated."""
        ctrl, event_bus, _, _, auto_run_config = self._make_controller()

        self.assertFalse(auto_run_config.auto_run_enabled)

        event_bus.publish(CommandEvent.AUTO_RUN_TOGGLE.value, {})
        self.assertTrue(auto_run_config.auto_run_enabled)

    def test_modem_online_forwards_to_engine(self):
        """Modem online -> engine.handle_trigger called."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish("modem.online", {"port": "COM1"})

        engine.handle_trigger.assert_called()

    def test_cpin_changed_forwards_to_engine(self):
        """CPIN READY -> engine.handle_trigger(CPIN_READY)."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish("cpin.transition", {
            "port": "COM1", "old": "UNKNOWN", "new": "READY",
        })

        engine.handle_trigger.assert_called()

    def test_individual_reactivate_routes_to_engine(self):
        """Individual reactivate -> engine.enqueue_workflow."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish(CommandEvent.REACTIVATE.value, {"port": "COM1"})

        engine.enqueue_workflow.assert_called_once()

    def test_mass_cek_nomor_sets_mode(self):
        """Mass cek nomor sets engine mode to CHECK_DATA."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {})

        engine.set_mode_from_name.assert_called_with("CHECK_DATA")

    def test_mass_reaktivasi_sets_mode(self):
        """Mass reaktivasi sets engine mode to REACTIVATE_FULL."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish(CommandEvent.MASS_REAKTIVASI.value, {})

        engine.set_mode_from_name.assert_called_with("REACTIVATE_FULL")

    def test_mass_cek_nomor_publishes_progress(self):
        """Mass cek nomor publishes MASS_PROGRESS UI event."""
        ctrl, event_bus, engine, wm, _ = self._make_controller()

        progress_events = []
        event_bus.subscribe(UIEvent.MASS_PROGRESS.value, lambda p: progress_events.append(p))

        event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {})

        self.assertGreater(len(progress_events), 0)
        self.assertIn("Mass check started", progress_events[0]["message"])

    def test_mass_reaktivasi_publishes_progress(self):
        """Mass reaktivasi publishes MASS_PROGRESS UI event."""
        ctrl, event_bus, engine, wm, _ = self._make_controller()

        progress_events = []
        event_bus.subscribe(UIEvent.MASS_PROGRESS.value, lambda p: progress_events.append(p))

        event_bus.publish(CommandEvent.MASS_REAKTIVASI.value, {})

        self.assertGreater(len(progress_events), 0)
        self.assertIn("Mass reactivation started", progress_events[0]["message"])

    def test_modem_offline_forwards_to_engine(self):
        """Modem offline -> engine.handle_trigger(MODEM_OFFLINE)."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish("modem.offline", {"port": "COM1"})

        engine.handle_trigger.assert_called()

    def test_cpin_pin_required_forwards_to_engine(self):
        """CPIN PIN_REQUIRED -> engine.handle_trigger(CPIN_REQUIRED)."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish("cpin.transition", {
            "port": "COM1", "old": "UNKNOWN", "new": "PIN_REQUIRED",
        })

        engine.handle_trigger.assert_called()

    def test_modem_appeared_creates_worker(self):
        """modem.appeared -> worker_manager.create_worker."""
        ctrl, event_bus, _, wm, _ = self._make_controller()

        event_bus.publish("modem.appeared", {"port": "COM5"})

        wm.create_worker.assert_called_with("COM5")

    def test_modem_disappeared_destroys_worker(self):
        """modem.disappeared -> worker_manager.destroy_worker."""
        ctrl, event_bus, _, wm, _ = self._make_controller()

        event_bus.publish("modem.disappeared", {"port": "COM1"})

        wm.destroy_worker.assert_called_with("COM1")

    def test_auto_run_toggle_publishes_changed_event(self):
        """Auto-run toggle publishes AUTO_RUN_CHANGED UI event."""
        ctrl, event_bus, _, _, _ = self._make_controller()

        events = []
        event_bus.subscribe(UIEvent.AUTO_RUN_CHANGED.value, lambda p: events.append(p))

        event_bus.publish(CommandEvent.AUTO_RUN_TOGGLE.value, {})

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["enabled"])

    def test_stop_all_stops_worker_manager_and_engine(self):
        """Stop all -> worker_manager.stop_all + engine.stop."""
        ctrl, event_bus, engine, wm, _ = self._make_controller()

        event_bus.publish(CommandEvent.STOP_ALL.value, {})

        wm.stop_all.assert_called_once()
        engine.stop.assert_called_once()

    def test_reset_modem_enqueues_hardware_reset(self):
        """Reset modem -> engine.enqueue_workflow("hardware_reset")."""
        ctrl, event_bus, engine, _, _ = self._make_controller()

        event_bus.publish(CommandEvent.RESET_MODEM.value, {"port": "COM1"})

        engine.handle_trigger.assert_called()
        engine.enqueue_workflow.assert_called()

    def test_port_on_starts_worker(self):
        """Port on -> worker.start()."""
        ctrl, event_bus, _, wm, _ = self._make_controller()

        event_bus.publish(CommandEvent.PORT_ON.value, {"port": "COM1"})

        wm.workers["COM1"].start.assert_called_once()

    def test_port_off_stops_worker(self):
        """Port off -> worker.stop()."""
        ctrl, event_bus, _, wm, _ = self._make_controller()

        event_bus.publish(CommandEvent.PORT_OFF.value, {"port": "COM1"})

        wm.workers["COM1"].stop.assert_called_once()

    def test_force_retry_calls_worker(self):
        """Force retry -> worker.force_retry()."""
        ctrl, event_bus, _, wm, _ = self._make_controller()

        event_bus.publish(CommandEvent.FORCE_RETRY.value, {"port": "COM1"})

        wm.workers["COM1"].force_retry.assert_called_once()

    def test_mass_check_enqueues_for_all_ports(self):
        """Mass cek nomor enqueues for every registered port."""
        ctrl, event_bus, engine, wm, _ = self._make_controller()
        wm.workers = {"COM1": MagicMock(), "COM2": MagicMock(), "COM3": MagicMock()}
        wm.get_active_ports.return_value = ["COM1", "COM2", "COM3"]

        event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {})

        self.assertEqual(engine.enqueue_workflow.call_count, 3)

    def test_mass_reaktivasi_enqueues_for_all_ports(self):
        """Mass reaktivasi enqueues for every registered port."""
        ctrl, event_bus, engine, wm, _ = self._make_controller()
        wm.workers = {"COM1": MagicMock(), "COM2": MagicMock()}
        wm.get_active_ports.return_value = ["COM1", "COM2"]

        event_bus.publish(CommandEvent.MASS_REAKTIVASI.value, {})

        self.assertEqual(engine.enqueue_workflow.call_count, 2)


if __name__ == "__main__":
    unittest.main()
