"""Tests for worker/ui/controller.py Sprint 3 changes."""

import unittest
from unittest.mock import MagicMock, patch

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

    subscribers = {}

    def track_subscribe(event_name, callback):
        subscribers[event_name] = callback

    event_bus.subscribe.side_effect = track_subscribe

    controller = UIController(
        event_bus, worker_manager, auto_run_config, automation_engine, db_lookup,
    )
    return controller, event_bus, worker_manager, auto_run_config, automation_engine, db_lookup, subscribers


class TestHandleMassReaktivasi(unittest.TestCase):
    """Tests for UIController._handle_mass_reaktivasi."""

    def test_enqueues_workflow_for_each_worker(self):
        """_handle_mass_reaktivasi should enqueue a workflow for each worker."""
        _, _, worker_manager, _, automation_engine, _, subs = _make_controller()
        workers = {"COM1": MagicMock(), "COM2": MagicMock()}
        worker_manager.workers = workers
        worker_manager.get_active_ports.return_value = ["COM1", "COM2"]

        subs[CommandEvent.MASS_REAKTIVASI.value]({})

        self.assertEqual(automation_engine.enqueue_workflow.call_count, 2)
        automation_engine.enqueue_workflow.assert_any_call("COM1", "reactivate_full", priority=10)
        automation_engine.enqueue_workflow.assert_any_call("COM2", "reactivate_full", priority=10)

    def test_sets_mode(self):
        """_handle_mass_reaktivasi should set automation engine mode."""
        _, _, worker_manager, _, automation_engine, _, subs = _make_controller()
        worker_manager.workers = {}
        worker_manager.get_active_ports.return_value = []

        subs[CommandEvent.MASS_REAKTIVASI.value]({})

        automation_engine.set_mode_from_name.assert_called_once_with("REACTIVATE_FULL")

    def test_publishes_mass_progress(self):
        """_handle_mass_reaktivasi should publish MASS_PROGRESS event."""
        _, event_bus, worker_manager, _, _, _, subs = _make_controller()
        worker_manager.workers = {"COM1": MagicMock()}
        worker_manager.get_active_ports.return_value = ["COM1"]

        subs[CommandEvent.MASS_REAKTIVASI.value]({})

        event_bus.publish.assert_any_call(UIEvent.MASS_PROGRESS.value, {
            "message": "Mass reactivation started on 1 ports",
            "total": 1,
        })


class TestHandleMassCekNomor(unittest.TestCase):
    """Tests for UIController._handle_mass_cek_nomor."""

    def test_enqueues_workflow_for_each_worker(self):
        """_handle_mass_cek_nomor should enqueue a workflow for each worker."""
        _, _, worker_manager, _, automation_engine, _, subs = _make_controller()
        workers = {"COM1": MagicMock()}
        worker_manager.workers = workers
        worker_manager.get_active_ports.return_value = ["COM1"]

        subs[CommandEvent.MASS_CEK_NOMOR.value]({})

        automation_engine.enqueue_workflow.assert_called_once_with("COM1", "check_data", priority=10)

    def test_sets_mode(self):
        """_handle_mass_cek_nomor should set automation engine mode."""
        _, _, worker_manager, _, automation_engine, _, subs = _make_controller()
        worker_manager.workers = {}
        worker_manager.get_active_ports.return_value = []

        subs[CommandEvent.MASS_CEK_NOMOR.value]({})

        automation_engine.set_mode_from_name.assert_called_once_with("CHECK_DATA")

    def test_publishes_mass_progress(self):
        """_handle_mass_cek_nomor should publish MASS_PROGRESS event."""
        _, event_bus, worker_manager, _, _, _, subs = _make_controller()
        worker_manager.workers = {"COM1": MagicMock(), "COM2": MagicMock()}
        worker_manager.get_active_ports.return_value = ["COM1", "COM2"]

        subs[CommandEvent.MASS_CEK_NOMOR.value]({})

        event_bus.publish.assert_any_call(UIEvent.MASS_PROGRESS.value, {
            "message": "Mass check started on 2 ports",
            "total": 2,
        })


class TestHandleReactivate(unittest.TestCase):
    """Tests for UIController._handle_reactivate."""

    def test_enqueues_workflow_for_port(self):
        """_handle_reactivate should enqueue a workflow via automation_engine."""
        _, _, _, _, automation_engine, _, subs = _make_controller()

        subs[CommandEvent.REACTIVATE.value]({"port": "COM1"})

        automation_engine.enqueue_workflow.assert_called_once_with("COM1", "reactivate_full", priority=5)

    def test_no_action_without_port(self):
        """_handle_reactivate should not enqueue without port."""
        _, _, _, _, automation_engine, _, subs = _make_controller()

        subs[CommandEvent.REACTIVATE.value]({})

        automation_engine.enqueue_workflow.assert_not_called()

    def test_no_action_for_unknown_port(self):
        """_handle_reactivate should still enqueue for any port string."""
        _, _, _, _, automation_engine, _, subs = _make_controller()

        subs[CommandEvent.REACTIVATE.value]({"port": "COM99"})

        automation_engine.enqueue_workflow.assert_called_once_with("COM99", "reactivate_full", priority=5)


