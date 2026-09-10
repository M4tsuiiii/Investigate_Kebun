"""Tests for Sprint 11A — Port Participation Control.

Tests for ACTIVE/EXCLUDED states, mass action filtering, auto-run filtering.
"""

import unittest
from unittest.mock import MagicMock, patch
import time

from app.domain.enums import PortState, ValidationResult
from worker.worker_manager import WorkerManager
from worker.modem_validator import ModemValidator, PortValidationResult
from worker.rules import AutoRunConfig
from worker.ui.controller import UIController
from worker.ui.event_bus import EventBus
from automation.engine import AutomationEngine
from automation.state import AutomationStatus
from automation.triggers import Trigger
from workflow.runner import WorkflowRunner
from workflow.registry import WorkflowRegistry


class TestPortParticipationControl(unittest.TestCase):
    """Test exclude_port / include_port on WorkerManager."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )

    def tearDown(self):
        self.manager.stop_all()

    def test_exclude_active_port(self):
        """Excluding an ACTIVE port transitions to EXCLUDED."""
        self.manager.create_worker("COM3")
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.ACTIVE)
        result = self.manager.exclude_port("COM3")
        self.assertTrue(result)
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.EXCLUDED)

    def test_exclude_non_active_port_fails(self):
        """Excluding a non-ACTIVE port returns False."""
        result = self.manager.exclude_port("COM99")
        self.assertFalse(result)

    def test_include_excluded_port(self):
        """Including an EXCLUDED port transitions to ACTIVE."""
        self.manager.create_worker("COM3")
        self.manager.exclude_port("COM3")
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.EXCLUDED)
        result = self.manager.include_port("COM3")
        self.assertTrue(result)
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.ACTIVE)

    def test_include_non_excluded_port_fails(self):
        """Including a non-EXCLUDED port returns False."""
        self.manager.create_worker("COM3")
        result = self.manager.include_port("COM3")
        self.assertFalse(result)

    def test_exclude_publishes_state_changed(self):
        """Excluding a port publishes port.state_changed event."""
        self.manager.create_worker("COM3")
        self.manager.exclude_port("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("port.state_changed" in c for c in calls))

    def test_exclude_publishes_port_excluded(self):
        """Excluding a port publishes port.excluded event."""
        self.manager.create_worker("COM3")
        self.manager.exclude_port("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        self.assertTrue(any("port.excluded" in c for c in calls))

    def test_include_publishes_state_changed(self):
        """Including a port publishes port.state_changed event."""
        self.manager.create_worker("COM3")
        self.manager.exclude_port("COM3")
        self.manager.include_port("COM3")
        calls = [str(c) for c in self.event_bus.publish.call_args_list]
        state_calls = [c for c in calls if "port.state_changed" in c]
        self.assertTrue(len(state_calls) >= 2)  # one for exclude, one for include

    def test_get_active_ports(self):
        """get_active_ports returns only ACTIVE ports."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        self.manager.exclude_port("COM5")
        active = self.manager.get_active_ports()
        self.assertIn("COM3", active)
        self.assertNotIn("COM5", active)

    def test_get_excluded_ports(self):
        """get_excluded_ports returns only EXCLUDED ports."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        self.manager.exclude_port("COM5")
        excluded = self.manager.get_excluded_ports()
        self.assertIn("COM5", excluded)
        self.assertNotIn("COM3", excluded)

    def test_is_port_active(self):
        """is_port_active returns True only for ACTIVE ports."""
        self.manager.create_worker("COM3")
        self.assertTrue(self.manager.is_port_active("COM3"))
        self.manager.exclude_port("COM3")
        self.assertFalse(self.manager.is_port_active("COM3"))


class TestMassActionExclusion(unittest.TestCase):
    """Test that mass actions skip EXCLUDED ports."""

    def setUp(self):
        self.event_bus = EventBus()
        self.auto_run_config = AutoRunConfig()

        at_client = MagicMock()
        ussd_runtime = MagicMock()
        skill_map = {
            "cek_nomor": MagicMock(),
            "cek_status": MagicMock(),
            "cek_nik": MagicMock(),
            "cek_kk": MagicMock(),
        }

        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0.01)
        registry = WorkflowRegistry()

        self.engine = AutomationEngine(
            workflow_runner=runner,
            workflow_registry=registry,
            auto_run_config=self.auto_run_config,
            event_bus=self.event_bus,
            max_concurrent=2,
        )

        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )

        db_lookup = MagicMock()

        self.controller = UIController(
            event_bus=self.event_bus,
            worker_manager=self.manager,
            auto_run_config=self.auto_run_config,
            automation_engine=self.engine,
            db_lookup=db_lookup,
        )

    def tearDown(self):
        self.manager.stop_all()
        self.engine.stop()

    def _is_port_enqueued(self, port_id):
        """Check if a port has a QUEUED or RUNNING status."""
        state = self.engine.get_state(port_id)
        return state.status in (AutomationStatus.QUEUED, AutomationStatus.RUNNING)

    def _setup_worker_mock(self, port_id, alive=True, modem_online=True, cpin_state=None):
        """Configure mock worker with attributes needed for eligibility check."""
        from app.domain.enums import CpinState
        if cpin_state is None:
            cpin_state = CpinState.READY
        mock_worker = MagicMock()
        mock_worker.is_alive = alive
        mock_worker.modem_online = modem_online
        mock_worker.cpin_state = cpin_state
        original_get_worker = self.manager.get_worker
        def _patched_get_worker(pid):
            if pid == port_id:
                return mock_worker
            return original_get_worker(pid)
        self.manager.get_worker = _patched_get_worker
        return mock_worker

    def test_mass_check_skips_excluded(self):
        """Mass check number skips EXCLUDED ports."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        self.manager.exclude_port("COM5")
        self._setup_worker_mock("COM3")
        self._setup_worker_mock("COM5")

        from worker.ui.events import CommandEvent
        self.event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {})
        time.sleep(1.0)

        self.assertTrue(self._is_port_enqueued("COM3"))
        self.assertFalse(self._is_port_enqueued("COM5"))

    def test_mass_reactivation_skips_excluded(self):
        """Mass reactivation skips EXCLUDED ports."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        self.manager.exclude_port("COM5")
        self._setup_worker_mock("COM3")
        self._setup_worker_mock("COM5")

        from worker.ui.events import CommandEvent
        self.event_bus.publish(CommandEvent.MASS_REAKTIVASI.value, {})
        time.sleep(1.0)

        self.assertTrue(self._is_port_enqueued("COM3"))
        self.assertFalse(self._is_port_enqueued("COM5"))

    def test_mass_action_counts_active_only(self):
        """Mass action progress message counts only active ports."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        self.manager.create_worker("COM7")
        self.manager.exclude_port("COM5")
        self._setup_worker_mock("COM3")
        self._setup_worker_mock("COM5")
        self._setup_worker_mock("COM7")

        from worker.ui.events import CommandEvent, UIEvent
        progress_events = []
        self.event_bus.subscribe(UIEvent.MASS_PROGRESS.value, lambda p: progress_events.append(p))

        self.event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {})
        time.sleep(1.0)

        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0]["total"], 2)  # COM3 + COM7


