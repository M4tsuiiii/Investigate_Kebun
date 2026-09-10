"""Tests for workflow.exceptions.

Exceptions: WorkflowError (base), SkillNotFoundError, WorkflowExecutionError.
"""

import unittest

from workflow.exceptions import (
    WorkflowError,
    SkillNotFoundError,
    WorkflowExecutionError,
)


class TestWorkflowError(unittest.TestCase):
    """Test WorkflowError base exception."""

    def test_workflow_error_message(self) -> None:
        err = WorkflowError("something went wrong")
        self.assertEqual(str(err), "something went wrong")


class TestSkillNotFoundError(unittest.TestCase):
    """Test SkillNotFoundError exception."""

    def test_skill_not_found_error_message(self) -> None:
        err = SkillNotFoundError("cek_nomor")
        self.assertIn("cek_nomor", str(err))
        self.assertIn("Skill not found", str(err))

    def test_skill_not_found_error_attribute(self) -> None:
        err = SkillNotFoundError("inject_reaktivasi")
        self.assertEqual(err.skill_name, "inject_reaktivasi")

    def test_skill_not_found_is_workflow_error(self) -> None:
        err = SkillNotFoundError("test")
        self.assertIsInstance(err, WorkflowError)
        self.assertIsInstance(err, Exception)


class TestWorkflowExecutionError(unittest.TestCase):
    """Test WorkflowExecutionError exception."""

    def test_workflow_execution_error_message(self) -> None:
        err = WorkflowExecutionError("check_data", "cek_nik", "timeout")
        msg = str(err)
        self.assertIn("check_data", msg)
        self.assertIn("cek_nik", msg)
        self.assertIn("timeout", msg)

    def test_workflow_execution_error_attributes(self) -> None:
        err = WorkflowExecutionError("reactivate_full", "verify_grace", "bad response")
        self.assertEqual(err.workflow_name, "reactivate_full")
        self.assertEqual(err.step, "verify_grace")
        self.assertEqual(err.error, "bad response")

    def test_workflow_execution_error_is_workflow_error(self) -> None:
        err = WorkflowExecutionError("wf", "step", "err")
        self.assertIsInstance(err, WorkflowError)
        self.assertIsInstance(err, Exception)


if __name__ == "__main__":
    unittest.main()
