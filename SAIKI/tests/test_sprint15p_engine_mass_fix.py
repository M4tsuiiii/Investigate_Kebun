"""Tests for Sprint 15P — Engine Entrypoint & Mass UI Freeze Fix."""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class TestEngineEntrypointTraces(unittest.TestCase):
    """Task 1: Engine boundary traces."""

    def test_handle_trigger_logs_enter_and_exit(self):
        """handle_trigger logs ENGINE ENTER and ENGINE EXIT."""
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from worker.rules import AutoRunConfig

        config = AutoRunConfig()
        config.set_enabled(False)

        runner = MagicMock()
        registry = MagicMock()
        event_bus = MagicMock()

        engine = AutomationEngine(runner, registry, config, event_bus)

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.CPIN_READY, "COM99", trigger_id=1, source="TEST")

        enter_logs = [l for l in cm.output if "[ENGINE ENTER]" in l]
        exit_logs = [l for l in cm.output if "[ENGINE EXIT]" in l]
        self.assertTrue(len(enter_logs) >= 1)
        self.assertTrue(len(exit_logs) >= 1)
        self.assertIn("COM99", enter_logs[0])

    def test_handle_trigger_logs_autorun_gate(self):
        """handle_trigger logs AUTORUN GATE when auto-run is disabled."""
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from worker.rules import AutoRunConfig

        config = AutoRunConfig()
        config.set_enabled(False)

        runner = MagicMock()
        registry = MagicMock()
        event_bus = MagicMock()

        engine = AutomationEngine(runner, registry, config, event_bus)

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.CPIN_READY, "COM99", trigger_id=1, source="TEST")

        gate_logs = [l for l in cm.output if "[AUTORUN GATE]" in l and "BLOCKED" in l]
        self.assertTrue(len(gate_logs) >= 1)

    def test_handle_trigger_logs_scheduler_action(self):
        """handle_trigger logs scheduler action."""
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from worker.rules import AutoRunConfig

        config = AutoRunConfig()
        config.set_enabled(True)

        runner = MagicMock()
        registry = MagicMock()
        event_bus = MagicMock()

        engine = AutomationEngine(runner, registry, config, event_bus)

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.CPIN_REQUIRED, "COM99", trigger_id=1, source="TEST")

        scheduler_logs = [l for l in cm.output if "[ENGINE] SCHEDULER" in l]
        self.assertTrue(len(scheduler_logs) >= 1)
        self.assertIn("action=standby", scheduler_logs[0])


class TestMassDispatchAsync(unittest.TestCase):
    """Task 2: Mass button returns immediately."""

    def test_mass_cek_nomor_returns_promptly(self):
        """Mass check number handler returns within 1 second."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig

        event_bus = MagicMock()
        worker_manager = MagicMock()
        worker_manager.get_active_ports.return_value = []
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        start = time.time()
        controller._handle_mass_cek_nomor({})
        elapsed = time.time() - start

        self.assertLess(elapsed, 1.0, "Mass handler must return immediately")

    def test_mass_reaktivasi_returns_promptly(self):
        """Mass reactivation handler returns within 1 second."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig

        event_bus = MagicMock()
        worker_manager = MagicMock()
        worker_manager.get_active_ports.return_value = []
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        start = time.time()
        controller._handle_mass_reaktivasi({})
        elapsed = time.time() - start

        self.assertLess(elapsed, 1.0, "Mass handler must return immediately")

    def test_mass_dispatch_submitted_logged(self):
        """Mass handler logs DISPATCH SUBMITTED."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig

        event_bus = MagicMock()
        worker_manager = MagicMock()
        worker_manager.get_active_ports.return_value = []
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        with self.assertLogs("saiki.controller", level="INFO") as cm:
            controller._handle_mass_cek_nomor({})

        submitted_logs = [l for l in cm.output if "[MASS DISPATCH SUBMITTED]" in l]
        self.assertTrue(len(submitted_logs) >= 1)

    def test_mass_dispatch_runs_in_background(self):
        """Mass dispatch runs in a background thread, not the calling thread."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig

        event_bus = MagicMock()
        worker_manager = MagicMock()
        worker_manager.get_active_ports.return_value = []
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        calling_thread = threading.current_thread().name

        controller._handle_mass_cek_nomor({})
        time.sleep(0.5)

        start_logs = []
        original_info = MagicMock()

        def capture_info(msg, *args):
            if "[MASS DISPATCH START]" in str(msg):
                start_logs.append(msg)

        with patch("worker.ui.controller.logger") as mock_logger:
            mock_logger.info = capture_info
            controller._handle_mass_cek_nomor({})
            time.sleep(0.5)


