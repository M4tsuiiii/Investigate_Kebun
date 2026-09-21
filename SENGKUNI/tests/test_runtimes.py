"""Runtimes tests — CpinRuntime, UssdRuntime."""

import threading
import time
import pytest
from unittest.mock import MagicMock, patch
from app.domain.enums import CpinState
from worker.cpin_runtime import CpinRuntime


class TestCpinRuntime:
    def _make_runtime(self, at_response="+CPIN: READY"):
        at_client = MagicMock()
        resp = MagicMock()
        resp.raw = at_response
        at_client.send_command = MagicMock(return_value=resp)
        transitions = []
        def on_transition(old, new):
            transitions.append((old, new))
        rt = CpinRuntime(
            port_id="COM99",
            at_client=at_client,
            on_cpin_transition=on_transition,
        )
        return rt, transitions

    def test_start_stop(self):
        rt, _ = self._make_runtime()
        rt.start()
        assert rt._running.is_set()
        rt.stop()
        assert not rt._running.is_set()

    def test_initial_state(self):
        rt, _ = self._make_runtime()
        assert rt.cpin_state == CpinState.UNKNOWN

    def test_poll_transitions(self):
        rt, transitions = self._make_runtime("+CPIN: READY")
        rt.start()
        time.sleep(1.5)  # Need 2+ polls for READY confirmation threshold
        rt.stop()
        assert any(new == CpinState.READY for _, new in transitions)

    def test_pause_resume(self):
        rt, _ = self._make_runtime()
        rt.start()
        rt.pause()
        assert rt.is_paused
        rt.resume()
        assert not rt.is_paused
        rt.stop()

    def test_reset_stabilization(self):
        rt, _ = self._make_runtime()
        rt.reset_stabilization()
        assert rt._unknown_count == 0
        assert rt._checking_count == 0

    def test_stabilization_ready_to_unknown(self):
        rt, transitions = self._make_runtime("+CPIN: NOT READY")
        rt._current_state = CpinState.READY
        result = rt._apply_stabilization(CpinState.UNKNOWN)
        assert result == CpinState.READY  # threshold not reached
        assert rt._checking_count == 1

    def test_stabilization_threshold(self):
        rt, _ = self._make_runtime()
        rt._current_state = CpinState.READY
        rt._checking_count = 1
        result = rt._apply_stabilization(CpinState.UNKNOWN)
        assert result == CpinState.UNKNOWN  # threshold reached

    def test_immediate_ready_needs_confirmation(self):
        """Single READY poll holds at current state until threshold met."""
        rt, _ = self._make_runtime()
        rt._current_state = CpinState.UNKNOWN
        result = rt._apply_stabilization(CpinState.READY)
        assert result == CpinState.UNKNOWN  # Holds until 2nd consecutive READY

    def test_ready_confirmation_threshold(self):
        """Two consecutive READY polls confirm READY state."""
        rt, _ = self._make_runtime()
        rt._current_state = CpinState.UNKNOWN
        rt._apply_stabilization(CpinState.READY)  # 1st — pending
        assert rt._current_state == CpinState.UNKNOWN
        result = rt._apply_stabilization(CpinState.READY)  # 2nd — confirmed
        assert result == CpinState.READY
