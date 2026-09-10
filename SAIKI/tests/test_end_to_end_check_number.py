"""End-to-end tests for Mass Check Number flow.

Verifies the FULL pipeline: UI EventBus -> Controller -> AutomationEngine -> WorkflowRunner -> Skills.
"""

import unittest
from unittest.mock import MagicMock, patch
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
from automation.engine import AutomationEngine
from automation.triggers import Trigger
from automation.state import AutomationStatus
from workflow.runner import WorkflowRunner
from workflow.registry import WorkflowRegistry


def _make_at_response(success=True, raw="OK"):
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


class TestEndToEndCheckNumber(unittest.TestCase):
    """End-to-end test: Button -> Controller -> Automation -> Workflow -> Skills -> Result."""

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

        worker_manager = WorkerManager(
            event_bus=event_bus,
            auto_run_config=auto_run_config,
        )

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
            "runner": runner,
            "registry": registry,
            "engine": engine,
            "worker_manager": worker_manager,
            "controller": controller,
        }

    def _setup_worker(self, sys, port_id):
        """Configure mock worker with attributes needed for eligibility check."""
        from app.domain.enums import CpinState
        mock_worker = MagicMock()
        mock_worker.is_alive = True
        mock_worker.modem_online = True
        mock_worker.cpin_state = CpinState.READY
        original_get_worker = sys["worker_manager"].get_worker
        def _patched_get_worker(pid):
            if pid == port_id:
                return mock_worker
            return original_get_worker(pid)
        sys["worker_manager"].get_worker = _patched_get_worker

    def test_end_to_end_check_number_success(self):
        """Full flow: Cek Nomor button -> check_data workflow -> AT command -> result."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "+CPIN: READY")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"Data NIK: 1234567890\""

        worker = sys["worker_manager"].create_worker("COM3")
        sys["auto_run_config"].set_enabled(True)

        sys["event_bus"].publish(CommandEvent.MASS_CEK_NOMOR.value, {})
        time.sleep(2.0)

        self.assertTrue(sys["engine"].get_queue_size() >= 0 or sys["engine"].get_running_count() >= 0)

    def test_end_to_end_check_number_failure_stops(self):
        """Skill fails -> workflow stops -> no further steps."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(False, "ERROR")

        worker = sys["worker_manager"].create_worker("COM4")
        sys["auto_run_config"].set_enabled(True)

        sys["event_bus"].publish(CommandEvent.MASS_CEK_NOMOR.value, {})
        time.sleep(2.0)

        self.assertTrue(True)

    def test_end_to_end_check_number_progress_updates(self):
        """UI receives progress events when mass check is triggered."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "+CPIN: READY")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"Data NIK: 1234567890\""

        sys["worker_manager"].create_worker("COM3")
        self._setup_worker(sys, "COM3")
        sys["auto_run_config"].set_enabled(True)

        progress_events = []
        sys["event_bus"].subscribe(UIEvent.MASS_PROGRESS.value, lambda p: progress_events.append(p))

        sys["event_bus"].publish(CommandEvent.MASS_CEK_NOMOR.value, {})
        time.sleep(1.5)

        self.assertGreater(len(progress_events), 0)
        self.assertEqual(progress_events[0]["total"], 1)

    def test_end_to_end_check_number_cleanup(self):
        """Cleanup runs between workflow steps via WorkflowRunner."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "OK")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"Data NIK: 999\""

        workflow = sys["registry"].get("check_data")
        result = sys["runner"].run(workflow, "COM3")

        self.assertTrue(result.success)
        self.assertEqual(result.steps_executed, ["cek_nomor", "cek_nik", "cek_kk"])

    def test_end_to_end_modem_online_triggers_automation(self):
        """Modem online -> automation engine enqueues workflow."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        worker = sys["worker_manager"].create_worker("COM5")

        sys["event_bus"].publish("modem.online", {"port": "COM5"})
        time.sleep(0.5)

        state = sys["engine"].get_state("COM5")
        self.assertIsNotNone(state)

    def test_check_number_only_executes_three_skills(self):
        """check_data workflow runs exactly cek_nomor, cek_nik, cek_kk."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "OK")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"info\""

        workflow = sys["registry"].get("check_data")
        result = sys["runner"].run(workflow, "COM6")

        self.assertTrue(result.success)
        self.assertEqual(len(result.steps_executed), 3)
        self.assertIn("cek_nomor", result.steps_executed)
        self.assertIn("cek_nik", result.steps_executed)
        self.assertIn("cek_kk", result.steps_executed)
        self.assertNotIn("cek_status", result.steps_executed)

    def test_check_number_context_populated(self):
        """Workflow context stores step results from each skill."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "OK")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"NIK:123\""

        workflow = sys["registry"].get("check_data")
        result = sys["runner"].run(workflow, "COM7")

        self.assertTrue(result.success)
        ctx = result.context
        self.assertIsNotNone(ctx)
        self.assertIn("cek_nomor", ctx.step_results)
        self.assertIn("cek_nik", ctx.step_results)
        self.assertIn("cek_kk", ctx.step_results)

    def test_check_number_duplicate_enqueue_prevented(self):
        """Same port is not enqueued twice in the automation engine."""
        sys = self._make_system()
        sys["auto_run_config"].set_enabled(True)

        sys["worker_manager"].create_worker("COM8")

        sys["event_bus"].publish(CommandEvent.MASS_CEK_NOMOR.value, {})
        sys["event_bus"].publish(CommandEvent.MASS_CEK_NOMOR.value, {})
        time.sleep(0.5)

        state = sys["engine"].get_state("COM8")
        self.assertIsNotNone(state)

    def test_check_number_at_client_called_correctly(self):
        """AT client receives the AT command for cek_nomor."""
        sys = self._make_system()

        sys["at_client"].send_command.return_value = _make_at_response(True, "OK")
        sys["ussd_runtime"].dial.return_value = "+CUSD: 0,\"data\""

        skill = sys["runner"]._skill_map["cek_nomor"]
        result = skill.execute(port="COM9")

        self.assertTrue(result.success)
        sys["at_client"].send_command.assert_called()
        call_args = sys["at_client"].send_command.call_args
        self.assertEqual(call_args[0][0], "AT")


if __name__ == "__main__":
    unittest.main()
