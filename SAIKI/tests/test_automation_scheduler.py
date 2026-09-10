"""Tests for automation.scheduler — AutomationScheduler."""

import unittest

from automation.scheduler import AutomationScheduler
from automation.triggers import Trigger, TriggerEvent
from automation.state import AutomationStatus


class TestAutomationScheduler(unittest.TestCase):
    """Test AutomationScheduler — trigger evaluation and port scheduling."""

    def test_get_state_creates_new(self) -> None:
        """Verify get_state creates new state for unknown port."""
        sched = AutomationScheduler()
        state = sched.get_state("COM3")
        self.assertIsNotNone(state)
        self.assertEqual(state.port, "COM3")

    def test_get_state_returns_existing(self) -> None:
        """Verify get_state returns same state for same port."""
        sched = AutomationScheduler()
        state1 = sched.get_state("COM3")
        state2 = sched.get_state("COM3")
        self.assertIs(state1, state2)

    def test_evaluate_trigger_modem_online_returns_enqueue(self) -> None:
        """Verify MODEM_ONLINE trigger returns 'enqueue'."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.MODEM_ONLINE, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "enqueue")

    def test_evaluate_trigger_modem_offline_returns_cancel(self) -> None:
        """Verify MODEM_OFFLINE trigger returns 'cancel'."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.MODEM_OFFLINE, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "cancel")

    def test_evaluate_trigger_sim_inserted_idle_returns_enqueue(self) -> None:
        """Verify SIM_INSERTED on idle port returns 'enqueue'."""
        sched = AutomationScheduler()
        state = sched.get_state("COM3")
        state.set_idle()
        event = TriggerEvent(trigger=Trigger.SIM_INSERTED, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "enqueue")

    def test_evaluate_trigger_sim_inserted_standby_returns_enqueue(self) -> None:
        """Verify SIM_INSERTED on standby port returns 'enqueue'."""
        sched = AutomationScheduler()
        state = sched.get_state("COM3")
        state.set_standby()
        event = TriggerEvent(trigger=Trigger.SIM_INSERTED, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "enqueue")

    def test_evaluate_trigger_sim_inserted_running_returns_none(self) -> None:
        """Verify SIM_INSERTED on running port returns None."""
        sched = AutomationScheduler()
        state = sched.get_state("COM3")
        state.set_running("reactivate_full")
        event = TriggerEvent(trigger=Trigger.SIM_INSERTED, port="COM3")
        self.assertIsNone(sched.evaluate_trigger(event))

    def test_evaluate_trigger_sim_removed_returns_cancel(self) -> None:
        """Verify SIM_REMOVED trigger returns 'cancel'."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.SIM_REMOVED, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "cancel")

    def test_evaluate_trigger_cpin_ready_idle_returns_enqueue(self) -> None:
        """Verify CPIN_READY on idle port returns 'enqueue'."""
        sched = AutomationScheduler()
        state = sched.get_state("COM3")
        state.set_idle()
        event = TriggerEvent(trigger=Trigger.CPIN_READY, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "enqueue")

    def test_evaluate_trigger_cpin_ready_standby_returns_enqueue(self) -> None:
        """Verify CPIN_READY on standby port returns 'enqueue'."""
        sched = AutomationScheduler()
        state = sched.get_state("COM3")
        state.set_standby()
        event = TriggerEvent(trigger=Trigger.CPIN_READY, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "enqueue")

    def test_evaluate_trigger_cpin_ready_running_returns_none(self) -> None:
        """Verify CPIN_READY on running port returns None."""
        sched = AutomationScheduler()
        state = sched.get_state("COM3")
        state.set_running("reactivate_full")
        event = TriggerEvent(trigger=Trigger.CPIN_READY, port="COM3")
        self.assertIsNone(sched.evaluate_trigger(event))

    def test_evaluate_trigger_cpin_required_returns_standby(self) -> None:
        """Verify CPIN_REQUIRED trigger returns 'standby'."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.CPIN_REQUIRED, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "standby")

    def test_evaluate_trigger_workflow_success_returns_standby(self) -> None:
        """Verify WORKFLOW_SUCCESS trigger returns 'standby'."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.WORKFLOW_SUCCESS, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "standby")

    def test_evaluate_trigger_workflow_failed_returns_none(self) -> None:
        """Verify WORKFLOW_FAILED trigger returns None."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.WORKFLOW_FAILED, port="COM3")
        self.assertIsNone(sched.evaluate_trigger(event))

    def test_evaluate_trigger_user_mass_reactivation_returns_enqueue(self) -> None:
        """Verify USER_MASS_REACTIVATION trigger returns 'enqueue'."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.USER_MASS_REACTIVATION, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "enqueue")

    def test_evaluate_trigger_user_mass_check_number_returns_enqueue(self) -> None:
        """Verify USER_MASS_CHECK_NUMBER trigger returns 'enqueue'."""
        sched = AutomationScheduler()
        event = TriggerEvent(trigger=Trigger.USER_MASS_CHECK_NUMBER, port="COM3")
        self.assertEqual(sched.evaluate_trigger(event), "enqueue")

    def test_list_ports(self) -> None:
        """Verify list_ports returns all tracked ports."""
        sched = AutomationScheduler()
        sched.get_state("COM3")
        sched.get_state("COM5")
        ports = sched.list_ports()
        self.assertIn("COM3", ports)
        self.assertIn("COM5", ports)
        self.assertEqual(len(ports), 2)

    def test_snapshot(self) -> None:
        """Verify snapshot returns dict of port states."""
        sched = AutomationScheduler()
        sched.get_state("COM3")
        snap = sched.snapshot()
        self.assertIn("COM3", snap)
        self.assertIn("port", snap["COM3"])
        self.assertIn("status", snap["COM3"])

    def test_snapshot_empty(self) -> None:
        """Verify snapshot returns empty dict when no ports tracked."""
        sched = AutomationScheduler()
        self.assertEqual(sched.snapshot(), {})


if __name__ == "__main__":
    unittest.main()
