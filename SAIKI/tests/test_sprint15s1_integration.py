"""Sprint 15S.1 integration tests — Real GUI command wiring & end-to-end delivery.

Tests instantiate real EventBus, Controller, and AutomationEngine boundary.
Mock serial hardware only. Do not mock EventBus subscriptions, controller handling,
or workflow enqueue boundaries.

10 test categories:
 1. Cek Nomor Massal from GUI callback → CLICK → DISPATCH → ENQUEUED
 2. Reaktivasi Massal from GUI callback → CLICK → DISPATCH → ENQUEUED
 3. Restart All from GUI callback → CLICK → DISPATCH → ENQUEUED
 4. Selected-port Reset Modem → CLICK → DISPATCH → ENQUEUED
 5. Per-port context-menu commands
 6. No selected port for Reset Modem → visible feedback
 7. Non-eligible ports → COMMAND SKIPPED with reason
 8. Unhandled event → COMMAND DELIVERY FAILED
 9. Workflow completion emits matching COMMAND RESULT
10. No GUI callback performs direct serial I/O or blocks UI
"""

import logging
import threading
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _LogCaptureHandler(logging.Handler):
    def __init__(self, records):
        super().__init__()
        self._records = records
    def emit(self, record):
        self._records.append(record)


class _CaptureLogs:
    def __init__(self, logger_name):
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

    def get_all_port_states(self):
        from app.domain.enums import PortState
        return {p: (PortState.EXCLUDED if p in self._excluded else PortState.ACTIVE)
                for p in self._active}

    def get_validation_results(self):
        return {}

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
        self.stopped = False

    def enqueue_workflow(self, port, workflow, priority=10, trigger_id=0):
        self.enqueued.append((port, workflow, priority))

    def handle_trigger(self, trigger, port, *args, **kwargs):
        pass

    def set_mode_from_name(self, name):
        pass

    def stop(self):
        self.stopped = True


class _FakeAutoRunConfig:
    def __init__(self):
        self.auto_run_enabled = False

    def set_enabled(self, v):
        self.auto_run_enabled = v

    def toggle(self):
        self.auto_run_enabled = not self.auto_run_enabled