class TestHandleDbLookupNik(unittest.TestCase):
    """Tests for UIController._handle_db_lookup_nik."""

    def test_calls_db_lookup_lookup_nik(self):
        """_handle_db_lookup_nik should call db_lookup.lookup_nik with msisdn."""
        _, _, _, _, _, db_lookup, subs = _make_controller()
        db_lookup.lookup_nik.return_value = {
            "msisdn": "08123456789",
            "nik": "3201234567890001",
            "masa_aktif": "2025-12-31",
        }

        subs[CommandEvent.DB_LOOKUP_NIK.value]({
            "port": "COM1",
            "msisdn": "08123456789",
        })

        db_lookup.lookup_nik.assert_called_once_with("08123456789")

    def test_publishes_db_lookup_result_event(self):
        """_handle_db_lookup_nik should publish DB_LOOKUP_RESULT event."""
        _, event_bus, _, _, _, db_lookup, subs = _make_controller()
        expected_result = {"nik": "3201234567890001", "msisdn": "08123456789", "masa_aktif": "2025-12-31"}
        db_lookup.lookup_nik.return_value = expected_result

        subs[CommandEvent.DB_LOOKUP_NIK.value]({
            "port": "COM1",
            "msisdn": "08123456789",
        })

        event_bus.publish.assert_any_call(UIEvent.DB_LOOKUP_RESULT.value, {
            "port": "COM1",
            "lookup_type": "nik",
            "msisdn": "08123456789",
            "result": expected_result,
        })

    def test_no_action_without_port(self):
        """_handle_db_lookup_nik should not call db_lookup without port."""
        _, _, _, _, _, db_lookup, subs = _make_controller()

        subs[CommandEvent.DB_LOOKUP_NIK.value]({"msisdn": "08123456789"})

        db_lookup.lookup_nik.assert_not_called()

    def test_no_action_without_msisdn(self):
        """_handle_db_lookup_nik should not call db_lookup without msisdn."""
        _, _, _, _, _, db_lookup, subs = _make_controller()

        subs[CommandEvent.DB_LOOKUP_NIK.value]({"port": "COM1"})

        db_lookup.lookup_nik.assert_not_called()

    def test_no_action_with_empty_payload(self):
        """_handle_db_lookup_nik should not call db_lookup with empty payload."""
        _, _, _, _, _, db_lookup, subs = _make_controller()

        subs[CommandEvent.DB_LOOKUP_NIK.value]({})

        db_lookup.lookup_nik.assert_not_called()

    def test_publishes_result_with_none_when_not_found(self):
        """_handle_db_lookup_nik should publish None result when lookup returns None."""
        _, event_bus, _, _, _, db_lookup, subs = _make_controller()
        db_lookup.lookup_nik.return_value = None

        subs[CommandEvent.DB_LOOKUP_NIK.value]({
            "port": "COM1",
            "msisdn": "99999999999",
        })

        event_bus.publish.assert_any_call(UIEvent.DB_LOOKUP_RESULT.value, {
            "port": "COM1",
            "lookup_type": "nik",
            "msisdn": "99999999999",
            "result": None,
        })


