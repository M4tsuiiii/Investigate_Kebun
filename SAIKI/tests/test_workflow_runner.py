"""Tests for workflow.runner — WorkflowRunner.

WorkflowRunner orchestrates skill execution with cleanup discipline.
Pipeline: load → resolve → execute → update context → cleanup → cooldown → next.
Failure: STOP on first skill failure.
"""

import threading
import time
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from workflow.context import WorkflowContext
from workflow.definitions import WorkflowDefinition
from workflow.exceptions import SkillNotFoundError, WorkflowError
from workflow.registry import WorkflowRegistry
from workflow.result import WorkflowResult
from workflow.runner import WorkflowRunner
from worker.skills.base import SkillResult


def _make_skill(
    name: str,
    success: bool = True,
    data: Dict[str, Any] | None = None,
    error: str = "",
) -> MagicMock:
    """Create a mock skill that returns a SkillResult."""
    skill = MagicMock()
    skill.name = name
    skill.execute.return_value = SkillResult(
        success=success,
        data=data or {},
        error=error,
        skill_name=name,
        port="COM3",
    )
    return skill


def _make_failing_skill(name: str, error: str = "skill failed") -> MagicMock:
    """Create a mock skill whose execute raises an exception."""
    skill = MagicMock()
    skill.name = name
    skill.execute.side_effect = RuntimeError(error)
    return skill


def _make_cleanup() -> MagicMock:
    """Create a mock CleanupManager."""
    cleanup = MagicMock()
    cleanup.close_session = MagicMock()
    cleanup.clear_buffer = MagicMock()
    cleanup.cooldown = MagicMock()
    return cleanup


