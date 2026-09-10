"""Tests for worker/modem_monitor.py Sprint 2 changes."""

import unittest
from unittest.mock import MagicMock, patch, call

from app.domain.enums import CpinState
from app.domain.constants import DEFAULT_AT_TIMEOUT, CPIN_POLL_TIMEOUT
from worker.modem_monitor import ModemMonitor


class TestModemMonitorRegisterUnregister(unittest.TestCase):
    """Tests for register_modem and unregister_modem."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(self.event_bus)

    def test_register_modem_adds_to_dict(self):
        """register_modem should store modem adapter keyed by port_id."""
        modem = MagicMock()
        self.monitor.register_modem("COM1", modem)
        self.assertIn("COM1", self.monitor._modem_ports)
        self.assertEqual(self.monitor._modem_ports["COM1"], modem)

    def test_unregister_modem_removes_from_dict(self):
        """unregister_modem should remove modem adapter."""
        modem = MagicMock()
        self.monitor.register_modem("COM1", modem)
        self.monitor.unregister_modem("COM1")
        self.assertNotIn("COM1", self.monitor._modem_ports)

    def test_unregister_removes_from_online_ports(self):
        """unregister_modem should remove from online_ports set."""
        modem = MagicMock()
        self.monitor.register_modem("COM1", modem)
        self.monitor._online_ports.add("COM1")
        self.monitor.unregister_modem("COM1")
        self.assertNotIn("COM1", self.monitor._online_ports)

    def test_unregister_removes_sim_state(self):
        """unregister_modem should remove cached SIM state."""
        modem = MagicMock()
        self.monitor.register_modem("COM1", modem)
        self.monitor._sim_states["COM1"] = CpinState.READY
        self.monitor.unregister_modem("COM1")
        self.assertNotIn("COM1", self.monitor._sim_states)

    def test_unregister_nonexistent_port_no_error(self):
        """unregister_modem on unknown port should not raise."""
        self.monitor.unregister_modem("COM999")


class TestCheckModemOnline(unittest.TestCase):
    """Tests for ModemMonitor.check_modem_online."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(self.event_bus)

    def test_at_response_returns_true(self):
        """check_modem_online should return True when modem responds to AT."""
        modem = MagicMock()
        modem.send_at.return_value = "OK"
        self.monitor.register_modem("COM1", modem)

        self.assertTrue(self.monitor.check_modem_online("COM1"))

    def test_no_response_returns_false(self):
        """check_modem_online should return False when modem returns None."""
        modem = MagicMock()
        modem.send_at.return_value = None
        self.monitor.register_modem("COM1", modem)

        self.assertFalse(self.monitor.check_modem_online("COM1"))

    def test_exception_returns_false(self):
        """check_modem_online should return False on exception."""
        modem = MagicMock()
        modem.send_at.side_effect = Exception("serial error")
        self.monitor.register_modem("COM1", modem)

        self.assertFalse(self.monitor.check_modem_online("COM1"))

    def test_unregistered_port_returns_false(self):
        """check_modem_online for unregistered port should return False."""
        self.assertFalse(self.monitor.check_modem_online("COM_UNKNOWN"))

    def test_sends_correct_at_command(self):
        """check_modem_online should send 'AT' with correct timeout."""
        modem = MagicMock()
        modem.send_at.return_value = "OK"
        self.monitor.register_modem("COM1", modem)

        self.monitor.check_modem_online("COM1")
        modem.send_at.assert_called_once_with("AT", timeout=DEFAULT_AT_TIMEOUT)


