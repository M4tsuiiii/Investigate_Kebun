"""Domain layer tests — enums, classifier, state machines."""

import pytest
from app.domain.enums import CpinState, PortStatus
from app.domain.classifier import parse_cpin_response
from app.domain.state_machine.cpin_sm import CpinStateMachine
from app.domain.state_machine.flow_sm import FlowStateMachine
from app.domain.state_machine.ussd_sm import UssdStateMachine
from app.domain.state_machine.hw_sm import HwStateMachine, HwState


class TestCpinState:
    def test_values(self):
        assert CpinState.READY.value == "READY"
        assert CpinState.NOT_READY.value == "NOT_READY"
        assert CpinState.NOT_INSERTED.value == "NOT_INSERTED"
        assert CpinState.UNKNOWN.value == "UNKNOWN"

    def test_from_value(self):
        assert CpinState("READY") == CpinState.READY


class TestPortStatus:
    def test_values(self):
        assert PortStatus.OFF.value == "OFF"
        assert PortStatus.READY.value == "READY"

    def test_from_value(self):
        assert PortStatus("OFF") == PortStatus.OFF


class TestParseCpinResponse:
    def test_ready(self):
        assert parse_cpin_response("+CPIN: READY") == CpinState.READY

    def test_not_ready(self):
        assert parse_cpin_response("+CPIN: NOT READY") == CpinState.NOT_READY

    def test_not_inserted(self):
        assert parse_cpin_response("+CPIN: NOT INSERTED") == CpinState.NOT_INSERTED

    def test_pin_required(self):
        assert parse_cpin_response("+CPIN: SIM PIN") == CpinState.PIN_REQUIRED

    def test_error_returns_unknown(self):
        assert parse_cpin_response("ERROR") == CpinState.UNKNOWN

    def test_empty_returns_unknown(self):
        assert parse_cpin_response("") == CpinState.UNKNOWN

    def test_none_returns_unknown(self):
        assert parse_cpin_response(None) == CpinState.UNKNOWN

    def test_cme_error_returns_not_inserted(self):
        assert parse_cpin_response("+CME ERROR: 10") == CpinState.NOT_INSERTED

    def test_cme_error_other_code_returns_not_inserted(self):
        assert parse_cpin_response("+CME ERROR: 13") == CpinState.NOT_INSERTED

    def test_stale_ussd_with_ready_not_false_positive(self):
        """Stale USSD data containing 'READY' must NOT be detected as CPIN READY."""
        stale = '+CUSD: 0,"Ready to serve",15\nOK'
        assert parse_cpin_response(stale) != CpinState.READY

    def test_multi_line_with_ready_prefix(self):
        """Valid +CPIN: READY with trailing content should parse correctly."""
        assert parse_cpin_response("+CPIN: READY\nOK") == CpinState.READY


class TestCpinStateMachine:
    def test_initial_state(self):
        sm = CpinStateMachine("COM99")
        assert sm.current_state == CpinState.UNKNOWN

    def test_transition(self):
        sm = CpinStateMachine("COM99")
        sm.transition(CpinState.READY)
        assert sm.current_state == CpinState.READY

    def test_get_state(self):
        sm = CpinStateMachine("COM99")
        assert sm.get_state() == CpinState.UNKNOWN

    def test_is_ready(self):
        sm = CpinStateMachine("COM99")
        assert sm.is_ready is False
        sm.transition(CpinState.READY)
        assert sm.is_ready is True

    def test_snapshot(self):
        sm = CpinStateMachine("COM99")
        snap = sm.snapshot()
        assert "cpin_state" in snap


class TestFlowStateMachine:
    def test_initial_state(self):
        sm = FlowStateMachine("COM99")
        assert sm.current_status is not None

    def test_is_active(self):
        sm = FlowStateMachine("COM99")
        assert isinstance(sm.is_active, bool)

    def test_snapshot(self):
        sm = FlowStateMachine("COM99")
        snap = sm.snapshot()
        assert isinstance(snap, dict)


class TestUssdStateMachine:
    def test_initial_state(self):
        sm = UssdStateMachine("COM99")
        assert sm.current_state is not None

    def test_snapshot(self):
        sm = UssdStateMachine("COM99")
        snap = sm.snapshot()
        assert isinstance(snap, dict)


class TestHwStateMachine:
    def test_initial_state(self):
        sm = HwStateMachine("COM99")
        assert sm.is_online is False
        assert sm.is_ready is False

    def test_modem_detected(self):
        sm = HwStateMachine("COM99")
        sm.transition(HwState.MODEM_DETECTED)
        assert sm.is_online is True

    def test_force_offline(self):
        sm = HwStateMachine("COM99")
        sm.transition(HwState.MODEM_DETECTED)
        sm.force_offline()
        assert sm.is_online is False

    def test_snapshot(self):
        sm = HwStateMachine("COM99")
        snap = sm.snapshot()
        assert "hw_state" in snap
