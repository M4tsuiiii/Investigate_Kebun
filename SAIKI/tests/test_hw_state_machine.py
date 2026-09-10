"""Tests for app/domain/state_machine/hw_sm.py — HwStateMachine.

Hardware lifecycle state transitions:
OFFLINE → MODEM_DETECTED → PORT_READY → SIM_INSERTED → CPIN_READY → READY
READY → SIM_REMOVED, READY → OFFLINE, SIM_REMOVED → OFFLINE, SIM_REMOVED → SIM_INSERTED
OFFLINE → READY (direct reconnect)
"""

import unittest
import threading
from unittest.mock import MagicMock

from app.domain.state_machine.hw_sm import HwStateMachine, HwState, HwTransition


class TestHwStateMachine(unittest.TestCase):
    """Test HwStateMachine — modem lifecycle state transitions."""

    def setUp(self) -> None:
        self.sm = HwStateMachine(port_name="COM3")

    def test_initial_state_is_offline(self) -> None:
        self.assertEqual(self.sm.current_state, HwState.OFFLINE)

    def test_valid_transition_returns_event(self) -> None:
        event = self.sm.transition(HwState.MODEM_DETECTED)
        self.assertIsNotNone(event)
        self.assertIsInstance(event, HwTransition)

    def test_valid_transition_updates_state(self) -> None:
        self.sm.transition(HwState.MODEM_DETECTED)
        self.assertEqual(self.sm.current_state, HwState.MODEM_DETECTED)

    def test_invalid_transition_returns_none(self) -> None:
        event = self.sm.transition(HwState.PORT_READY)
        self.assertIsNone(event)
        self.assertEqual(self.sm.current_state, HwState.OFFLINE)

    def test_same_state_transition_returns_none(self) -> None:
        event = self.sm.transition(HwState.OFFLINE)
        self.assertIsNone(event)

    def test_transition_detail_captured(self) -> None:
        event = self.sm.transition(HwState.MODEM_DETECTED, detail="USB plugged")
        self.assertEqual(event.detail, "USB plugged")

    def test_transition_port_captured(self) -> None:
        event = self.sm.transition(HwState.MODEM_DETECTED)
        self.assertEqual(event.port, "COM3")

    def test_listener_called_on_transition(self) -> None:
        listener = MagicMock()
        self.sm.subscribe(listener)
        self.sm.transition(HwState.MODEM_DETECTED)
        listener.assert_called_once()
        call_arg = listener.call_args[0][0]
        self.assertEqual(call_arg.old_state, HwState.OFFLINE)
        self.assertEqual(call_arg.new_state, HwState.MODEM_DETECTED)

    def test_multiple_listeners(self) -> None:
        l1 = MagicMock()
        l2 = MagicMock()
        self.sm.subscribe(l1)
        self.sm.subscribe(l2)
        self.sm.transition(HwState.MODEM_DETECTED)
        l1.assert_called_once()
        l2.assert_called_once()

    def test_listener_exception_does_not_crash(self) -> None:
        def bad_listener(event: HwTransition) -> None:
            raise RuntimeError("boom")

        self.sm.subscribe(bad_listener)
        event = self.sm.transition(HwState.MODEM_DETECTED)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, HwState.MODEM_DETECTED)

    def test_force_offline_from_ready(self) -> None:
        self.sm.transition(HwState.MODEM_DETECTED)
        self.sm.transition(HwState.PORT_READY)
        self.sm.transition(HwState.SIM_INSERTED)
        self.sm.transition(HwState.CPIN_READY)
        self.sm.transition(HwState.READY)
        self.sm.force_offline()
        self.assertEqual(self.sm.current_state, HwState.OFFLINE)

    def test_force_offline_from_any_state(self) -> None:
        self.sm.transition(HwState.MODEM_DETECTED)
        self.sm.transition(HwState.PORT_READY)
        self.sm.force_offline()
        self.assertEqual(self.sm.current_state, HwState.OFFLINE)

    def test_is_ready_true_when_ready(self) -> None:
        self.sm.transition(HwState.MODEM_DETECTED)
        self.sm.transition(HwState.PORT_READY)
        self.sm.transition(HwState.SIM_INSERTED)
        self.sm.transition(HwState.CPIN_READY)
        self.sm.transition(HwState.READY)
        self.assertTrue(self.sm.is_ready)

    def test_is_ready_false_when_not_ready(self) -> None:
        self.assertFalse(self.sm.is_ready)
        self.sm.transition(HwState.MODEM_DETECTED)
        self.assertFalse(self.sm.is_ready)

    def test_is_online_true_when_ready(self) -> None:
        self.sm.transition(HwState.MODEM_DETECTED)
        self.sm.transition(HwState.PORT_READY)
        self.sm.transition(HwState.SIM_INSERTED)
        self.sm.transition(HwState.CPIN_READY)
        self.sm.transition(HwState.READY)
        self.assertTrue(self.sm.is_online)

    def test_is_online_true_when_sim_removed(self) -> None:
        """SIM_REMOVED is online per is_online check (not in OFFLINE/SIM_REMOVED set?).

        is_online returns True when state not in (OFFLINE, SIM_REMOVED).
        SIM_REMOVED IS in that set, so is_online should be False.
        """
        self.sm.transition(HwState.MODEM_DETECTED)
        self.sm.transition(HwState.PORT_READY)
        self.sm.transition(HwState.SIM_INSERTED)
        self.sm.transition(HwState.CPIN_READY)
        self.sm.transition(HwState.READY)
        self.sm.transition(HwState.SIM_REMOVED)
        self.assertFalse(self.sm.is_online)

    def test_is_online_false_when_offline(self) -> None:
        self.assertFalse(self.sm.is_online)

    def test_snapshot_returns_dict(self) -> None:
        snap = self.sm.snapshot()
        self.assertIsInstance(snap, dict)
        self.assertIn("port", snap)
        self.assertIn("hw_state", snap)
        self.assertEqual(snap["port"], "COM3")
        self.assertEqual(snap["hw_state"], HwState.OFFLINE.value)

    def test_full_lifecycle_offline_to_ready(self) -> None:
        transitions = [
            HwState.MODEM_DETECTED,
            HwState.PORT_READY,
            HwState.SIM_INSERTED,
            HwState.CPIN_READY,
            HwState.READY,
        ]
        for target in transitions:
            event = self.sm.transition(target)
            self.assertIsNotNone(event, f"Transition to {target} failed")
        self.assertEqual(self.sm.current_state, HwState.READY)
        self.assertTrue(self.sm.is_ready)
        self.assertTrue(self.sm.is_online)

    def test_ready_to_sim_removed_to_offline(self) -> None:
        self.sm.transition(HwState.MODEM_DETECTED)
        self.sm.transition(HwState.PORT_READY)
        self.sm.transition(HwState.SIM_INSERTED)
        self.sm.transition(HwState.CPIN_READY)
        self.sm.transition(HwState.READY)

        event1 = self.sm.transition(HwState.SIM_REMOVED)
        self.assertIsNotNone(event1)
        self.assertEqual(self.sm.current_state, HwState.SIM_REMOVED)

        event2 = self.sm.transition(HwState.OFFLINE)
        self.assertIsNotNone(event2)
        self.assertEqual(self.sm.current_state, HwState.OFFLINE)

    def test_thread_safety(self) -> None:
        errors: list = []

        def transition_worker() -> None:
            try:
                for _ in range(100):
                    self.sm.transition(HwState.MODEM_DETECTED)
                    self.sm.transition(HwState.PORT_READY)
                    self.sm.transition(HwState.SIM_INSERTED)
                    self.sm.transition(HwState.CPIN_READY)
                    self.sm.transition(HwState.READY)
                    self.sm.transition(HwState.SIM_REMOVED)
                    self.sm.transition(HwState.OFFLINE)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_offline_to_ready_direct(self) -> None:
        event = self.sm.transition(HwState.READY)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, HwState.READY)

    def test_sim_removed_to_sim_inserted(self) -> None:
        self.sm.transition(HwState.MODEM_DETECTED)
        self.sm.transition(HwState.PORT_READY)
        self.sm.transition(HwState.SIM_INSERTED)
        self.sm.transition(HwState.CPIN_READY)
        self.sm.transition(HwState.READY)
        self.sm.transition(HwState.SIM_REMOVED)

        event = self.sm.transition(HwState.SIM_INSERTED)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, HwState.SIM_INSERTED)

    def test_old_state_recorded_in_transition(self) -> None:
        event = self.sm.transition(HwState.MODEM_DETECTED)
        self.assertEqual(event.old_state, HwState.OFFLINE)
        self.assertEqual(event.new_state, HwState.MODEM_DETECTED)


if __name__ == "__main__":
    unittest.main()
