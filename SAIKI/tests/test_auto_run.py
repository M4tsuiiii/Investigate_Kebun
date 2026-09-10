"""Tests for Auto Run functionality.

Verifies auto-run ON/OFF behavior, toggle mechanics, and gating logic.
"""

import unittest
from unittest.mock import MagicMock
import time

from worker.ui.event_bus import EventBus
from worker.ui.controller import UIController
from worker.ui.events import CommandEvent, UIEvent
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig
from worker.db_lookup import DbLookup
from automation.engine import AutomationEngine
from automation.triggers import Trigger
from automation.state import AutomationStatus
from workflow.runner import WorkflowRunner
from workflow.registry import WorkflowRegistry
from worker.skills.base import SkillResult


def _make_success_skill(name):
    skill = MagicMock()
    skill.name = name
    skill.description = f"mock {name}"
    skill.execute.return_value = SkillResult(
        success=True, data={}, skill_name=name, port="COM3",
    )
    return skill


class TestAutoRun(unittest.TestCase):
    """Test auto-run ON/OFF behavior."""

    def _make_system(self):
        event_bus = EventBus()
        auto_run_config = AutoRunConfig()

        skill_map = {
            "cek_nomor": _make_success_skill("cek_nomor"),
            "cek_status": _make_success_skill("cek_status"),
            "cek_nik": _make_success_skill("cek_nik"),
            "cek_kk": _make_success_skill("cek_kk"),
            "inject_reaktivasi": _make_success_skill("inject_reaktivasi"),
            "verify_grace": _make_success_skill("verify_grace"),
        }

        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0.01)
        registry = WorkflowRegistry()

        engine = AutomationEngine(
            workflow_runner=runner,
            workflow_registry=registry,
            auto_run_config=auto_run_config,
            event_bus=event_bus,
        )

        worker_manager = WorkerManager(event_bus=event_bus, auto_run_config=auto_run_config)

        controller = UIController(
            event_bus=event_bus,
            worker_manager=worker_manager,
            auto_run_config=auto_run_config,
            automation_engine=engine,
            db_lookup=DbLookup(),
        )

        return {
            "event_bus": event_bus,
            "auto_run_config": auto_run_config,
            "engine": engine,
            "worker_manager": worker_manager,
        }

    def test_auto_run_on_enables_workflow(self):
        """Auto Run ON + CPIN READY -> workflow runs."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["worker_manager"].create_worker("COM3")

        sys["event_bus"].publish("cpin.transition", {
            "port": "COM3", "old": "UNKNOWN", "new": "READY",
        })
        time.sleep(1.0)

        state = sys["engine"].get_state("COM3")
        self.assertIsNotNone(state)

    def test_auto_run_off_prevents_workflow(self):
        """Auto Run OFF -> no workflow runs."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(False)

        sys["worker_manager"].create_worker("COM4")

        sys["event_bus"].publish("cpin.transition", {
            "port": "COM4", "old": "UNKNOWN", "new": "READY",
        })
        time.sleep(1.0)

        self.assertEqual(sys["engine"].get_queue_size(), 0)

    def test_toggle_auto_run(self):
        """Toggle auto-run updates state correctly."""
        sys = self._make_system()

        self.assertFalse(sys["auto_run_config"].auto_run_enabled)

        sys["event_bus"].publish(CommandEvent.AUTO_RUN_TOGGLE.value, {})
        self.assertTrue(sys["auto_run_config"].auto_run_enabled)

        sys["event_bus"].publish(CommandEvent.AUTO_RUN_TOGGLE.value, {})
        self.assertFalse(sys["auto_run_config"].auto_run_enabled)

    def test_toggle_publishes_ui_event(self):
        """Toggle publishes AUTO_RUN_CHANGED UI event."""
        sys = self._make_system()

        events = []
        sys["event_bus"].subscribe(UIEvent.AUTO_RUN_CHANGED.value, lambda p: events.append(p))

        sys["event_bus"].publish(CommandEvent.AUTO_RUN_TOGGLE.value, {})

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["enabled"])

    def test_toggle_with_explicit_enabled_value(self):
        """Toggle with explicit enabled value sets that value."""
        sys = self._make_system()

        sys["event_bus"].publish(CommandEvent.AUTO_RUN_TOGGLE.value, {"enabled": True})
        self.assertTrue(sys["auto_run_config"].auto_run_enabled)

        sys["event_bus"].publish(CommandEvent.AUTO_RUN_TOGGLE.value, {"enabled": False})
        self.assertFalse(sys["auto_run_config"].auto_run_enabled)

    def test_auto_run_off_skips_all_triggers(self):
        """All trigger types are skipped when auto-run is off."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(False)

        triggers_to_test = [
            (Trigger.MODEM_ONLINE, "COM3"),
            (Trigger.CPIN_READY, "COM3"),
            (Trigger.SIM_INSERTED, "COM3"),
        ]

        for trigger, port in triggers_to_test:
            sys["engine"].handle_trigger(trigger, port)

        self.assertEqual(sys["engine"].get_queue_size(), 0)

    def test_auto_run_on_allows_modem_online_trigger(self):
        """MODEM_ONLINE trigger enqueues when auto-run is on."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["engine"].handle_trigger(Trigger.MODEM_ONLINE, "COM3")
        self.assertEqual(sys["engine"].get_queue_size(), 1)

    def test_auto_run_on_allows_cpin_ready_trigger(self):
        """CPIN_READY trigger enqueues when auto-run is on."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["engine"].handle_trigger(Trigger.CPIN_READY, "COM3")
        self.assertEqual(sys["engine"].get_queue_size(), 1)

    def test_cpin_required_sets_standby(self):
        """CPIN_REQUIRED trigger sets port to standby."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["engine"].handle_trigger(Trigger.CPIN_REQUIRED, "COM3")
        state = sys["engine"].get_state("COM3")
        self.assertEqual(state.status, AutomationStatus.STANDBY)

    def test_auto_run_toggle_double_call(self):
        """Double toggle returns to original state."""
        sys = self._make_system()

        original = sys["auto_run_config"].auto_run_enabled

        sys["event_bus"].publish(CommandEvent.AUTO_RUN_TOGGLE.value, {})
        sys["event_bus"].publish(CommandEvent.AUTO_RUN_TOGGLE.value, {})

        self.assertEqual(sys["auto_run_config"].auto_run_enabled, original)


if __name__ == "__main__":
    unittest.main()
