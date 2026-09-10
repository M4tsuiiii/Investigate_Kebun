"""Tests for ModemMonitor — COM port appearance/disappearance detection."""

import unittest
import threading
import time
from unittest.mock import MagicMock, patch

from worker.modem_monitor import ModemMonitor


class TestModemMonitorLifecycle(unittest.TestCase):
    """Test ModemMonitor start/stop thread lifecycle."""

    def setUp(self):
        """Create fresh ModemMonitor before each test."""
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(event_bus=self.event_bus, check_interval=0.1)

    def tearDown(self):
        """Stop monitor after each test."""
        self.monitor.stop()

    def test_start_creates_daemon_thread(self):
        """Verify start() creates a daemon thread."""
        self.monitor.start()
        self.assertIsNotNone(self.monitor._thread)
        self.assertTrue(self.monitor._thread.daemon)
        self.assertTrue(self.monitor._running.is_set())

    def test_stop_clears_running_flag(self):
        """Verify stop() clears the running flag."""
        self.monitor.start()
        self.monitor.stop()
        self.assertFalse(self.monitor._running.is_set())

    def test_stop_without_start(self):
        """Verify stop() does not crash when not started."""
        self.monitor.stop()

    def test_known_ports_returns_set(self):
        """Verify known_ports returns a set."""
        ports = self.monitor.known_ports
        self.assertIsInstance(ports, set)

    def test_online_ports_returns_set(self):
        """Verify online_ports returns a set."""
        ports = self.monitor.online_ports
        self.assertIsInstance(ports, set)


class TestModemMonitorPortDetection(unittest.TestCase):
    """Test ModemMonitor port checking and event publishing."""

    def setUp(self):
        """Create fresh ModemMonitor before each test."""
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(event_bus=self.event_bus, check_interval=0.1)

    def tearDown(self):
        """Stop monitor after each test."""
        self.monitor.stop()

    @patch("worker.modem_monitor.serial")
    def test_check_ports_returns_set(self, mock_serial):
        """Verify check_ports() returns a set of port names."""
        port1 = MagicMock()
        port1.device = "COM3"
        port2 = MagicMock()
        port2.device = "COM5"
        mock_serial.tools.list_ports.comports.return_value = [port1, port2]
        result = self.monitor.check_ports()
        self.assertIsInstance(result, set)
        self.assertIn("COM3", result)
        self.assertIn("COM5", result)

    @patch("worker.modem_monitor.serial")
    def test_check_ports_empty_when_no_serial(self, mock_serial):
        """Verify check_ports returns empty set when serial not available."""
        mock_serial.tools.list_ports.comports.return_value = []
        result = self.monitor.check_ports()
        self.assertIsInstance(result, set)
        self.assertEqual(len(result), 0)

    def test_check_ports_returns_set_type(self):
        """Verify check_ports always returns a set (even when serial unavailable)."""
        result = self.monitor.check_ports()
        self.assertIsInstance(result, set)

    def test_monitor_publishes_port_appeared(self):
        """Verify monitor publishes modem.appeared for new ports."""
        with patch.object(self.monitor, "check_ports") as mock_check:
            mock_check.return_value = {"COM3"}
            self.monitor._known_ports = set()
            self.monitor._check_ports()
            calls = [str(c) for c in self.event_bus.publish.call_args_list]
            self.assertTrue(any("modem.appeared" in c for c in calls))

    def test_monitor_publishes_port_disappeared(self):
        """Verify monitor publishes modem.disappeared for removed ports."""
        self.monitor._known_ports = {"COM3"}
        with patch.object(self.monitor, "check_ports") as mock_check:
            mock_check.return_value = set()
            self.monitor._check_ports()
            calls = [str(c) for c in self.event_bus.publish.call_args_list]
            self.assertTrue(any("modem.disappeared" in c for c in calls))

    def test_monitor_no_event_for_unchanged_ports(self):
        """Verify no events published when ports unchanged."""
        self.monitor._known_ports = {"COM3"}
        with patch.object(self.monitor, "check_ports") as mock_check:
            mock_check.return_value = {"COM3"}
            self.monitor._check_ports()
            self.event_bus.publish.assert_not_called()

    def test_mark_online_publishes_event(self):
        """Verify mark_online publishes modem.online event."""
        self.monitor.mark_online("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("modem.online" in c for c in calls))

    def test_mark_offline_publishes_event(self):
        """Verify mark_offline publishes modem.offline event."""
        self.monitor.mark_online("COM3")
        self.event_bus.publish.reset_mock()
        self.monitor.mark_offline("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("modem.offline" in c for c in calls))

    def test_mark_online_publishes_each_time(self):
        """Verify mark_online always publishes modem.online event."""
        self.monitor.mark_online("COM3")
        self.event_bus.publish.reset_mock()
        self.monitor.mark_online("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("modem.online" in c for c in calls))


class TestModemMonitorThreadSafety(unittest.TestCase):
    """Test ModemMonitor thread safety."""

    def setUp(self):
        """Create fresh ModemMonitor before each test."""
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(event_bus=self.event_bus, check_interval=0.1)

    def tearDown(self):
        """Stop monitor after each test."""
        self.monitor.stop()

    def test_concurrent_known_ports_access(self):
        """Verify concurrent reads of known_ports do not crash."""
        errors = []

        def reader():
            try:
                for _ in range(100):
                    _ = self.monitor.known_ports
                    _ = self.monitor.online_ports
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_concurrent_mark_online_offline(self):
        """Verify concurrent mark_online/mark_offline do not crash."""
        errors = []

        def mutator():
            try:
                for _ in range(100):
                    self.monitor.mark_online("COM3")
                    self.monitor.mark_offline("COM3")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mutator) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
