"""Sprint 15S tests — Command Delivery, Button Binding, Eligibility, Traces.

14 test categories:
 1. COMMAND_WORKFLOW_MAP completeness
 2. PER_PORT_COMMAND_MAP completeness
 3. Controller subscription completeness
 4. Button semantics: cek_nomor -> check_number (NOT check_data)
 5. Context menu mapping correctness
 6. Per-port command routing
 7. Eligibility: excluded port skipped
 8. Eligibility: dead worker skipped
 9. Eligibility: modem offline skipped
10. Eligibility: wrong CPIN skipped
11. Eligibility: connected serial required for HW commands
12. COMMAND CLICK/DISPATCH/ENQUEUED traces emitted
13. COMMAND SKIPPED trace with reason
14. UI processing status on command
"""

import logging
import unittest
from unittest.mock import MagicMock, patch, call
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _CaptureLogs:
    """Context manager that captures log records from a logger."""
    def __init__(self, logger_name):
        import logging
        self._logger = logging.getLogger(logger_name)
        self.records = []
        self._handler = _LogCaptureHandler(self.records)

    def __enter__(self):
        self._old_level = self._logger.level
        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *args):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._old_level)

    def messages(self, substring=None):
        msgs = [r.getMessage() for r in self.records]
        if substring:
            return [m for m in msgs if substring in m]
        return msgs


class _LogCaptureHandler(logging.Handler):
    def __init__(self, records):
        super().__init__()
        self._records = records
    def emit(self, record):
        self._records.append(record)


class _FakeEventBus:
    def __init__(self):
        self._subs = {}
        self._pub = []

    def subscribe(self, event, handler):
        self._subs.setdefault(event, []).append(handler)

    def publish(self, event, payload=None):
        self._pub.append((event, payload))
        for h in self._subs.get(event, []):
            h(payload or {})

    def published(self, event):
        """Return list of payloads for matching event name."""
        return [p for e, p in self._pub if e == event]


class _FakeWorkerManager:
    def __init__(self):
        self.workers = {}
        self._active = set()
        self._excluded = set()

    def get_worker(self, port):
        return self.workers.get(port)

    def get_active_ports(self):
        return list(self._active)

    def get_port_state(self, port):
        from app.domain.enums import PortState
        if port in self._excluded:
            return PortState.EXCLUDED
        return PortState.ACTIVE if port in self._active else PortState.IDLE

    def exclude_port(self, port):
        self._excluded.add(port)
        self._active.discard(port)

    def include_port(self, port):
        self._excluded.discard(port)
        self._active.add(port)

    def stop_all(self):
        pass

    def create_worker(self, port):
        pass

    def destroy_worker(self, port):
        self.workers.pop(port, None)
        self._active.discard(port)


class _FakeWorker:
    def __init__(self, alive=True, modem_online=True, cpin="READY", connected=True):
        self.is_alive = alive
        self.modem_online = modem_online
        from app.domain.enums import CpinState
        self.cpin_state = getattr(CpinState, cpin, CpinState.UNKNOWN)
        self.is_connected = connected
        self._started = False
        self._stopped = False

    def start(self):
        self._started = True

    def stop(self):
        self._stopped = True

    def force_retry(self):
        pass

    def set_modem_online(self, v):
        self.modem_online = v


class _FakeAutomationEngine:
    def __init__(self):
        self.enqueued = []
        self.triggers = []

    def enqueue_workflow(self, port, workflow, priority=10, trigger_id=0):
        self.enqueued.append((port, workflow, priority, trigger_id))

    def handle_trigger(self, trigger, port, *args, **kwargs):
        self.triggers.append((trigger, port))

    def set_mode_from_name(self, name):
        pass

    def stop(self):
        pass


class _FakeDbLookup:
    def lookup_nik(self, msisdn):
        return None

    def lookup_kk(self, nik):
        return None