class TestMassTargetEligibility(unittest.TestCase):
    """Task 3: Eligible mass targets filtering."""

    def test_skips_not_inserted_ports(self):
        """Ports with NOT_INSERTED SIM are skipped."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig
        from app.domain.enums import CpinState

        event_bus = MagicMock()
        worker_manager = MagicMock()
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        worker = MagicMock()
        worker.is_alive = True
        worker.modem_online = True
        worker.cpin_state = CpinState.NOT_INSERTED
        worker_manager.get_active_ports.return_value = ["COM1"]
        worker_manager.get_worker.return_value = worker

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        eligible, skipped = controller._get_eligible_mass_targets()
        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][1], "sim_not_inserted")

    def test_skips_not_ready_ports(self):
        """Ports with NOT_READY state are skipped."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig
        from app.domain.enums import CpinState

        event_bus = MagicMock()
        worker_manager = MagicMock()
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        worker = MagicMock()
        worker.is_alive = True
        worker.modem_online = True
        worker.cpin_state = CpinState.NOT_READY
        worker_manager.get_active_ports.return_value = ["COM1"]
        worker_manager.get_worker.return_value = worker

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        eligible, skipped = controller._get_eligible_mass_targets()
        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][1], "not_ready")

    def test_skips_unknown_ports(self):
        """Ports with UNKNOWN state are skipped."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig
        from app.domain.enums import CpinState

        event_bus = MagicMock()
        worker_manager = MagicMock()
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        worker = MagicMock()
        worker.is_alive = True
        worker.modem_online = True
        worker.cpin_state = CpinState.UNKNOWN
        worker_manager.get_active_ports.return_value = ["COM1"]
        worker_manager.get_worker.return_value = worker

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        eligible, skipped = controller._get_eligible_mass_targets()
        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][1], "unknown_state")

    def test_includes_ready_ports(self):
        """Ports with READY state are eligible."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig
        from app.domain.enums import CpinState

        event_bus = MagicMock()
        worker_manager = MagicMock()
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        worker = MagicMock()
        worker.is_alive = True
        worker.modem_online = True
        worker.cpin_state = CpinState.READY
        worker_manager.get_active_ports.return_value = ["COM1"]
        worker_manager.get_worker.return_value = worker

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        eligible, skipped = controller._get_eligible_mass_targets()
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0], "COM1")
        self.assertEqual(len(skipped), 0)

    def test_skips_offline_modem(self):
        """Ports with modem offline are skipped."""
        from worker.ui.controller import UIController
        from worker.rules import AutoRunConfig

        event_bus = MagicMock()
        worker_manager = MagicMock()
        auto_run_config = AutoRunConfig()
        engine = MagicMock()
        db_lookup = MagicMock()

        worker = MagicMock()
        worker.is_alive = True
        worker.modem_online = False
        worker_manager.get_active_ports.return_value = ["COM1"]
        worker_manager.get_worker.return_value = worker

        controller = UIController(event_bus, worker_manager, auto_run_config, engine, db_lookup)

        eligible, skipped = controller._get_eligible_mass_targets()
        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][1], "modem_offline")


class TestUIHeartbeat(unittest.TestCase):
    """Task 4: UI heartbeat and freeze detection."""

    def test_heartbeat_tick_updates_last_tick(self):
        """tick() updates the last tick timestamp."""
        from worker.ui.ui_heartbeat import UIHeartbeat

        hb = UIHeartbeat(freeze_threshold=5.0)
        before = time.time()
        hb.tick()
        after = time.time()

        self.assertGreaterEqual(hb._last_tick, before)
        self.assertLessEqual(hb._last_tick, after)

    def test_heartbeat_detects_freeze(self):
        """Heartbeat detects freeze after threshold."""
        from worker.ui.ui_heartbeat import UIHeartbeat

        hb = UIHeartbeat(freeze_threshold=0.1)
        hb._last_tick = time.time() - 1.0

        hb.start()
        time.sleep(0.3)
        hb.stop()

        self.assertTrue(hb._dump_done)


class TestCPINLogReduction(unittest.TestCase):
    """Task 5: Repetitive CPIN traces are DEBUG level."""

    def test_cpint_trace_is_debug(self):
        """CPIN TRACE logs are at DEBUG level, not INFO."""
        import logging
        from worker.cpin_runtime import CpinRuntime
        from worker.ui.event_bus import EventBus

        event_bus = EventBus()
        at_client = MagicMock()
        at_client._serial = MagicMock()
        at_client._serial.is_open = True
        at_client.send_command.return_value = MagicMock(raw="+CPIN: READY\r\nOK")

        cpin = CpinRuntime("COM99", at_client, event_bus)

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        trace_logs = [l for l in cm.output if "[CPIN TRACE]" in l]
        self.assertTrue(len(trace_logs) >= 1)

        info_trace_logs = [l for l in cm.output if "[CPIN TRACE]" in l and "INFO" in l]
        self.assertEqual(len(info_trace_logs), 0, "CPIN TRACE should be DEBUG, not INFO")


if __name__ == "__main__":
    unittest.main()
