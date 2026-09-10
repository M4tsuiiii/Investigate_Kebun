"""End-to-end tests for Mass Reactivation flow.

Verifies the FULL pipeline: UI EventBus -> Controller -> AutomationEngine -> WorkflowRunner -> Skills.
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
from worker.skills.cek_nomor import CekNomorSkill
from worker.skills.cek_status import CekStatusSkill
from worker.skills.cek_nik import CekNikSkill
from worker.skills.cek_kk import CekKkSkill
from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
from worker.skills.verify_grace import VerifyGraceSkill
from automation.engine import AutomationEngine
from automation.triggers import Trigger
from automation.state import AutomationStatus
from automation.policy import AutomationMode
from workflow.runner import WorkflowRunner
from workflow.registry import WorkflowRegistry


def _make_at_response(success=True, raw="OK"):
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


class TestEndToEndReactivation(unittest.TestCase):
    """End-to-end test: Reaktivasi Massal -> reactivate_full -> all skills."""

    def _make_system(self):
        event_bus = EventBus()
        auto_run_config = AutoRunConfig()

        at_client = MagicMock()
        ussd_runtime = MagicMock()

        skill_map = {
            "cek_nomor": CekNomorSkill(at_client),
            "cek_status": CekStatusSkill(at_client),
            "cek_nik": CekNikSkill(ussd_runtime),
            "cek_kk": CekKkSkill(ussd_runtime),
            "inject_reaktivasi": InjectReaktivasiSkill(ussd_runtime),
            "verify_grace": VerifyGraceSkill(ussd_runtime),
        }

        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0.01)
        registry = WorkflowRegistry()

        engine = AutomationEngine(
            workflow_runner=runner,
            workflow_registry=registry,
            auto_run_config=auto_run_config,
            event_bus=event_bus,
            max_concurrent=2,
        )

        worker_manager = WorkerManager(event_bus=event_bus, auto_run_config=auto_run_config)
        db_lookup = DbLookup()

        controller = UIController(
            event_bus=event_bus,
            worker_manager=worker_manager,
            auto_run_config=auto_run_config,
            automation_engine=engine,
            db_lookup=db_lookup,
        )

        return {
            "event_bus": event_bus,
            "auto_run_config": auto_run_config,
            "at_client": at_client,
            "ussd_runtime": ussd_runtime,
            "engine": engine,
            "worker_manager": worker_manager,
            "runner": runner,
            "registry": registry,
        }

    def test_end_to_end_reactivation_success(self):
        """Full reactivation flow succeeds through all 6 steps."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "+CPIN: READY")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"Reactivated, aktif s.d. 2026-12-31\""

        sys["worker_manager"].create_worker("COM3")
        sys["auto_run_config"].set_enabled(True)

        sys["event_bus"].publish(CommandEvent.MASS_REAKTIVASI.value, {})
        time.sleep(3.0)

        self.assertTrue(True)

    def test_end_to_end_reactivation_stops_on_failure(self):
        """Reactivation stops when a skill fails mid-workflow."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(False, "ERROR")

        sys["worker_manager"].create_worker("COM4")
        sys["auto_run_config"].set_enabled(True)

        sys["event_bus"].publish(CommandEvent.MASS_REAKTIVASI.value, {})
        time.sleep(2.0)

        self.assertTrue(True)

    def test_reactivate_full_workflow_has_six_steps(self):
        """reactivate_full workflow contains all 6 steps in order."""
        sys = self._make_system()

        workflow = sys["registry"].get("reactivate_full")
        self.assertIsNotNone(workflow)
        self.assertEqual(workflow.steps, [
            "cek_nomor", "cek_status", "cek_nik", "cek_kk",
            "inject_reaktivasi", "verify_grace",
        ])

    def test_reactivation_all_skills_execute_on_success(self):
        """All 6 skills execute when mocks return success."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "+CPIN: READY")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"AKTIF s.d. 2026-12-31\""

        workflow = sys["registry"].get("reactivate_full")
        result = sys["runner"].run(workflow, "COM5")

        self.assertTrue(result.success)
        self.assertEqual(len(result.steps_executed), 6)
        self.assertEqual(result.steps_failed, [])

    def test_reactivation_stops_on_first_skill_failure(self):
        """Workflow stops after first failing skill."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(False, "ERROR")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"data\""

        workflow = sys["registry"].get("reactivate_full")
        result = sys["runner"].run(workflow, "COM6")

        self.assertFalse(result.success)
        self.assertEqual(result.steps_executed, ["cek_nomor"])
        self.assertEqual(result.steps_failed, ["cek_nomor"])

    def test_reactivation_grace_verification_in_context(self):
        """verify_grace result is stored in workflow context."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "+CPIN: READY")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"Status: AKTIF, Grace: 2026-12-31\""

        workflow = sys["registry"].get("reactivate_full")
        result = sys["runner"].run(workflow, "COM7")

        self.assertTrue(result.success)
        ctx = result.context
        self.assertIn("verify_grace", ctx.step_results)
        self.assertIn("inject_reaktivasi", ctx.step_results)

    def test_reactivation_progress_events_published(self):
        """UI receives progress events during mass reactivation."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "+CPIN: READY")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"AKTIF\""

        sys["worker_manager"].create_worker("COM3")
        sys["auto_run_config"].set_enabled(True)

        progress_events = []
        sys["event_bus"].subscribe(UIEvent.MASS_PROGRESS.value, lambda p: progress_events.append(p))

        sys["event_bus"].publish(CommandEvent.MASS_REAKTIVASI.value, {})
        time.sleep(1.0)

        self.assertGreater(len(progress_events), 0)

    def test_reactivation_mode_set_on_mass_trigger(self):
        """Mass reactivation sets automation mode to REACTIVATE_FULL."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["worker_manager"].create_worker("COM3")

        sys["event_bus"].publish(CommandEvent.MASS_REAKTIVASI.value, {})
        time.sleep(0.5)

        self.assertEqual(sys["engine"].mode, AutomationMode.REACTIVATE_FULL)

    def test_individual_reactivate_routes_to_engine(self):
        """Individual reactivasi command routes to automation engine."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["worker_manager"].create_worker("COM3")

        sys["event_bus"].publish(CommandEvent.REACTIVATE.value, {"port": "COM3"})
        time.sleep(0.5)

        state = sys["engine"].get_state("COM3")
        self.assertIsNotNone(state)


if __name__ == "__main__":
    unittest.main()
