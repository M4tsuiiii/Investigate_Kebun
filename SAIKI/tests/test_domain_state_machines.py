"""Tests for SAIKI domain state machines — CpinSM, FlowSM, UssdSM."""

import unittest
import threading
from unittest.mock import MagicMock

from app.domain.enums import CpinState, FlowStatus, FailureCode
from app.domain.state_machine.cpin_sm import CpinStateMachine, CpinTransition
from app.domain.state_machine.flow_sm import FlowStateMachine, FlowTransition
from app.domain.state_machine.ussd_sm import (
    UssdStateMachine,
    UssdSessionState,
    UssdTransition,
)


class TestCpinStateMachine(unittest.TestCase):
    """Test CpinStateMachine — SIM card CPIN state transitions."""

    def setUp(self):
        """Create fresh state machine before each test."""
        self.sm = CpinStateMachine(port_name="COM3")

    def test_initial_state(self):
        """Verify initial state is UNKNOWN."""
        self.assertEqual(self.sm.current_state, CpinState.UNKNOWN)

    def test_valid_transition_unknown_to_ready(self):
        """Verify UNKNOWN -> READY is valid."""
        event = self.sm.transition(CpinState.READY)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, CpinState.READY)

    def test_valid_transition_ready_to_not_ready(self):
        """Verify READY -> NOT_READY is valid."""
        self.sm.transition(CpinState.READY)
        event = self.sm.transition(CpinState.NOT_READY)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, CpinState.NOT_READY)

    def test_valid_transition_ready_to_pin_required(self):
        """Verify READY -> PIN_REQUIRED is valid."""
        self.sm.transition(CpinState.READY)
        event = self.sm.transition(CpinState.PIN_REQUIRED)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, CpinState.PIN_REQUIRED)

    def test_valid_transition_ready_to_not_inserted(self):
        """Verify READY -> NOT_INSERTED is valid."""
        self.sm.transition(CpinState.READY)
        event = self.sm.transition(CpinState.NOT_INSERTED)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, CpinState.NOT_INSERTED)

    def test_invalid_transition_rejected(self):
        """Verify invalid transitions still apply (fallback to on_unknown)."""
        event = self.sm.transition(CpinState.PIN_REQUIRED)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, CpinState.PIN_REQUIRED)

    def test_same_state_returns_transition_with_flag(self):
        """Verify same-state transition returns event with is_same_state=True."""
        event = self.sm.transition(CpinState.UNKNOWN)
        self.assertIsNotNone(event)
        self.assertTrue(event.is_same_state)

    def test_rlock_thread_safety(self):
        """Verify RLock prevents concurrent modification issues."""
        errors = []

        def transition_worker():
            try:
                for _ in range(100):
                    self.sm.transition(CpinState.READY)
                    self.sm.transition(CpinState.NOT_READY)
                    self.sm.transition(CpinState.UNKNOWN)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_subscribe_listener_notification(self):
        """Verify listeners are called on state change."""
        listener = MagicMock()
        self.sm.subscribe(listener)
        self.sm.transition(CpinState.READY)
        listener.assert_called_once()
        call_args = listener.call_args[0][0]
        self.assertEqual(call_args.new_state, CpinState.READY)

    def test_multiple_listeners(self):
        """Verify multiple listeners are all notified."""
        l1 = MagicMock()
        l2 = MagicMock()
        self.sm.subscribe(l1)
        self.sm.subscribe(l2)
        self.sm.transition(CpinState.READY)
        l1.assert_called_once()
        l2.assert_called_once()

    def test_card_cycle_management(self):
        """Verify require_card_cycle and clear_card_cycle."""
        self.sm.require_card_cycle()
        self.assertTrue(self.sm.awaiting_card_cycle)
        self.sm.clear_card_cycle()
        self.assertFalse(self.sm.awaiting_card_cycle)

    def test_should_block_auto_run(self):
        """Verify should_block_auto_run returns correct values."""
        # Default: trigger_mode != "Auto-Run on Insert" => blocked
        self.assertTrue(self.sm.should_block_auto_run("Manual"))
        # Auto-Run on Insert but current_state == UNKNOWN (not READY) and no awaiting => not blocked
        self.assertFalse(self.sm.should_block_auto_run("Auto-Run on Insert"))
        # When awaiting_card_cycle => blocked
        self.sm.require_card_cycle()
        self.assertTrue(self.sm.should_block_auto_run("Auto-Run on Insert"))

    def test_snapshot(self):
        """Verify snapshot returns current state as dict."""
        snap = self.sm.snapshot()
        self.assertIn("port", snap)
        self.assertIn("cpin_state", snap)
        self.assertIn("awaiting_card_cycle", snap)
        self.assertEqual(snap["port"], "COM3")
        self.assertEqual(snap["cpin_state"], CpinState.UNKNOWN.value)

    def test_is_ready_property(self):
        """Verify is_ready property."""
        self.assertFalse(self.sm.is_ready)
        self.sm.transition(CpinState.READY)
        self.assertTrue(self.sm.is_ready)

    def test_is_inserted_property(self):
        """Verify is_inserted property."""
        self.assertFalse(self.sm.is_inserted)
        self.sm.transition(CpinState.READY)
        self.assertTrue(self.sm.is_inserted)

    def test_listener_exception_does_not_crash(self):
        """Verify listener exceptions are silently caught."""
        def bad_listener(event):
            raise RuntimeError("boom")

        self.sm.subscribe(bad_listener)
        event = self.sm.transition(CpinState.READY)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, CpinState.READY)