class TestHandleDbLookupKk(unittest.TestCase):
    """Tests for UIController._handle_db_lookup_kk."""

    def test_calls_db_lookup_lookup_kk(self):
        """_handle_db_lookup_kk should call db_lookup.lookup_kk with nik."""
        _, _, _, _, _, db_lookup, subs = _make_controller()
        db_lookup.lookup_kk.return_value = {
            "nik": "3201234567890001",
            "kk": "3201234567890002",
        }

        subs[CommandEvent.DB_LOOKUP_KK.value]({
            "port": "COM1",
            "nik": "3201234567890001",
        })

        db_lookup.lookup_kk.assert_called_once_with("3201234567890001")

    def test_publishes_db_lookup_result_event(self):
        """_handle_db_lookup_kk should publish DB_LOOKUP_RESULT event."""
        _, event_bus, _, _, _, db_lookup, subs = _make_controller()
        expected_result = {"nik": "3201234567890001", "kk": "3201234567890002"}
        db_lookup.lookup_kk.return_value = expected_result

        subs[CommandEvent.DB_LOOKUP_KK.value]({
            "port": "COM1",
            "nik": "3201234567890001",
        })

        event_bus.publish.assert_any_call(UIEvent.DB_LOOKUP_RESULT.value, {
            "port": "COM1",
            "lookup_type": "kk",
            "nik": "3201234567890001",
            "result": expected_result,
        })

    def test_no_action_without_port(self):
        """_handle_db_lookup_kk should not call db_lookup without port."""
        _, _, _, _, _, db_lookup, subs = _make_controller()

        subs[CommandEvent.DB_LOOKUP_KK.value]({"nik": "3201234567890001"})

        db_lookup.lookup_kk.assert_not_called()

    def test_no_action_without_nik(self):
        """_handle_db_lookup_kk should not call db_lookup without nik."""
        _, _, _, _, _, db_lookup, subs = _make_controller()

        subs[CommandEvent.DB_LOOKUP_KK.value]({"port": "COM1"})

        db_lookup.lookup_kk.assert_not_called()

    def test_no_action_with_empty_payload(self):
        """_handle_db_lookup_kk should not call db_lookup with empty payload."""
        _, _, _, _, _, db_lookup, subs = _make_controller()

        subs[CommandEvent.DB_LOOKUP_KK.value]({})

        db_lookup.lookup_kk.assert_not_called()

    def test_publishes_result_with_none_when_not_found(self):
        """_handle_db_lookup_kk should publish None result when lookup returns None."""
        _, event_bus, _, _, _, db_lookup, subs = _make_controller()
        db_lookup.lookup_kk.return_value = None

        subs[CommandEvent.DB_LOOKUP_KK.value]({
            "port": "COM1",
            "nik": "9999999999999999",
        })

        event_bus.publish.assert_any_call(UIEvent.DB_LOOKUP_RESULT.value, {
            "port": "COM1",
            "lookup_type": "kk",
            "nik": "9999999999999999",
            "result": None,
        })


class TestSprint3EventSubscriptions(unittest.TestCase):
    """Tests for Sprint 3 event subscriptions."""

    def test_subscribes_to_mass_reaktivasi(self):
        """_subscribe_events should subscribe to MASS_REAKTIVASI command."""
        controller, event_bus, _, _, _, _, _ = _make_controller()
        event_bus.subscribe.assert_any_call(
            CommandEvent.MASS_REAKTIVASI.value,
            controller._handle_mass_reaktivasi,
        )

    def test_subscribes_to_mass_cek_nomor(self):
        """_subscribe_events should subscribe to MASS_CEK_NOMOR command."""
        controller, event_bus, _, _, _, _, _ = _make_controller()
        event_bus.subscribe.assert_any_call(
            CommandEvent.MASS_CEK_NOMOR.value,
            controller._handle_mass_cek_nomor,
        )

    def test_subscribes_to_reactivate(self):
        """_subscribe_events should subscribe to REACTIVATE command."""
        controller, event_bus, _, _, _, _, _ = _make_controller()
        event_bus.subscribe.assert_any_call(
            CommandEvent.REACTIVATE.value,
            controller._handle_reactivate,
        )

    def test_subscribes_to_db_lookup_nik(self):
        """_subscribe_events should subscribe to DB_LOOKUP_NIK command."""
        controller, event_bus, _, _, _, _, _ = _make_controller()
        event_bus.subscribe.assert_any_call(
            CommandEvent.DB_LOOKUP_NIK.value,
            controller._handle_db_lookup_nik,
        )

    def test_subscribes_to_db_lookup_kk(self):
        """_subscribe_events should subscribe to DB_LOOKUP_KK command."""
        controller, event_bus, _, _, _, _, _ = _make_controller()
        event_bus.subscribe.assert_any_call(
            CommandEvent.DB_LOOKUP_KK.value,
            controller._handle_db_lookup_kk,
        )


class TestSprint3EventBusPublishing(unittest.TestCase):
    """Tests for Sprint 3 event bus publishing behavior."""

    def test_mass_reaktivasi_publishes_mass_progress(self):
        """Mass reactivation should publish MASS_PROGRESS event with message."""
        _, event_bus, worker_manager, _, _, _, subs = _make_controller()
        worker_manager.workers = {"COM1": MagicMock()}
        worker_manager.get_active_ports.return_value = ["COM1"]

        subs[CommandEvent.MASS_REAKTIVASI.value]({})

        event_bus.publish.assert_any_call(UIEvent.MASS_PROGRESS.value, {
            "message": "Mass reactivation started on 1 ports",
            "total": 1,
        })

    def test_mass_cek_nomor_publishes_mass_progress(self):
        """Mass cek nomor should publish MASS_PROGRESS event with message."""
        _, event_bus, worker_manager, _, _, _, subs = _make_controller()
        worker_manager.workers = {"COM1": MagicMock()}
        worker_manager.get_active_ports.return_value = ["COM1"]

        subs[CommandEvent.MASS_CEK_NOMOR.value]({})

        event_bus.publish.assert_any_call(UIEvent.MASS_PROGRESS.value, {
            "message": "Mass check started on 1 ports",
            "total": 1,
        })


if __name__ == "__main__":
    unittest.main()
