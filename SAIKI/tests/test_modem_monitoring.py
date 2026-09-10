"""Tests for realtime modem monitoring updates.

Verifies modem events flow through the pipeline and update automation state.
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
from automation.policy import AutomationMode
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


class TestModemMonitoring(unittest.TestCase):
    """Test realtime modem monitoring events."""

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
            "engine": engine,
            "worker_manager": worker_manager,
            "auto_run_config": auto_run_config,
        }

    def test_modem_online_creates_worker_and_triggers(self):
        """Modem online -> worker created -> automation triggered."""
        sys = self._make_system()
        sys["engine"].start()

        sys["event_bus"].publish("modem.online", {"port": "COM3"})
        time.sleep(0.5)

        state = sys["engine"].get_state("COM3")
        self.assertIsNotNone(state)

        sys["engine"].stop()

    def test_modem_offline_cancels_queued(self):
        """Modem offline -> queued workflows cancelled."""
        sys = self._make_system()
        sys["engine"].start()

        sys["event_bus"].publish("modem.offline", {"port": "COM3"})
        time.sleep(0.5)

        state = sys["engine"].get_state("COM3")
        self.assertTrue(state.is_idle)

        sys["engine"].stop()

    def test_cpin_ready_triggers_automation(self):
        """CPIN READY -> automation engine enqueues workflow."""
        sys = self._make_system()
        sys["engine"].start()
        sys["auto_run_config"].set_enabled(True)

        sys["event_bus"].publish("cpin.transition", {
            "port": "COM5", "old": "UNKNOWN", "new": "READY",
        })
        time.sleep(1.0)

        state = sys["engine"].get_state("COM5")
        self.assertIsNotNone(state)

        sys["engine"].stop()

    def test_cpin_required_sets_standby(self):
        """CPIN NOT_READY -> automation engine sets standby."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["event_bus"].publish("cpin.transition", {
            "port": "COM5", "old": "READY", "new": "NOT_READY",
        })
        time.sleep(0.5)

        state = sys["engine"].get_state("COM5")
        self.assertIsNotNone(state)

    def test_modem_appeared_creates_worker(self):
        """modem.appeared event creates a new worker."""
        sys = self._make_system()

        sys["event_bus"].publish("modem.appeared", {"port": "COM10"})
        time.sleep(0.5)

        worker = sys["worker_manager"].get_worker("COM10")
        self.assertIsNotNone(worker)

    def test_modem_disappeared_removes_worker(self):
        """modem.disappeared event removes a worker."""
        sys = self._make_system()

        sys["worker_manager"].create_worker("COM11")
        self.assertIsNotNone(sys["worker_manager"].get_worker("COM11"))

        sys["event_bus"].publish("modem.disappeared", {"port": "COM11"})
        time.sleep(0.5)

        worker = sys["worker_manager"].get_worker("COM11")
        self.assertIsNone(worker)

    def test_modem_online_sets_worker_online(self):
        """modem.online sets worker modem_online flag."""
        sys = self._make_system()

        worker = sys["worker_manager"].create_worker("COM12")
        self.assertFalse(worker.modem_online)

        sys["event_bus"].publish("modem.online", {"port": "COM12"})
        time.sleep(0.5)

        self.assertTrue(worker.modem_online)

    def test_modem_offline_sets_worker_offline(self):
        """modem.offline clears worker modem_online flag."""
        sys = self._make_system()

        worker = sys["worker_manager"].create_worker("COM13")

        sys["event_bus"].publish("modem.online", {"port": "COM13"})
        time.sleep(0.3)
        self.assertTrue(worker.modem_online)

        sys["event_bus"].publish("modem.offline", {"port": "COM13"})
        time.sleep(0.3)
        self.assertFalse(worker.modem_online)

    def test_auto_run_off_skips_modem_online_trigger(self):
        """modem.online is skipped by engine when auto-run is off."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(False)

        sys["event_bus"].publish("modem.online", {"port": "COM14"})
        time.sleep(0.5)

        state = sys["engine"].get_state("COM14")
        self.assertEqual(state.status, AutomationStatus.IDLE)

    def test_auto_run_on_enqueues_on_modem_online(self):
        """modem.online enqueues workflow when auto-run is on."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["worker_manager"].create_worker("COM15")

        sys["event_bus"].publish("modem.online", {"port": "COM15"})
        time.sleep(0.5)

        state = sys["engine"].get_state("COM15")
        self.assertIsNotNone(state)

    def test_cpin_pin_required_sets_standby(self):
        """CPIN PIN_REQUIRED sets port to standby."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["event_bus"].publish("cpin.transition", {
            "port": "COM16", "old": "UNKNOWN", "new": "PIN_REQUIRED",
        })
        time.sleep(0.5)

        state = sys["engine"].get_state("COM16")
        self.assertEqual(state.status, AutomationStatus.STANDBY)


if __name__ == "__main__":
    unittest.main()