class _FakeAutoRunConfig:
    def __init__(self):
        self.auto_run_enabled = False

    def set_enabled(self, v):
        self.auto_run_enabled = v

    def toggle(self):
        self.auto_run_enabled = not self.auto_run_enabled


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCommandWorkflowMap(unittest.TestCase):
    """Category 1: COMMAND_ROUTES completeness."""

    def test_check_number_maps_to_atomic(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertEqual(ROUTE_BY_EVENT["cmd.cek_nomor"][2], "check_number")

    def test_check_status_maps_to_atomic(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertIn("cmd.cek_status", ROUTE_BY_EVENT)  # Sprint 15S.2: now routed
        self.assertEqual(ROUTE_BY_EVENT["cmd.cek_status"][2], "check_status")

    def test_check_nik_maps_to_atomic(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertEqual(ROUTE_BY_EVENT["cmd.cek_nik"][2], "check_nik")

    def test_check_kk_maps_to_atomic(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertEqual(ROUTE_BY_EVENT["cmd.cari_kk"][2], "check_kk")

    def test_reaktivasi_maps_to_full(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertEqual(ROUTE_BY_EVENT["cmd.reactivate"][2], "reactivate_full")

    def test_hardware_restart_maps(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertEqual(ROUTE_BY_EVENT["cmd.restart_all"][2], "hardware_restart")

    def test_hardware_reset_maps(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        self.assertEqual(ROUTE_BY_EVENT["cmd.reset_modem"][2], "hardware_reset")

    def test_no_composite_in_routes(self):
        from worker.ui.controller import ROUTE_BY_EVENT
        for event, route in ROUTE_BY_EVENT.items():
            self.assertNotEqual(route[2], "check_data", f"check_data found in route {event}")


class TestPerPortCommandMap(unittest.TestCase):
    """Category 2: PER_PORT_COMMAND_MAP completeness."""

    def test_cek_nomor_maps_to_check_number(self):
        from worker.ui.controller import PER_PORT_COMMAND_MAP
        self.assertEqual(PER_PORT_COMMAND_MAP["cmd.cek_nomor"], "check_number")

    def test_cek_nik_maps_to_check_nik(self):
        from worker.ui.controller import PER_PORT_COMMAND_MAP
        self.assertEqual(PER_PORT_COMMAND_MAP["cmd.cek_nik"], "check_nik")

    def test_cari_kk_maps_to_check_kk(self):
        from worker.ui.controller import PER_PORT_COMMAND_MAP
        self.assertEqual(PER_PORT_COMMAND_MAP["cmd.cari_kk"], "check_kk")

    def test_cek_limit_maps_to_check_number(self):
        from worker.ui.controller import PER_PORT_COMMAND_MAP
        self.assertEqual(PER_PORT_COMMAND_MAP["cmd.cek_limit"], "check_number")

    def test_reactivate_maps_to_reactivate_full(self):
        from worker.ui.controller import PER_PORT_COMMAND_MAP
        self.assertEqual(PER_PORT_COMMAND_MAP["cmd.reactivate"], "reactivate_full")

    def test_reset_modem_maps(self):
        from worker.ui.controller import PER_PORT_COMMAND_MAP
        self.assertEqual(PER_PORT_COMMAND_MAP["cmd.reset_modem"], "hardware_reset")

    def test_force_retry_maps(self):
        from worker.ui.controller import PER_PORT_COMMAND_MAP
        self.assertIsNone(PER_PORT_COMMAND_MAP["cmd.force_retry"])


class TestControllerSubscriptions(unittest.TestCase):
    """Category 3: Controller subscription completeness."""

    def _make_controller(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)
        return ctrl, bus

    def test_cek_nomor_subscribed(self):
        _, bus = self._make_controller()
        self.assertIn("cmd.cek_nomor", bus._subs)

    def test_cek_nik_subscribed(self):
        _, bus = self._make_controller()
        self.assertIn("cmd.cek_nik", bus._subs)

    def test_cari_kk_subscribed(self):
        _, bus = self._make_controller()
        self.assertIn("cmd.cari_kk", bus._subs)

    def test_cek_limit_subscribed(self):
        _, bus = self._make_controller()
        self.assertIn("cmd.cek_limit", bus._subs)

    def test_reactivate_subscribed(self):
        _, bus = self._make_controller()
        self.assertIn("cmd.reactivate", bus._subs)

    def test_mass_cek_nomor_subscribed(self):
        _, bus = self._make_controller()
        self.assertIn("cmd.mass.cek_nomor", bus._subs)

    def test_mass_reaktivasi_subscribed(self):
        _, bus = self._make_controller()
        self.assertIn("cmd.mass.reaktivasi", bus._subs)


class TestButtonSemantics(unittest.TestCase):
    """Category 4: cek_nomor → check_number (NOT check_data)."""

    def test_mass_cek_nomor_enqueues_check_number(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        import threading
        with patch.object(threading, "Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_instance.start = MagicMock()
            mock_thread.return_value = mock_instance

            bus.publish("cmd.mass.cek_nomor", {})

            mock_instance.start.assert_called_once()
            target_func = mock_thread.call_args.kwargs.get("target") or mock_thread.call_args[0][0]

            target_func()

        workflows = [w for _, w, *_ in ae.enqueued]
        self.assertIn("check_number", workflows)
        self.assertNotIn("check_data", workflows)


class TestContextMenuMapping(unittest.TestCase):
    """Category 5: Context menu mapping correctness."""

    def test_cek_nomor_uses_per_port_event(self):
        from worker.ui.context_menu import PortContextMenu
        for item in PortContextMenu.MENU_ITEMS:
            if item and item[0] == "Cek Nomor":
                self.assertEqual(item[1].value, "cmd.cek_nomor")
                break

    def test_cek_nik_uses_per_port_event(self):
        from worker.ui.context_menu import PortContextMenu
        for item in PortContextMenu.MENU_ITEMS:
            if item and item[0] == "Cek NIK":
                self.assertEqual(item[1].value, "cmd.cek_nik")
                break

    def test_cari_kk_uses_per_port_event(self):
        from worker.ui.context_menu import PortContextMenu
        for item in PortContextMenu.MENU_ITEMS:
            if item and item[0] == "Cari / Ambil KK":
                self.assertEqual(item[1].value, "cmd.cari_kk")
                break

    def test_cek_limit_uses_cek_limit_event(self):
        from worker.ui.context_menu import PortContextMenu
        for item in PortContextMenu.MENU_ITEMS:
            if item and item[0] == "Cek Limit":
                self.assertEqual(item[1].value, "cmd.cek_limit")
                break

    def test_no_mass_events_in_context_menu(self):
        from worker.ui.context_menu import PortContextMenu
        from worker.ui.events import CommandEvent
        for item in PortContextMenu.MENU_ITEMS:
            if item:
                self.assertNotIn(item[1], [CommandEvent.MASS_CEK_NOMOR, CommandEvent.MASS_REAKTIVASI])


class TestPerPortCommandRouting(unittest.TestCase):
    """Category 6: Per-port command routing through controller."""

    def _make_controller(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)
        return ctrl, bus, wm, ae

    def test_cek_nomor_enqueues_check_number(self):
        ctrl, bus, wm, ae = self._make_controller()
        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.cek_nomor", {"port": "COM1"})
        workflows = [w for _, w, *_ in ae.enqueued]
        self.assertIn("check_number", workflows)

    def test_cek_nik_enqueues_check_nik(self):
        ctrl, bus, wm, ae = self._make_controller()
        worker = _FakeWorker()
        wm.workers["COM2"] = worker
        wm._active.add("COM2")

        bus.publish("cmd.cek_nik", {"port": "COM2"})
        workflows = [w for _, w, *_ in ae.enqueued]
        self.assertIn("check_nik", workflows)

    def test_cari_kk_enqueues_check_kk(self):
        ctrl, bus, wm, ae = self._make_controller()
        worker = _FakeWorker()
        wm.workers["COM3"] = worker
        wm._active.add("COM3")

        bus.publish("cmd.cari_kk", {"port": "COM3"})
        workflows = [w for _, w, *_ in ae.enqueued]
        self.assertIn("check_kk", workflows)

    def test_cek_limit_enqueues_check_number(self):
        ctrl, bus, wm, ae = self._make_controller()
        worker = _FakeWorker()
        wm.workers["COM4"] = worker
        wm._active.add("COM4")

        bus.publish("cmd.cek_limit", {"port": "COM4"})
        workflows = [w for _, w, *_ in ae.enqueued]
        self.assertIn("check_number", workflows)

    def test_reactivate_enqueues_reactivate_full(self):
        ctrl, bus, wm, ae = self._make_controller()
        worker = _FakeWorker()
        wm.workers["COM5"] = worker
        wm._active.add("COM5")

        bus.publish("cmd.reactivate", {"port": "COM5"})
        workflows = [w for _, w, *_ in ae.enqueued]
        self.assertIn("reactivate_full", workflows)

    def test_no_port_publishes_skipped(self):
        ctrl, bus, wm, ae = self._make_controller()
        bus.publish("cmd.cek_nomor", {})
        self.assertEqual(len(ae.enqueued), 0)


class TestEligibilityExcluded(unittest.TestCase):
    """Category 7: Excluded port is skipped."""

    def test_excluded_port_skipped(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")
        wm._excluded.add("COM1")

        bus.publish("cmd.cek_nomor", {"port": "COM1"})
        self.assertEqual(len(ae.enqueued), 0)
        mass_events = bus.published("ui.mass.progress")
        skipped = [p for p in mass_events if isinstance(p, dict) and "Skipped" in str(p.get("message", ""))]
        self.assertTrue(len(skipped) > 0, f"No skip event published. All published: {mass_events}")


class TestEligibilityDeadWorker(unittest.TestCase):
    """Category 8: Dead worker is skipped."""

    def test_dead_worker_skipped(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker(alive=False)
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.cek_nomor", {"port": "COM1"})
        self.assertEqual(len(ae.enqueued), 0)


class TestEligibilityModemOffline(unittest.TestCase):
    """Category 9: Modem offline is skipped."""

    def test_modem_offline_skipped(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker(modem_online=False)
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.cek_nomor", {"port": "COM1"})
        self.assertEqual(len(ae.enqueued), 0)


class TestEligibilityWrongCpin(unittest.TestCase):
    """Category 10: Wrong CPIN state is skipped."""

    def _test_cpin_skip(self, cpin):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker(cpin=cpin)
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.cek_nomor", {"port": "COM1"})
        self.assertEqual(len(ae.enqueued), 0, f"Expected skip for CPIN={cpin}")

    def test_not_inserted_skipped(self):
        self._test_cpin_skip("NOT_INSERTED")

    def test_not_ready_skipped(self):
        self._test_cpin_skip("NOT_READY")

    def test_unknown_skipped(self):
        self._test_cpin_skip("UNKNOWN")

    def test_pin_required_skipped(self):
        self._test_cpin_skip("PIN_REQUIRED")

    def test_ready_not_skipped(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker(cpin="READY")
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.cek_nomor", {"port": "COM1"})
        self.assertGreater(len(ae.enqueued), 0)


class TestEligibilityHwRequiresSerial(unittest.TestCase):
    """Category 11: HW commands require connected serial."""

    def test_disconnected_skipped_for_reset(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker(connected=False)
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.reset_modem", {"port": "COM1"})
        self.assertEqual(len(ae.enqueued), 0)

    def test_connected_not_skipped_for_reset(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker(connected=True)
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.reset_modem", {"port": "COM1"})
        self.assertGreater(len(ae.enqueued), 0)


class TestCommandTraces(unittest.TestCase):
    """Category 12: COMMAND CLICK/DISPATCH/ENQUEUED traces emitted."""

    def _make_controller(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)
        return ctrl, bus, wm, ae

    def test_command_click_emitted(self):
        ctrl, bus, wm, ae = self._make_controller()
        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.cek_nomor", {"port": "COM1"})

        click_traces = cap.messages("[COMMAND CLICK]")
        self.assertTrue(len(click_traces) > 0, f"No COMMAND CLICK trace. All logs: {cap.messages()}")

    def test_command_enqueued_emitted(self):
        ctrl, bus, wm, ae = self._make_controller()
        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.cek_nomor", {"port": "COM1"})

        enqueue_traces = cap.messages("[COMMAND ENQUEUED]")
        self.assertTrue(len(enqueue_traces) > 0, f"No COMMAND ENQUEUED trace. All logs: {cap.messages()}")


class TestCommandSkippedTrace(unittest.TestCase):
    """Category 13: COMMAND SKIPPED trace with reason."""

    def test_skipped_trace_with_reason(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker(modem_online=False)
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.cek_nomor", {"port": "COM1"})

        skipped = cap.messages("[COMMAND SKIPPED]")
        has_reason = any("modem_offline" in m for m in skipped)
        self.assertTrue(has_reason, f"No skipped trace with modem_offline. Traces: {skipped}")


class TestUIProcessingStatus(unittest.TestCase):
    """Category 14: UI processing status on command."""

    def test_port_update_processing_published(self):
        from worker.ui.controller import UIController
        bus = _FakeEventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.cek_nomor", {"port": "COM1"})

        updates = [p for p in bus.published("ui.port.update")
                   if isinstance(p, dict) and p.get("port") == "COM1" and p.get("status") == "PROCESSING"]
        self.assertTrue(len(updates) > 0)


if __name__ == "__main__":
    unittest.main()
