"""Tests for workflow.definitions — WorkflowDefinition.

WorkflowDefinition is a frozen dataclass describing an ordered list of
skill steps. Immutable once created.
"""

import unittest

from workflow.definitions import WorkflowDefinition


class TestWorkflowDefinitionCreation(unittest.TestCase):
    """Test WorkflowDefinition construction."""

    def test_creation_with_defaults(self) -> None:
        wf = WorkflowDefinition(name="test")
        self.assertEqual(wf.name, "test")
        self.assertEqual(wf.description, "")
        self.assertEqual(wf.steps, [])

    def test_creation_with_all_fields(self) -> None:
        wf = WorkflowDefinition(
            name="check_data",
            description="Check modem data",
            steps=["cek_nomor", "cek_nik", "cek_kk"],
        )
        self.assertEqual(wf.name, "check_data")
        self.assertEqual(wf.description, "Check modem data")
        self.assertEqual(wf.steps, ["cek_nomor", "cek_nik", "cek_kk"])


class TestWorkflowDefinitionStepCount(unittest.TestCase):
    """Test WorkflowDefinition.step_count."""

    def test_step_count(self) -> None:
        wf = WorkflowDefinition(
            name="reactivate_full",
            steps=["cek_nomor", "cek_status", "cek_nik", "cek_kk",
                    "inject_reaktivasi", "verify_grace"],
        )
        self.assertEqual(wf.step_count(), 6)

    def test_step_count_empty(self) -> None:
        wf = WorkflowDefinition(name="empty")
        self.assertEqual(wf.step_count(), 0)


class TestWorkflowDefinitionHasStep(unittest.TestCase):
    """Test WorkflowDefinition.has_step."""

    def test_has_step_true(self) -> None:
        wf = WorkflowDefinition(
            name="check_data",
            steps=["cek_nomor", "cek_nik", "cek_kk"],
        )
        self.assertTrue(wf.has_step("cek_nomor"))
        self.assertTrue(wf.has_step("cek_nik"))
        self.assertTrue(wf.has_step("cek_kk"))

    def test_has_step_false(self) -> None:
        wf = WorkflowDefinition(
            name="check_data",
            steps=["cek_nomor", "cek_nik", "cek_kk"],
        )
        self.assertFalse(wf.has_step("inject_reaktivasi"))
        self.assertFalse(wf.has_step("nonexistent"))


class TestWorkflowDefinitionRepr(unittest.TestCase):
    """Test WorkflowDefinition.__repr__."""

    def test_repr(self) -> None:
        wf = WorkflowDefinition(
            name="check_data",
            steps=["cek_nomor", "cek_nik"],
        )
        r = repr(wf)
        self.assertIn("check_data", r)
        self.assertIn("cek_nomor", r)
        self.assertIn("cek_nik", r)


class TestWorkflowDefinitionFrozen(unittest.TestCase):
    """Test WorkflowDefinition is immutable (frozen dataclass)."""

    def test_frozen(self) -> None:
        wf = WorkflowDefinition(
            name="check_data",
            steps=["cek_nomor"],
        )
        with self.assertRaises(AttributeError):
            wf.name = "modified"  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            wf.steps = []  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