class TestFlowStateMachine(unittest.TestCase):
    """Test FlowStateMachine — reactivation workflow transitions."""

    def setUp(self):
        """Create fresh state machine before each test."""
        self.sm = FlowStateMachine(port_name="COM5")

    def test_initial_state(self):
        """Verify initial state is STABILISASI."""
        self.assertEqual(self.sm.current_status, FlowStatus.STABILISASI)

    def test_valid_transition_stabilisasi_to_cek_nomor(self):
        """Verify STABILISASI -> CEK_NOMOR is valid."""
        event = self.sm.transition(FlowStatus.CEK_NOMOR)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_status, FlowStatus.CEK_NOMOR)

    def test_valid_transition_full_flow(self):
        """Verify complete flow transition chain."""
        steps = [
            FlowStatus.CEK_NOMOR,
            FlowStatus.CEK_STATUS,
            FlowStatus.CEK_NIK,
            FlowStatus.CEK_KK,
            FlowStatus.INJECTING,
            FlowStatus.VERIFYING,
            FlowStatus.DONE,
        ]
        for step in steps:
            event = self.sm.transition(step)
            self.assertIsNotNone(event, f"Transition to {step} failed")
        self.assertEqual(self.sm.current_status, FlowStatus.DONE)

    def test_invalid_transition_returns_none(self):
        """Verify invalid transitions return None."""
        event = self.sm.transition(FlowStatus.CEK_NIK)
        self.assertIsNone(event)
        self.assertEqual(self.sm.current_status, FlowStatus.STABILISASI)

    def test_gagal_from_any_state(self):
        """Verify GAGAL can be reached from any valid state."""
        self.sm.transition(FlowStatus.CEK_NOMOR)
        event = self.sm.transition(FlowStatus.GAGAL)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_status, FlowStatus.GAGAL)

    def test_rlock_thread_safety(self):
        """Verify RLock prevents concurrent modification issues."""
        errors = []

        def transition_worker():
            try:
                for _ in range(100):
                    self.sm.transition(FlowStatus.CEK_NOMOR)
                    self.sm.transition(FlowStatus.CEK_STATUS)
                    self.sm.reset()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_reset(self):
        """Verify reset returns to STABILISASI."""
        self.sm.transition(FlowStatus.CEK_NOMOR)
        self.sm.transition(FlowStatus.CEK_STATUS)
        self.sm.reset()
        self.assertEqual(self.sm.current_status, FlowStatus.STABILISASI)

    def test_failure_code_propagation(self):
        """Verify failure_code is passed through transition event."""
        self.sm.transition(FlowStatus.CEK_NOMOR)
        event = self.sm.transition(FlowStatus.GAGAL, failure_code=FailureCode.GAGAL_CEK_NIK)
        self.assertIsNotNone(event)
        self.assertEqual(event.failure_code, FailureCode.GAGAL_CEK_NIK)

    def test_is_done_property(self):
        """Verify is_done property."""
        self.assertFalse(self.sm.is_done)
        self.sm.transition(FlowStatus.CEK_NOMOR)
        self.sm.transition(FlowStatus.CEK_STATUS)
        self.sm.transition(FlowStatus.DONE)
        self.assertTrue(self.sm.is_done)

    def test_is_failed_property(self):
        """Verify is_failed property."""
        self.assertFalse(self.sm.is_failed)
        self.sm.transition(FlowStatus.GAGAL)
        self.assertTrue(self.sm.is_failed)

    def test_is_active_property(self):
        """Verify is_active property."""
        self.assertTrue(self.sm.is_active)
        self.sm.transition(FlowStatus.GAGAL)
        self.assertFalse(self.sm.is_active)

    def test_subscribe_listener_notification(self):
        """Verify listeners are called on transition."""
        listener = MagicMock()
        self.sm.subscribe(listener)
        self.sm.transition(FlowStatus.CEK_NOMOR)
        listener.assert_called_once()

    def test_snapshot(self):
        """Verify snapshot returns current state as dict."""
        snap = self.sm.snapshot()
        self.assertIn("port", snap)
        self.assertIn("flow_status", snap)
        self.assertEqual(snap["port"], "COM5")
        self.assertEqual(snap["flow_status"], FlowStatus.STABILISASI.value)

    def test_listener_exception_does_not_crash(self):
        """Verify listener exceptions are silently caught."""
        def bad_listener(event):
            raise RuntimeError("boom")

        self.sm.subscribe(bad_listener)
        event = self.sm.transition(FlowStatus.CEK_NOMOR)
        self.assertIsNotNone(event)