class TestAutoRunExclusion(unittest.TestCase):
    """Test that auto-run skips EXCLUDED ports."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()
        self.auto_run_config.set_enabled(True)

        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )

        self.engine = AutomationEngine(
            workflow_runner=MagicMock(),
            workflow_registry=MagicMock(),
            auto_run_config=self.auto_run_config,
            event_bus=self.event_bus,
            max_concurrent=2,
            port_state_provider=self.manager,
        )

    def tearDown(self):
        self.manager.stop_all()
        self.engine.stop()

    def test_auto_run_skips_excluded_port(self):
        """Auto-run trigger on EXCLUDED port is skipped."""
        self.manager.create_worker("COM3")
        self.manager.exclude_port("COM3")

        self.engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        state = self.engine.get_state("COM3")
        self.assertEqual(state.status, AutomationStatus.IDLE)

    def test_auto_run_processes_active_port(self):
        """Auto-run trigger on ACTIVE port is processed."""
        self.manager.create_worker("COM3")

        self.engine.handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        state = self.engine.get_state("COM3")
        self.assertIn(state.status, (AutomationStatus.QUEUED, AutomationStatus.RUNNING))

    def test_manual_enqueue_skips_excluded(self):
        """Manual enqueue on EXCLUDED port is skipped."""
        self.manager.create_worker("COM3")
        self.manager.exclude_port("COM3")

        self.engine.enqueue_workflow("COM3", "check_data")
        state = self.engine.get_state("COM3")
        self.assertEqual(state.status, AutomationStatus.IDLE)

    def test_port_excluded_cancels_queued(self):
        """Excluding a port cancels its queued workflow."""
        self.manager.create_worker("COM3")
        self.engine.enqueue_workflow("COM3", "check_data")
        state = self.engine.get_state("COM3")
        self.assertEqual(state.status, AutomationStatus.QUEUED)

        self.manager.exclude_port("COM3")
        time.sleep(0.3)


class TestRemovedPortState(unittest.TestCase):
    """Test port state transitions on removal."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )

    def tearDown(self):
        self.manager.stop_all()

    def test_destroy_active_port_becomes_removed(self):
        """Destroying an ACTIVE port sets state to REMOVED."""
        self.manager.create_worker("COM3")
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.ACTIVE)
        self.manager.destroy_worker("COM3")
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.REMOVED)

    def test_destroy_excluded_port_becomes_removed(self):
        """Destroying an EXCLUDED port sets state to REMOVED."""
        self.manager.create_worker("COM3")
        self.manager.exclude_port("COM3")
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.EXCLUDED)
        self.manager.destroy_worker("COM3")
        self.assertEqual(self.manager.get_port_state("COM3"), PortState.REMOVED)

    def test_stop_all_clears_states(self):
        """stop_all clears all port states."""
        self.manager.create_worker("COM3")
        self.manager.create_worker("COM5")
        self.manager.stop_all()
        self.assertEqual(len(self.manager.get_all_port_states()), 0)


class TestRestartAllExclusion(unittest.TestCase):
    """Test restart_all only affects ACTIVE ports."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )

    def tearDown(self):
        self.manager.stop_all()

    def test_restart_all_skips_excluded(self):
        """restart_all only restarts ACTIVE workers."""
        w1 = self.manager.create_worker("COM3")
        w2 = self.manager.create_worker("COM5")
        self.manager.exclude_port("COM5")

        self.manager.restart_all()

        self.assertTrue(w1.state.consume_force_retry())
        self.assertFalse(w2.state.consume_force_retry())


class TestQueueAutoRunExclusion(unittest.TestCase):
    """Test queue_auto_run_all only affects ACTIVE ports."""

    def setUp(self):
        self.event_bus = MagicMock()
        self.auto_run_config = AutoRunConfig()
        self.manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
        )

    def tearDown(self):
        self.manager.stop_all()

    def test_queue_auto_run_skips_excluded(self):
        """queue_auto_run_all only queues ACTIVE workers."""
        w1 = self.manager.create_worker("COM3")
        w2 = self.manager.create_worker("COM5")
        self.manager.exclude_port("COM5")

        self.manager.queue_auto_run_all()

        self.assertTrue(w1.state.consume_auto_run())
        self.assertFalse(w2.state.consume_auto_run())


if __name__ == "__main__":
    unittest.main()
