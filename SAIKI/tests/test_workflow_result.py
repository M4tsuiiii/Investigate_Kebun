"""Tests for workflow.result — WorkflowResult.

WorkflowResult tracks the outcome of a workflow execution including
success/failure, timing, steps executed, and error details.
"""

import unittest

from workflow.context import WorkflowContext
from workflow.result import WorkflowResult


class TestWorkflowResultDefaults(unittest.TestCase):
    """Test WorkflowResult default values."""

    def test_initial_defaults(self) -> None:
        r = WorkflowResult()
        self.assertEqual(r.workflow_name, "")
        self.assertFalse(r.success)
        self.assertEqual(r.started_at, 0.0)
        self.assertEqual(r.finished_at, 0.0)
        self.assertEqual(r.steps_executed, [])
        self.assertEqual(r.steps_failed, [])
        self.assertIsNone(r.context)
        self.assertEqual(r.errors, [])


class TestWorkflowResultDuration(unittest.TestCase):
    """Test WorkflowResult.duration_seconds property."""

    def test_duration_seconds(self) -> None:
        r = WorkflowResult(started_at=100.0, finished_at=105.5)
        self.assertAlmostEqual(r.duration_seconds, 5.5)

    def test_duration_seconds_zero_when_no_times(self) -> None:
        r = WorkflowResult()
        self.assertEqual(r.duration_seconds, 0.0)

    def test_duration_seconds_zero_when_only_started(self) -> None:
        r = WorkflowResult(started_at=100.0)
        self.assertEqual(r.duration_seconds, 0.0)


class TestWorkflowResultLastStep(unittest.TestCase):
    """Test WorkflowResult.last_step property."""

    def test_last_step(self) -> None:
        r = WorkflowResult(steps_executed=["cek_nomor", "cek_nik", "cek_kk"])
        self.assertEqual(r.last_step, "cek_kk")

    def test_last_step_none_when_empty(self) -> None:
        r = WorkflowResult()
        self.assertIsNone(r.last_step)


class TestWorkflowResultFailedStep(unittest.TestCase):
    """Test WorkflowResult.failed_step property."""

    def test_failed_step(self) -> None:
        r = WorkflowResult(
            steps_executed=["cek_nomor", "cek_nik"],
            steps_failed=["cek_nik"],
        )
        self.assertEqual(r.failed_step, "cek_nik")

    def test_failed_step_none_when_empty(self) -> None:
        r = WorkflowResult()
        self.assertIsNone(r.failed_step)


class TestWorkflowResultToDict(unittest.TestCase):
    """Test WorkflowResult.to_dict method."""

    def test_to_dict(self) -> None:
        r = WorkflowResult(
            workflow_name="check_data",
            success=True,
            started_at=100.0,
            finished_at=105.0,
            steps_executed=["cek_nomor", "cek_nik"],
            steps_failed=[],
            errors=[],
        )
        d = r.to_dict()
        self.assertEqual(d["workflow_name"], "check_data")
        self.assertTrue(d["success"])
        self.assertEqual(d["started_at"], 100.0)
        self.assertEqual(d["finished_at"], 105.0)
        self.assertEqual(d["duration_seconds"], 5.0)
        self.assertEqual(d["steps_executed"], ["cek_nomor", "cek_nik"])
        self.assertEqual(d["steps_failed"], [])
        self.assertEqual(d["errors"], [])
        self.assertIsNone(d["context"])

    def test_to_dict_with_context(self) -> None:
        ctx = WorkflowContext(port="COM3", nomor="08123")
        r = WorkflowResult(
            workflow_name="check_data",
            context=ctx,
        )
        d = r.to_dict()
        self.assertIsNotNone(d["context"])
        self.assertEqual(d["context"]["port"], "COM3")
        self.assertEqual(d["context"]["nomor"], "08123")


class TestWorkflowResultRepr(unittest.TestCase):
    """Test WorkflowResult.__repr__."""

    def test_repr(self) -> None:
        r = WorkflowResult(
            workflow_name="check_data",
            success=True,
            steps_executed=["cek_nomor", "cek_nik"],
        )
        s = repr(r)
        self.assertIn("check_data", s)
        self.assertIn("success=True", s)
        self.assertIn("steps=2", s)


if __name__ == "__main__":
    unittest.main()