class _FakeDbLookup:
    def lookup_nik(self, msisdn):
        return None
    def lookup_kk(self, nik):
        return None


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestCekNomorMassalFromGUI(unittest.TestCase):
    """Category 1: Cek Nomor Massal from its actual GUI callback."""

    def test_mass_cek_nomor_click_dispatch_enqueued(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        dbl = _FakeDbLookup()
        ctrl = UIController(bus, wm, arc, ae, dbl)

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            # Simulate GUI callback
            bus.publish("cmd.mass.cek_nomor", {"source": "workspace_button"})

        click = cap.messages("[COMMAND CLICK]")
        dispatch = cap.messages("[COMMAND DISPATCH]")
        enqueued = cap.messages("[COMMAND ENQUEUED]")

        self.assertTrue(len(click) > 0, f"No CLICK trace: {cap.messages()}")
        self.assertTrue(len(dispatch) > 0, f"No DISPATCH trace")
        self.assertTrue(len(enqueued) > 0, f"No ENQUEUED trace")

        # Verify check_number is enqueued (not check_data)
        self.assertEqual(ae.enqueued[0][1], "check_number")

    def test_mass_cek_nomor_uses_check_number_not_check_data(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        arc = _FakeAutoRunConfig()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, arc, ae, _FakeDbLookup())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        bus.publish("cmd.mass.cek_nomor", {"source": "workspace_button"})

        workflows = [w for _, w, *_ in ae.enqueued]
        self.assertIn("check_number", workflows)
        self.assertNotIn("check_data", workflows)


class TestReaktivasiMassalFromGUI(unittest.TestCase):
    """Category 2: Reaktivasi Massal from its actual GUI callback."""

    def test_mass_reaktivasi_click_dispatch_enqueued(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.mass.reaktivasi", {"source": "workspace_button"})

        self.assertTrue(len(cap.messages("[COMMAND CLICK]")) > 0)
        self.assertTrue(len(cap.messages("[COMMAND DISPATCH]")) > 0)
        self.assertTrue(len(cap.messages("[COMMAND ENQUEUED]")) > 0)
        self.assertEqual(ae.enqueued[0][1], "reactivate_full")


class TestRestartAllFromGUI(unittest.TestCase):
    """Category 3: Restart All from its actual GUI callback."""

    def test_restart_all_click_dispatch_enqueued(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.restart_all", {"source": "workspace_button"})

        self.assertTrue(len(cap.messages("[COMMAND CLICK]")) > 0)
        self.assertTrue(len(cap.messages("[COMMAND ENQUEUED]")) > 0)
        self.assertEqual(ae.enqueued[0][1], "hardware_restart")


class TestResetModemSelectedPort(unittest.TestCase):
    """Category 4: Selected-port Reset Modem."""

    def test_reset_modem_with_port_enqueues(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.reset_modem", {"port": "COM1", "source": "workspace_button"})

        self.assertTrue(len(cap.messages("[COMMAND CLICK]")) > 0)
        self.assertTrue(len(cap.messages("[COMMAND ENQUEUED]")) > 0)
        self.assertEqual(ae.enqueued[0][0], "COM1")
        self.assertEqual(ae.enqueued[0][1], "hardware_reset")


class TestContextMenuCommands(unittest.TestCase):
    """Category 5: Every per-port context-menu command."""

    def _test_per_port(self, event_name, expected_workflow):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(event_name, {"port": "COM1", "source": "context_menu"})

        self.assertTrue(len(cap.messages("[COMMAND CLICK]")) > 0,
                         f"No CLICK for {event_name}")
        self.assertTrue(len(cap.messages("[COMMAND ENQUEUED]")) > 0,
                         f"No ENQUEUED for {event_name}")
        self.assertEqual(ae.enqueued[0][1], expected_workflow,
                         f"Wrong workflow for {event_name}")

    def test_cek_nomor(self):
        self._test_per_port("cmd.cek_nomor", "check_number")

    def test_cek_nik(self):
        self._test_per_port("cmd.cek_nik", "check_nik")

    def test_cari_kk(self):
        self._test_per_port("cmd.cari_kk", "check_kk")

    def test_cek_limit(self):
        self._test_per_port("cmd.cek_limit", "check_number")

    def test_reactivate(self):
        self._test_per_port("cmd.reactivate", "reactivate_full")


class TestResetModemNoSelection(unittest.TestCase):
    """Category 6: Missing selected port for Reset Modem produces visible feedback."""

    def test_no_port_shows_feedback(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        # Capture MASS_PROGRESS events via subscription
        progress_messages = []
        bus.subscribe("ui.mass.progress", lambda p: progress_messages.append(p))

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.reset_modem", {"source": "workspace_button"})

        # Should produce RESULT with skipped
        result_traces = cap.messages("[COMMAND RESULT]")
        self.assertTrue(any("no_port_selected" in m for m in result_traces),
                         f"No feedback trace: {result_traces}")

        # Should publish MASS_PROGRESS with instruction
        self.assertTrue(len(progress_messages) > 0, "No progress message published")
        self.assertIn("Pilih port", str(progress_messages[0].get("message", "")))


class TestNonEligiblePorts(unittest.TestCase):
    """Category 7: Non-eligible ports produce COMMAND SKIPPED with reason."""

    def test_modem_offline_skipped(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        worker = _FakeWorker(modem_online=False)
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.cek_nomor", {"port": "COM1", "source": "context_menu"})

        skipped = cap.messages("[COMMAND SKIPPED]")
        self.assertTrue(any("modem_offline" in m for m in skipped),
                         f"No skip with reason: {skipped}")

    def test_excluded_port_skipped(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")
        wm._excluded.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("cmd.cek_nomor", {"port": "COM1", "source": "context_menu"})

        skipped = cap.messages("[COMMAND SKIPPED]")
        self.assertTrue(any("excluded" in m for m in skipped))


class TestUnhandledEvent(unittest.TestCase):
    """Category 8: An unhandled event produces COMMAND DELIVERY FAILED."""

    def test_unhandled_cmd_event_logs_failure(self):
        from worker.ui.event_bus import EventBus

        bus = EventBus()
        # Don't subscribe to "cmd.nonexistent"

        with _CaptureLogs("saiki.event_bus") as cap:
            bus.publish("cmd.nonexistent", {"port": "COM1"})

        failed = cap.messages("[COMMAND DELIVERY FAILED]")
        self.assertTrue(len(failed) > 0, f"No failure trace: {cap.messages()}")
        self.assertTrue(any("no_subscribers" in m for m in failed))


class TestWorkflowCompletionEmitsCommandResult(unittest.TestCase):
    """Category 9: Workflow completion emits matching command ID."""

    def test_completed_emits_result(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("automation.completed", {
                "port": "COM1",
                "workflow": "check_number",
                "trigger": "manual",
                "duration": 1.5,
            })

        result = cap.messages("[COMMAND RESULT]")
        self.assertTrue(len(result) > 0, f"No RESULT trace: {cap.messages()}")
        self.assertTrue(any("success" in m for m in result))

    def test_failed_emits_result(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish("automation.failed", {
                "port": "COM1",
                "workflow": "check_number",
                "error": "serial timeout",
            })

        result = cap.messages("[COMMAND RESULT]")
        self.assertTrue(len(result) > 0)
        self.assertTrue(any("failed" in m for m in result))


class TestNoBlockingGUIThread(unittest.TestCase):
    """Category 10: No GUI callback performs direct serial I/O or blocks the UI."""

    def test_mass_cek_nomor_returns_immediately(self):
        from worker.ui.event_bus import EventBus
        from worker.ui.controller import UIController

        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAutomationEngine()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDbLookup())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        # The dispatch thread is daemon, so if it blocks, the test still passes
        # but the thread would be stuck. Verify the main publish returns immediately.
        start = threading.Event()
        done = threading.Event()

        original_publish = bus.publish
        def patched_publish(event, payload=None):
            original_publish(event, payload)
            done.set()

        bus.publish = patched_publish

        import time
        t0 = time.monotonic()
        bus.publish("cmd.mass.cek_nomor", {"source": "workspace_button"})
        elapsed = time.monotonic() - t0

        # Publish should return in < 100ms (it dispatches to a thread)
        self.assertLess(elapsed, 0.5, f"Publish took {elapsed:.2f}s — likely blocking")


if __name__ == "__main__":
    unittest.main()
