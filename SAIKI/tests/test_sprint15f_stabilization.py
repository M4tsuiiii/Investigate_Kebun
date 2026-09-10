"""Tests for Sprint 15F — CPIN Stabilization & GOOD Parity.

Tests for: CHECKING_THRESHOLD, UNKNOWN_THRESHOLD, removal confirmation,
adaptive polling, workflow audit logging.
"""

import unittest
from unittest.mock import MagicMock, patch, call
import logging

from app.domain.enums import CpinState
from app.domain.constants import (
    CPIN_UNKNOWN_THRESHOLD,
    CPIN_CHECKING_THRESHOLD,
    CPIN_MAX_REMOVAL_CONFIRM,
    CPIN_POLL_INTERVAL,
)
from worker.cpin_runtime import CpinRuntime
from worker.ui.event_bus import EventBus


# ------------------------------------------------------------------
# 1. CHECKING_THRESHOLD — READY→UNKNOWN stays READY until threshold
# ------------------------------------------------------------------

class TestCheckingThreshold(unittest.TestCase):
    """READY→UNKNOWN should not flip immediately. Must reach CHECKING_THRESHOLD."""

    def test_ready_to_unknown_once_stays_ready(self):
        """Single UNKNOWN from READY keeps READY state."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()

        # Set initial state to READY
        cpin._current_state = CpinState.READY
        cpin._unknown_count = 0
        cpin._checking_count = 0

        # First UNKNOWN
        result = cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
        self.assertEqual(result, CpinState.READY)  # Should stay READY
        self.assertEqual(cpin._unknown_count, 1)

    def test_ready_to_unknown_twice_stays_ready(self):
        """Two UNKNOWN from READY keeps READY state (at threshold)."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.READY
        cpin._unknown_count = 0
        cpin._checking_count = 0

        # First UNKNOWN
        cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
        # Second UNKNOWN
        result = cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
        self.assertEqual(result, CpinState.READY)  # Still READY at threshold
        self.assertEqual(cpin._unknown_count, 2)

    def test_ready_to_unknown_three_flips_not_ready(self):
        """Three UNKNOWN from READY flips to NOT_READY (UNKNOWN_THRESHOLD)."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.READY
        cpin._unknown_count = 0
        cpin._checking_count = 0

        # Three UNKNOWNs
        cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
        cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
        result = cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
        self.assertEqual(result, CpinState.NOT_READY)
        self.assertEqual(cpin._unknown_count, 0)  # Reset after flip

    def test_unknown_threshold_constant(self):
        """CPIN_UNKNOWN_THRESHOLD should be 3."""
        self.assertEqual(CPIN_UNKNOWN_THRESHOLD, 3)

    def test_checking_threshold_constant(self):
        """CPIN_CHECKING_THRESHOLD should be 2."""
        self.assertEqual(CPIN_CHECKING_THRESHOLD, 2)


# ------------------------------------------------------------------
# 2. Removal Confirmation — READY→NOT_INSERTED needs confirmations
# ------------------------------------------------------------------

class TestRemovalConfirmation(unittest.TestCase):
    """READY→NOT_INSERTED should require CPIN_MAX_REMOVAL_CONFIRM retries."""

    def test_ready_to_not_inserted_once_stays_ready(self):
        """Single NOT_INSERTED from READY keeps READY state."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.READY
        cpin._removal_confirm_count = 0

        result = cpin._apply_stabilization(CpinState.READY, CpinState.NOT_INSERTED)
        self.assertEqual(result, CpinState.READY)  # Should stay READY
        self.assertEqual(cpin._removal_confirm_count, 1)

    def test_ready_to_not_inserted_confirmed(self):
        """Two NOT_INSERTED from READY confirms removal."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.READY
        cpin._removal_confirm_count = 0

        # First NOT_INSERTED
        cpin._apply_stabilization(CpinState.READY, CpinState.NOT_INSERTED)
        # Second NOT_INSERTED (confirmation)
        result = cpin._apply_stabilization(CpinState.READY, CpinState.NOT_INSERTED)
        self.assertEqual(result, CpinState.NOT_INSERTED)
        self.assertEqual(cpin._removal_confirm_count, 0)  # Reset after confirm

    def test_removal_confirm_constant(self):
        """CPIN_MAX_REMOVAL_CONFIRM should be 2."""
        self.assertEqual(CPIN_MAX_REMOVAL_CONFIRM, 2)


# ------------------------------------------------------------------
# 3. READY transition resets counters
# ------------------------------------------------------------------

class TestReadyResetsCounters(unittest.TestCase):
    """Any→READY should reset all stabilization counters."""

    def test_unknown_to_ready_resets_counters(self):
        """UNKNOWN→READY resets unknown_count and checking_count."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.UNKNOWN
        cpin._unknown_count = 2
        cpin._checking_count = 2
        cpin._removal_confirm_count = 1

        result = cpin._apply_stabilization(CpinState.UNKNOWN, CpinState.READY)
        self.assertEqual(result, CpinState.READY)
        self.assertEqual(cpin._unknown_count, 0)
        self.assertEqual(cpin._checking_count, 0)
        self.assertEqual(cpin._removal_confirm_count, 0)

    def test_not_ready_to_ready_resets_counters(self):
        """NOT_READY→READY resets all counters."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.NOT_READY
        cpin._unknown_count = 3
        cpin._checking_count = 2

        result = cpin._apply_stabilization(CpinState.NOT_READY, CpinState.READY)
        self.assertEqual(result, CpinState.READY)
        self.assertEqual(cpin._unknown_count, 0)


# ------------------------------------------------------------------
# 4. Adaptive Polling — READY slower than CHECKING
# ------------------------------------------------------------------

class TestAdaptivePolling(unittest.TestCase):
    """READY ports should poll slower than CHECKING ports."""

    def test_ready_polls_slower(self):
        """READY state should set longer poll interval."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        cpin._update_poll_interval(CpinState.READY)
        self.assertGreater(cpin._poll_interval, CPIN_POLL_INTERVAL)

    def test_unknown_polls_normal(self):
        """UNKNOWN state should set normal poll interval."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        cpin._update_poll_interval(CpinState.UNKNOWN)
        self.assertEqual(cpin._poll_interval, CPIN_POLL_INTERVAL)

    def test_not_ready_polls_faster(self):
        """NOT_READY state should set faster poll interval."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        cpin._update_poll_interval(CpinState.NOT_READY)
        self.assertLess(cpin._poll_interval, CPIN_POLL_INTERVAL)


