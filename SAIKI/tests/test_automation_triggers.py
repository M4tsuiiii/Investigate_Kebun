"""Tests for automation.triggers — Trigger enum and TriggerEvent."""

import unittest

from automation.triggers import Trigger, TriggerEvent


class TestTriggerEnum(unittest.TestCase):
    """Test Trigger enum — hardware and workflow event types."""

    def test_trigger_enum_values(self) -> None:
        """Verify Trigger members have correct string values."""
        self.assertEqual(Trigger.MODEM_ONLINE.value, "MODEM_ONLINE")
        self.assertEqual(Trigger.MODEM_OFFLINE.value, "MODEM_OFFLINE")
        self.assertEqual(Trigger.SIM_INSERTED.value, "SIM_INSERTED")
        self.assertEqual(Trigger.SIM_REMOVED.value, "SIM_REMOVED")
        self.assertEqual(Trigger.CPIN_READY.value, "CPIN_READY")
        self.assertEqual(Trigger.CPIN_REQUIRED.value, "CPIN_REQUIRED")
        self.assertEqual(Trigger.WORKFLOW_SUCCESS.value, "WORKFLOW_SUCCESS")
        self.assertEqual(Trigger.WORKFLOW_FAILED.value, "WORKFLOW_FAILED")
        self.assertEqual(Trigger.USER_MASS_REACTIVATION.value, "USER_MASS_REACTIVATION")
        self.assertEqual(Trigger.USER_MASS_CHECK_NUMBER.value, "USER_MASS_CHECK_NUMBER")

    def test_trigger_has_all_values(self) -> None:
        """Verify Trigger has exactly 10 members."""
        self.assertEqual(len(Trigger), 10)

    def test_trigger_inherits_str(self) -> None:
        """Verify Trigger is a str enum."""
        self.assertIsInstance(Trigger.MODEM_ONLINE, str)
        self.assertTrue(Trigger.MODEM_ONLINE == "MODEM_ONLINE")

    def test_trigger_no_duplicate_values(self) -> None:
        """Verify no duplicate values across members."""
        values = [m.value for m in Trigger]
        self.assertEqual(len(values), len(set(values)))


class TestTriggerEvent(unittest.TestCase):
    """Test TriggerEvent dataclass — trigger event with context."""

    def test_trigger_event_creation(self) -> None:
        """Verify TriggerEvent can be created with required fields."""
        event = TriggerEvent(trigger=Trigger.MODEM_ONLINE, port="COM3")
        self.assertEqual(event.trigger, Trigger.MODEM_ONLINE)
        self.assertEqual(event.port, "COM3")
        self.assertEqual(event.detail, "")

    def test_trigger_event_with_detail(self) -> None:
        """Verify TriggerEvent accepts optional detail."""
        event = TriggerEvent(
            trigger=Trigger.WORKFLOW_FAILED,
            port="COM5",
            detail="timeout",
        )
        self.assertEqual(event.detail, "timeout")

    def test_trigger_event_is_frozen(self) -> None:
        """Verify TriggerEvent is frozen (immutable)."""
        event = TriggerEvent(trigger=Trigger.SIM_INSERTED, port="COM3")
        with self.assertRaises(AttributeError):
            event.port = "COM4"  # type: ignore[misc]

    def test_trigger_event_repr(self) -> None:
        """Verify TriggerEvent repr format."""
        event = TriggerEvent(trigger=Trigger.CPIN_READY, port="COM7")
        r = repr(event)
        self.assertIn("TriggerEvent", r)
        self.assertIn("CPIN_READY", r)
        self.assertIn("COM7", r)

    def test_trigger_event_comparison(self) -> None:
        """Verify two identical TriggerEvents are equal."""
        e1 = TriggerEvent(trigger=Trigger.MODEM_ONLINE, port="COM3")
        e2 = TriggerEvent(trigger=Trigger.MODEM_ONLINE, port="COM3")
        self.assertEqual(e1, e2)

    def test_trigger_event_inequality(self) -> None:
        """Verify different TriggerEvents are not equal."""
        e1 = TriggerEvent(trigger=Trigger.MODEM_ONLINE, port="COM3")
        e2 = TriggerEvent(trigger=Trigger.MODEM_OFFLINE, port="COM3")
        self.assertNotEqual(e1, e2)


if __name__ == "__main__":
    unittest.main()