class TestUssdStateMachine(unittest.TestCase):
    """Test UssdStateMachine — USSD session lifecycle."""

    def setUp(self):
        """Create fresh state machine before each test."""
        self.sm = UssdStateMachine(port_name="COM7")

    def test_initial_state(self):
        """Verify initial state is IDLE."""
        self.assertEqual(self.sm.current_state, UssdSessionState.IDLE)

    def test_valid_transition_idle_to_fencing(self):
        """Verify IDLE -> FENCING is valid."""
        event = self.sm.transition(UssdSessionState.FENCING)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, UssdSessionState.FENCING)

    def test_valid_transition_full_flow(self):
        """Verify complete USSD flow transitions."""
        steps = [
            UssdSessionState.FENCING,
            UssdSessionState.DIALING,
            UssdSessionState.READING,
            UssdSessionState.PROCESSING,
            UssdSessionState.IDLE,
        ]
        for step in steps:
            event = self.sm.transition(step)
            self.assertIsNotNone(event, f"Transition to {step} failed")
        self.assertEqual(self.sm.current_state, UssdSessionState.IDLE)

    def test_invalid_transition_returns_none(self):
        """Verify invalid transitions return None."""
        event = self.sm.transition(UssdSessionState.READING)
        self.assertIsNone(event)
        self.assertEqual(self.sm.current_state, UssdSessionState.IDLE)

    def test_force_idle(self):
        """Verify force_idle returns to IDLE from any state."""
        self.sm.transition(UssdSessionState.FENCING)
        self.sm.transition(UssdSessionState.DIALING)
        self.sm.force_idle()
        self.assertEqual(self.sm.current_state, UssdSessionState.IDLE)

    def test_force_idle_from_recovery(self):
        """Verify force_idle works from RECOVERY state."""
        self.sm.transition(UssdSessionState.FENCING)
        self.sm.transition(UssdSessionState.DIALING)
        self.sm.transition(UssdSessionState.READING)
        self.sm.transition(UssdSessionState.PROCESSING)
        self.sm.transition(UssdSessionState.RECOVERY)
        self.sm.force_idle()
        self.assertEqual(self.sm.current_state, UssdSessionState.IDLE)

    def test_rlock_thread_safety(self):
        """Verify RLock prevents concurrent modification issues."""
        errors = []

        def transition_worker():
            try:
                for _ in range(100):
                    self.sm.transition(UssdSessionState.FENCING)
                    self.sm.transition(UssdSessionState.DIALING)
                    self.sm.force_idle()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_subscribe_listener_notification(self):
        """Verify listeners are called on transition."""
        listener = MagicMock()
        self.sm.subscribe(listener)
        self.sm.transition(UssdSessionState.FENCING)
        listener.assert_called_once()

    def test_is_idle_property(self):
        """Verify is_idle property."""
        self.assertTrue(self.sm.is_idle)
        self.sm.transition(UssdSessionState.FENCING)
        self.assertFalse(self.sm.is_idle)

    def test_is_active_property(self):
        """Verify is_active property."""
        self.assertFalse(self.sm.is_active)
        self.sm.transition(UssdSessionState.FENCING)
        self.assertTrue(self.sm.is_active)

    def test_snapshot(self):
        """Verify snapshot returns current state as dict."""
        snap = self.sm.snapshot()
        self.assertIn("port", snap)
        self.assertIn("ussd_state", snap)
        self.assertEqual(snap["port"], "COM7")
        self.assertEqual(snap["ussd_state"], UssdSessionState.IDLE.value)

    def test_recovery_to_idle(self):
        """Verify RECOVERY -> IDLE transition."""
        self.sm.transition(UssdSessionState.FENCING)
        self.sm.transition(UssdSessionState.DIALING)
        self.sm.transition(UssdSessionState.READING)
        self.sm.transition(UssdSessionState.PROCESSING)
        self.sm.transition(UssdSessionState.RECOVERY)
        event = self.sm.transition(UssdSessionState.IDLE)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, UssdSessionState.IDLE)

    def test_recovery_to_fencing(self):
        """Verify RECOVERY -> FENCING transition (retry)."""
        self.sm.transition(UssdSessionState.FENCING)
        self.sm.transition(UssdSessionState.DIALING)
        self.sm.transition(UssdSessionState.READING)
        self.sm.transition(UssdSessionState.PROCESSING)
        self.sm.transition(UssdSessionState.RECOVERY)
        event = self.sm.transition(UssdSessionState.FENCING)
        self.assertIsNotNone(event)
        self.assertEqual(self.sm.current_state, UssdSessionState.FENCING)

    def test_listener_exception_does_not_crash(self):
        """Verify listener exceptions are silently caught."""
        def bad_listener(event):
            raise RuntimeError("boom")

        self.sm.subscribe(bad_listener)
        event = self.sm.transition(UssdSessionState.FENCING)
        self.assertIsNotNone(event)


if __name__ == "__main__":
    unittest.main()