# ------------------------------------------------------------------
# 5. Workflow Audit Logging
# ------------------------------------------------------------------

class TestWorkflowAuditLogging(unittest.TestCase):
    """Automation engine should log lifecycle events."""

    def test_engine_logs_trigger(self):
        """handle_trigger should log [ENGINE] TRIGGER_IN."""
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=AutoRunConfig(),
            event_bus=MagicMock(),
        )

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.MODEM_ONLINE, "COM1")

        trigger_logs = [l for l in cm.output if "ENGINE ENTER" in l]
        self.assertTrue(len(trigger_logs) > 0)

    def test_engine_logs_autorun_disabled(self):
        """handle_trigger should log when auto-run disabled."""
        from automation.engine import AutomationEngine
        from automation.triggers import Trigger
        from workflow.runner import WorkflowRunner
        from workflow.registry import WorkflowRegistry
        from worker.rules import AutoRunConfig

        config = AutoRunConfig()
        config.set_enabled(False)

        engine = AutomationEngine(
            workflow_runner=MagicMock(spec=WorkflowRunner),
            workflow_registry=MagicMock(spec=WorkflowRegistry),
            auto_run_config=config,
            event_bus=MagicMock(),
        )

        with self.assertLogs("saiki.automation", level="INFO") as cm:
            engine.handle_trigger(Trigger.MODEM_ONLINE, "COM1")

        skip_logs = [l for l in cm.output if "auto_run_disabled" in l]
        self.assertTrue(len(skip_logs) > 0)


# ------------------------------------------------------------------
# 6. Integration: stabilization prevents flickering
# ------------------------------------------------------------------

class TestStabilizationPreventsFlickering(unittest.TestCase):
    """CPIN state should not flicker between READY and UNKNOWN."""

    def test_rapid_unknown_transitions_dont_flicker(self):
        """Multiple rapid UNKNOWN responses should not cause state flips."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.READY
        cpin._unknown_count = 0
        cpin._checking_count = 0

        # Simulate 5 rapid UNKNOWN responses
        for i in range(5):
            result = cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
            # After 3rd UNKNOWN, should flip to NOT_READY
            if i < 2:
                self.assertEqual(result, CpinState.READY, f"Step {i+1}: should stay READY")
            elif i == 2:
                self.assertEqual(result, CpinState.NOT_READY, f"Step {i+1}: should flip to NOT_READY")

    def test_ready_after_unknown_resets(self):
        """UNKNOWN→READY should reset all counters."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())

        cpin._current_state = CpinState.READY
        cpin._unknown_count = 2
        cpin._checking_count = 2

        # UNKNOWN response
        cpin._apply_stabilization(CpinState.READY, CpinState.UNKNOWN)
        # Then READY response
        result = cpin._apply_stabilization(CpinState.UNKNOWN, CpinState.READY)
        self.assertEqual(result, CpinState.READY)
        self.assertEqual(cpin._unknown_count, 0)
        self.assertEqual(cpin._checking_count, 0)


if __name__ == "__main__":
    unittest.main()
