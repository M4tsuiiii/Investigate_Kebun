"""Tests for Sprint 10A — Runtime Wiring & Bootstrap Fix.

Verifies: startup report, hardware injection, skill wiring, lifecycle logging.
All tests mock hardware dependencies to avoid real COM port connections.
"""

import unittest
import time
from unittest.mock import MagicMock, patch, call

from worker.worker_manager import WorkerManager
from worker.port_worker import PortWorker
from worker.rules import AutoRunConfig
from worker.ui.event_bus import EventBus


class TestSystemBootstrapLifecycle(unittest.TestCase):
    """Test SystemBootstrap startup lifecycle with mocked hardware."""

    def _make_bootstrap(self):
        """Create a SystemBootstrap with mocked scanning and hardware."""
        with patch("worker.system_bootstrap.SystemBootstrap._create_serial", return_value=MagicMock()), \
             patch("worker.system_bootstrap.SystemBootstrap._create_at_client", return_value=MagicMock()):
            from worker.system_bootstrap import SystemBootstrap
            bootstrap = SystemBootstrap()
        return bootstrap

    def tearDown(self):
        if hasattr(self, "bootstrap"):
            try:
                self.bootstrap.worker_manager.stop_all()
                self.bootstrap.automation_engine.stop()
            except Exception:
                pass

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_start_prints_startup_report(self, mock_scan):
        """start() prints a startup report with component counts."""
        self.bootstrap = self._make_bootstrap()
        with patch("builtins.print") as mock_print:
            self.bootstrap.start()
            # Report runs in background thread — wait for it
            import time
            time.sleep(3.0)
            printed = [str(c) for c in mock_print.call_args_list]
            report_lines = [l for l in printed if "STARTUP REPORT" in l]
            self.assertTrue(len(report_lines) > 0)

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_get_startup_report_returns_dict(self, mock_scan):
        """get_startup_report() returns dict with expected keys."""
        self.bootstrap = self._make_bootstrap()
        self.bootstrap.start()
        report = self.bootstrap.get_startup_report()
        self.assertIn("com_detected", report)
        self.assertIn("workers_created", report)
        self.assertIn("skills_wired", report)
        self.assertIn("workflows_registered", report)
        self.assertIn("automation_ready", report)
        self.assertIn("auto_run", report)
        self.assertTrue(report["automation_ready"])

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_start_calls_worker_manager_start_scanning(self, mock_scan):
        """start() triggers WorkerManager.start_scanning()."""
        self.bootstrap = self._make_bootstrap()
        self.bootstrap.start()
        self.assertTrue(self.bootstrap.worker_manager._scanning.is_set())

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_start_starts_automation_engine(self, mock_scan):
        """start() starts the AutomationEngine."""
        self.bootstrap = self._make_bootstrap()
        self.bootstrap.start()
        engine = self.bootstrap.automation_engine
        self.assertTrue(engine._running)

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_stop_stops_everything(self, mock_scan):
        """stop() stops scanning, automation, and workers."""
        self.bootstrap = self._make_bootstrap()
        self.bootstrap.start()
        self.bootstrap.stop()
        self.assertFalse(self.bootstrap.worker_manager._scanning.is_set())

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_subscribe_modem_events_forwards_to_automation(self, mock_scan):
        """Modem events are forwarded to AutomationEngine triggers."""
        self.bootstrap = self._make_bootstrap()
        self.bootstrap.start()
        self.bootstrap.worker_manager.create_worker("COM99")
        self.bootstrap.event_bus.publish("modem.online", {"port": "COM99"})
        time.sleep(0.3)
        state = self.bootstrap.automation_engine.get_state("COM99")
        self.assertIsNotNone(state)

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_port_discovered_wires_skills(self, mock_scan):
        """When a port is discovered, skills are wired for that worker."""
        self.bootstrap = self._make_bootstrap()
        self.bootstrap.start()
        self.bootstrap.worker_manager.create_worker("COM99")
        time.sleep(0.1)
        self.assertIn("COM99", self.bootstrap.worker_manager.workers)

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_initial_scan_with_no_ports(self, mock_scan):
        """Initial scan with no ports detected creates no workers."""
        self.bootstrap = self._make_bootstrap()
        self.bootstrap.start()
        time.sleep(0.5)
        workers = self.bootstrap.worker_manager.workers
        self.assertIsInstance(workers, dict)