class TestCheckSimState(unittest.TestCase):
    """Tests for ModemMonitor.check_sim_state."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(self.event_bus)

    def test_ready_returns_cpin_ready(self):
        """check_sim_state should return READY for +CPIN: READY."""
        modem = MagicMock()
        modem.send_at.return_value = "+CPIN: READY"
        self.monitor.register_modem("COM1", modem)

        self.assertEqual(self.monitor.check_sim_state("COM1"), CpinState.READY)

    def test_not_inserted_returns_cpin_not_inserted(self):
        """check_sim_state should return NOT_INSERTED."""
        modem = MagicMock()
        modem.send_at.return_value = "+CPIN: SIM NOT INSERTED"
        self.monitor.register_modem("COM1", modem)

        self.assertEqual(self.monitor.check_sim_state("COM1"), CpinState.NOT_INSERTED)

    def test_pin_required_returns_cpin_pin_required(self):
        """check_sim_state should return PIN_REQUIRED."""
        modem = MagicMock()
        modem.send_at.return_value = "+CPIN: SIM PIN"
        self.monitor.register_modem("COM1", modem)

        self.assertEqual(self.monitor.check_sim_state("COM1"), CpinState.PIN_REQUIRED)

    def test_unknown_response_returns_not_ready(self):
        """check_sim_state should return NOT_READY for unrecognized response."""
        modem = MagicMock()
        modem.send_at.return_value = "+CPIN: SOMETHING ELSE"
        self.monitor.register_modem("COM1", modem)

        self.assertEqual(self.monitor.check_sim_state("COM1"), CpinState.NOT_READY)

    def test_none_response_returns_unknown(self):
        """check_sim_state should return UNKNOWN for None response."""
        modem = MagicMock()
        modem.send_at.return_value = None
        self.monitor.register_modem("COM1", modem)

        self.assertEqual(self.monitor.check_sim_state("COM1"), CpinState.UNKNOWN)

    def test_exception_returns_unknown(self):
        """check_sim_state should return UNKNOWN on exception."""
        modem = MagicMock()
        modem.send_at.side_effect = Exception("error")
        self.monitor.register_modem("COM1", modem)

        self.assertEqual(self.monitor.check_sim_state("COM1"), CpinState.UNKNOWN)

    def test_unregistered_port_returns_unknown(self):
        """check_sim_state for unregistered port should return UNKNOWN."""
        self.assertEqual(self.monitor.check_sim_state("COM_UNKNOWN"), CpinState.UNKNOWN)


class TestMarkOnline(unittest.TestCase):
    """Tests for ModemMonitor.mark_online."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(self.event_bus)

    def test_publishes_modem_online(self):
        """mark_online should publish modem.online event."""
        self.monitor.mark_online("COM1")
        self.event_bus.publish.assert_called_with("modem.online", {"port": "COM1"})

    def test_adds_to_online_ports(self):
        """mark_online should add port to online_ports set."""
        self.monitor.mark_online("COM1")
        self.assertIn("COM1", self.monitor.online_ports)

    def test_idempotent(self):
        """mark_online called twice should still have port in set."""
        self.monitor.mark_online("COM1")
        self.monitor.mark_online("COM1")
        self.assertEqual(len(self.monitor.online_ports), 1)


class TestMarkOffline(unittest.TestCase):
    """Tests for ModemMonitor.mark_offline."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(self.event_bus)

    def test_publishes_modem_offline(self):
        """mark_offline should publish modem.offline event."""
        self.monitor.mark_offline("COM1")
        self.event_bus.publish.assert_called_with("modem.offline", {"port": "COM1"})

    def test_removes_from_online_ports(self):
        """mark_offline should remove port from online_ports set."""
        self.monitor._online_ports.add("COM1")
        self.monitor.mark_offline("COM1")
        self.assertNotIn("COM1", self.monitor.online_ports)


class TestCheckModems(unittest.TestCase):
    """Tests for ModemMonitor._check_modems."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.monitor = ModemMonitor(self.event_bus)

    def test_detects_online_change(self):
        """_check_modems should detect modem coming online."""
        modem = MagicMock()
        modem.send_at.return_value = "OK"
        self.monitor.register_modem("COM1", modem)

        self.monitor._check_modems()

        self.assertIn("COM1", self.monitor.online_ports)

    def test_detects_offline_change(self):
        """_check_modems should detect modem going offline."""
        modem = MagicMock()
        modem.send_at.return_value = None
        self.monitor.register_modem("COM1", modem)
        self.monitor._online_ports.add("COM1")

        self.monitor._check_modems()

        self.assertNotIn("COM1", self.monitor.online_ports)

    def test_publishes_sim_changed(self):
        """_check_modems should publish modem.sim_changed when SIM state changes."""
        modem = MagicMock()
        modem.send_at.return_value = "+CPIN: READY"
        self.monitor.register_modem("COM1", modem)

        self.monitor._check_modems()

        self.event_bus.publish.assert_any_call("modem.sim_changed", {
            "port": "COM1",
            "old_state": CpinState.UNKNOWN.value,
            "new_state": CpinState.READY.value,
        })


class TestKnownPortsProperty(unittest.TestCase):
    """Tests for ModemMonitor.known_ports property."""

    def test_returns_copy(self):
        """known_ports should return a copy, not the internal set."""
        event_bus = MagicMock()
        monitor = ModemMonitor(event_bus)
        ports = monitor.known_ports
        ports.add("HACK")
        self.assertNotIn("HACK", monitor.known_ports)


class TestOnlinePortsProperty(unittest.TestCase):
    """Tests for ModemMonitor.online_ports property."""

    def test_returns_copy(self):
        """online_ports should return a copy, not the internal set."""
        event_bus = MagicMock()
        monitor = ModemMonitor(event_bus)
        ports = monitor.online_ports
        ports.add("HACK")
        self.assertNotIn("HACK", monitor.online_ports)


if __name__ == "__main__":
    unittest.main()