class TestWorkflowRunnerSuccess(unittest.TestCase):
    """Test successful workflow execution."""

    @patch("workflow.runner.time.sleep")
    def test_run_success_all_steps(self, mock_sleep: MagicMock) -> None:
        skill_map = {
            "step_a": _make_skill("step_a", data={"a": 1}),
            "step_b": _make_skill("step_b", data={"b": 2}),
            "step_c": _make_skill("step_c", data={"c": 3}),
        }
        wf = WorkflowDefinition(name="test_wf", steps=["step_a", "step_b", "step_c"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run(wf, port="COM3")

        self.assertTrue(result.success)
        self.assertEqual(result.steps_executed, ["step_a", "step_b", "step_c"])
        self.assertEqual(result.steps_failed, [])
        self.assertEqual(result.workflow_name, "test_wf")

    @patch("workflow.runner.time.sleep")
    def test_run_updates_context(self, mock_sleep: MagicMock) -> None:
        skill_map = {
            "step_a": _make_skill("step_a", data={"nomor": "08123"}),
            "step_b": _make_skill("step_b", data={"nik": "320123"}),
        }
        wf = WorkflowDefinition(name="test_wf", steps=["step_a", "step_b"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run(wf, port="COM3")

        ctx = result.context
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.get_step_result("step_a"), {"nomor": "08123"})
        self.assertEqual(ctx.get_step_result("step_b"), {"nik": "320123"})

    @patch("workflow.runner.time.sleep")
    def test_run_publishes_result_with_all_steps(self, mock_sleep: MagicMock) -> None:
        skill_map = {
            "a": _make_skill("a"),
            "b": _make_skill("b"),
        }
        wf = WorkflowDefinition(name="pub_wf", steps=["a", "b"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run(wf, port="COM3")

        self.assertIsInstance(result, WorkflowResult)
        self.assertTrue(result.success)
        self.assertEqual(len(result.steps_executed), 2)
        self.assertGreater(result.duration_seconds, 0)


class TestWorkflowRunnerFailure(unittest.TestCase):
    """Test workflow failure and stop-on-first-failure."""

    @patch("workflow.runner.time.sleep")
    def test_run_failure_stops_on_first_failure(self, mock_sleep: MagicMock) -> None:
        skill_b = _make_skill("step_b", success=False, error="bad input")
        skill_map = {
            "step_a": _make_skill("step_a"),
            "step_b": skill_b,
            "step_c": _make_skill("step_c"),
        }
        wf = WorkflowDefinition(
            name="fail_wf", steps=["step_a", "step_b", "step_c"]
        )
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run(wf, port="COM3")

        self.assertFalse(result.success)
        self.assertEqual(result.steps_executed, ["step_a", "step_b"])
        self.assertEqual(result.steps_failed, ["step_b"])
        self.assertIn("step_b: bad input", result.errors[0])
        skill_b.execute.assert_called_once()

    @patch("workflow.runner.time.sleep")
    def test_run_publishes_result_with_failed_step(self, mock_sleep: MagicMock) -> None:
        skill_map = {
            "step_a": _make_skill("step_a"),
            "step_b": _make_skill("step_b", success=False, error="fail"),
        }
        wf = WorkflowDefinition(name="fail_wf", steps=["step_a", "step_b"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run(wf, port="COM3")

        self.assertFalse(result.success)
        self.assertEqual(result.failed_step, "step_b")
        self.assertEqual(result.last_step, "step_b")

    @patch("workflow.runner.time.sleep")
    def test_run_cleans_up_after_failure(self, mock_sleep: MagicMock) -> None:
        cleanup = _make_cleanup()
        skill_map = {
            "step_a": _make_skill("step_a"),
            "step_b": _make_skill("step_b", success=False, error="boom"),
        }
        wf = WorkflowDefinition(name="fail_wf", steps=["step_a", "step_b"])
        runner = WorkflowRunner(
            skill_map=skill_map, cleanup_manager=cleanup, cooldown_seconds=0
        )

        result = runner.run(wf, port="COM3")

        self.assertFalse(result.success)
        cleanup.close_session.assert_called()


class TestWorkflowRunnerSkillNotFound(unittest.TestCase):
    """Test SkillNotFoundError when skill is missing."""

    def test_run_skill_not_found_raises(self) -> None:
        skill_map = {}  # no skills registered
        wf = WorkflowDefinition(name="missing_wf", steps=["nonexistent_skill"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        with self.assertRaises(SkillNotFoundError) as ctx:
            runner.run(wf, port="COM3")

        self.assertEqual(ctx.exception.skill_name, "nonexistent_skill")


class TestWorkflowRunnerContext(unittest.TestCase):
    """Test custom context handling."""

    @patch("workflow.runner.time.sleep")
    def test_run_with_custom_context(self, mock_sleep: MagicMock) -> None:
        skill_map = {"step_a": _make_skill("step_a")}
        wf = WorkflowDefinition(name="custom_wf", steps=["step_a"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        ctx = WorkflowContext(port="COM9")
        ctx.update("nomor", "existing_value")

        result = runner.run(wf, port="COM3", context=ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.context.get("port"), "COM3")
        self.assertEqual(result.context.get("nomor"), "existing_value")


class TestWorkflowRunnerCallback(unittest.TestCase):
    """Test on_step_complete callback."""

    @patch("workflow.runner.time.sleep")
    def test_run_on_step_complete_callback(self, mock_sleep: MagicMock) -> None:
        calls: list[tuple[str, Any, WorkflowContext]] = []
        skill_map = {
            "step_a": _make_skill("step_a", data={"x": 1}),
            "step_b": _make_skill("step_b", data={"y": 2}),
        }
        wf = WorkflowDefinition(name="cb_wf", steps=["step_a", "step_b"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        def on_complete(step_name: str, skill_result: Any, ctx: WorkflowContext) -> None:
            calls.append((step_name, skill_result, ctx))

        runner.run(wf, port="COM3", on_step_complete=on_complete)

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "step_a")
        self.assertEqual(calls[1][0], "step_b")


class TestWorkflowRunnerByName(unittest.TestCase):
    """Test run_by_name method."""

    @patch("workflow.runner.time.sleep")
    def test_run_by_name_success(self, mock_sleep: MagicMock) -> None:
        skill_map = {
            "cek_nomor": _make_skill("cek_nomor"),
            "cek_nik": _make_skill("cek_nik"),
            "cek_kk": _make_skill("cek_kk"),
        }
        registry = WorkflowRegistry()
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run_by_name("check_data", port="COM3", registry=registry)

        self.assertTrue(result.success)
        self.assertEqual(result.workflow_name, "check_data")
        self.assertEqual(result.steps_executed, ["cek_nomor", "cek_nik", "cek_kk"])

    def test_run_by_name_unknown_raises(self) -> None:
        skill_map = {}
        registry = WorkflowRegistry()
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        with self.assertRaises(WorkflowError) as ctx:
            runner.run_by_name("nonexistent", port="COM3", registry=registry)

        self.assertIn("nonexistent", str(ctx.exception))


class TestWorkflowRunnerParallel(unittest.TestCase):
    """Test thread-safe parallel workflow execution."""

    @patch("workflow.runner.time.sleep")
    def test_run_multiple_workflows_parallel(self, mock_sleep: MagicMock) -> None:
        skill_map = {
            "step_a": _make_skill("step_a", data={"val": 1}),
        }
        wf = WorkflowDefinition(name="parallel_wf", steps=["step_a"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        results: list[WorkflowResult] = []
        barrier = threading.Barrier(3)

        def run_worker(port: str) -> None:
            barrier.wait()
            r = runner.run(wf, port=port)
            results.append(r)

        threads = [
            threading.Thread(target=run_worker, args=("COM3",)),
            threading.Thread(target=run_worker, args=("COM5",)),
            threading.Thread(target=run_worker, args=("COM7",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.success for r in results))
        ports = {r.context.get("port") for r in results if r.context}
        self.assertEqual(ports, {"COM3", "COM5", "COM7"})


class TestWorkflowRunnerEdgeCases(unittest.TestCase):
    """Test edge cases and utilities."""

    @patch("workflow.runner.time.sleep")
    def test_run_empty_workflow(self, mock_sleep: MagicMock) -> None:
        skill_map: Dict[str, MagicMock] = {}
        wf = WorkflowDefinition(name="empty_wf", steps=[])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run(wf, port="COM3")

        self.assertTrue(result.success)
        self.assertEqual(result.steps_executed, [])
        self.assertEqual(result.steps_failed, [])

    @patch("workflow.runner.time.sleep")
    def test_run_calls_cleanup_between_steps(self, mock_sleep: MagicMock) -> None:
        cleanup = _make_cleanup()
        skill_map = {
            "a": _make_skill("a"),
            "b": _make_skill("b"),
            "c": _make_skill("c"),
        }
        wf = WorkflowDefinition(name="clean_wf", steps=["a", "b", "c"])
        runner = WorkflowRunner(
            skill_map=skill_map, cleanup_manager=cleanup, cooldown_seconds=1.0
        )

        result = runner.run(wf, port="COM3")

        self.assertTrue(result.success)
        self.assertEqual(cleanup.close_session.call_count, 2)
        self.assertEqual(cleanup.clear_buffer.call_count, 2)
        cleanup.cooldown.assert_called_with(1.0)

    def test_skill_names_property(self) -> None:
        skill_map = {
            "cek_nomor": _make_skill("cek_nomor"),
            "cek_nik": _make_skill("cek_nik"),
        }
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        names = runner.skill_names

        self.assertIsInstance(names, list)
        self.assertIn("cek_nomor", names)
        self.assertIn("cek_nik", names)

    @patch("workflow.runner.time.sleep")
    def test_run_uses_custom_cooldown(self, mock_sleep: MagicMock) -> None:
        cleanup = _make_cleanup()
        skill_map = {
            "a": _make_skill("a"),
            "b": _make_skill("b"),
        }
        wf = WorkflowDefinition(name="cd_wf", steps=["a", "b"])
        runner = WorkflowRunner(
            skill_map=skill_map, cleanup_manager=cleanup, cooldown_seconds=8.0
        )

        runner.run(wf, port="COM3")

        cleanup.cooldown.assert_called_with(8.0)


class TestWorkflowRunnerSkillException(unittest.TestCase):
    """Test skill that raises an exception during execute."""

    @patch("workflow.runner.time.sleep")
    def test_run_skill_exception_captured_as_failure(self, mock_sleep: MagicMock) -> None:
        skill_map = {
            "explode": _make_failing_skill("explode", "connection lost"),
        }
        wf = WorkflowDefinition(name="exc_wf", steps=["explode"])
        runner = WorkflowRunner(skill_map=skill_map, cooldown_seconds=0)

        result = runner.run(wf, port="COM3")

        self.assertFalse(result.success)
        self.assertIn("explode", result.steps_executed)
        self.assertIn("explode", result.steps_failed)


if __name__ == "__main__":
    unittest.main()