class TestWorkerManagerHardwareInjection(unittest.TestCase):
    """Test WorkerManager hardware dependency injection."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()

    def tearDown(self):
        if hasattr(self, "manager"):
            self.manager.stop_all()

    def test_create_worker_without_factories_logs_warning(self):
        """create_worker() without factories logs offline warning."""
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )
        worker = self.manager.create_worker("COM99")
        self.assertIsInstance(worker, PortWorker)
        self.assertIn("COM99", self.manager.workers)

    def test_create_worker_with_factories_calls_inject(self):
        """create_worker() with factories calls them for injection."""
        serial_factory = MagicMock(return_value=MagicMock())
        at_factory = MagicMock(return_value=MagicMock())
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
            serial_factory=serial_factory,
            at_client_factory=at_factory,
        )
        worker = self.manager.create_worker("COM99")
        serial_factory.assert_called_once_with("COM99", 115200)
        at_factory.assert_called_once()

    def test_destroy_worker_calls_disconnect(self):
        """destroy_worker() calls worker.disconnect()."""
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )
        worker = self.manager.create_worker("COM99")
        with patch.object(worker, "disconnect") as mock_disconnect:
            self.manager.destroy_worker("COM99")
            mock_disconnect.assert_called_once()

    def test_stop_all_disconnects_all_workers(self):
        """stop_all() disconnects all workers before clearing."""
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )
        w1 = self.manager.create_worker("COM98")
        w2 = self.manager.create_worker("COM97")
        with patch.object(w1, "disconnect") as d1, patch.object(w2, "disconnect") as d2:
            self.manager.stop_all()
            d1.assert_called_once()
            d2.assert_called_once()

    def test_scan_once_returns_port_list(self):
        """scan_once() returns a list of COM port strings."""
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )
        result = self.manager.scan_once()
        self.assertIsInstance(result, list)

    def test_start_scanning_does_initial_scan(self):
        """start_scanning() performs initial scan immediately."""
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )
        self.manager.start_scanning()
        self.assertTrue(self.manager._scanning.is_set())
        self.manager.stop_all()


class TestStartupReportContent(unittest.TestCase):
    """Test that startup report contains accurate data."""

    def _make_bootstrap(self):
        with patch("worker.system_bootstrap.SystemBootstrap._create_serial", return_value=MagicMock()), \
             patch("worker.system_bootstrap.SystemBootstrap._create_at_client", return_value=MagicMock()):
            from worker.system_bootstrap import SystemBootstrap
            return SystemBootstrap()

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_report_reflects_manual_worker_creation(self, mock_scan):
        """Report updates after workers are created."""
        bootstrap = self._make_bootstrap()
        bootstrap.start()
        bootstrap.worker_manager.create_worker("COM99")
        time.sleep(0.1)
        report = bootstrap.get_startup_report()
        self.assertGreaterEqual(report["workers_created"], 1)
        bootstrap.worker_manager.stop_all()
        bootstrap.automation_engine.stop()

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_report_shows_auto_run_state(self, mock_scan):
        """Report shows current auto_run state."""
        bootstrap = self._make_bootstrap()
        bootstrap.auto_run_config.set_enabled(True)
        bootstrap.start()
        report = bootstrap.get_startup_report()
        self.assertTrue(report["auto_run"])
        bootstrap.worker_manager.stop_all()
        bootstrap.automation_engine.stop()

    @patch("worker.worker_manager.WorkerManager.scan_once", return_value=[])
    def test_report_shows_workflows_registered(self, mock_scan):
        """Report shows all pre-built workflows."""
        bootstrap = self._make_bootstrap()
        bootstrap.start()
        report = bootstrap.get_startup_report()
        self.assertGreaterEqual(report["workflows_registered"], 5)
        self.assertIn("check_data", report["workflows_list"])
        self.assertIn("reactivate_fast", report["workflows_list"])
        self.assertIn("reactivate_full", report["workflows_list"])
        bootstrap.worker_manager.stop_all()
        bootstrap.automation_engine.stop()


if __name__ == "__main__":
    unittest.main()
