"""Tests for workflow.registry — WorkflowRegistry.

WorkflowRegistry stores and retrieves workflow definitions.
Pre-registers 5 built-in workflows on init.
"""

import unittest

from workflow.definitions import WorkflowDefinition
from workflow.registry import WorkflowRegistry


class TestWorkflowRegistryDefaults(unittest.TestCase):
    """Test pre-registered workflows."""

    def test_default_workflows_registered(self) -> None:
        reg = WorkflowRegistry()
        names = reg.list_workflows()
        self.assertEqual(len(names), 5)
        self.assertIn("check_data", names)
        self.assertIn("reactivate_fast", names)
        self.assertIn("reactivate_full", names)
        self.assertIn("hardware_restart", names)
        self.assertIn("hardware_reset", names)

    def test_get_returns_workflow(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.get("check_data")
        self.assertIsNotNone(wf)
        self.assertIsInstance(wf, WorkflowDefinition)
        self.assertEqual(wf.name, "check_data")

    def test_get_returns_none_for_unknown(self) -> None:
        reg = WorkflowRegistry()
        self.assertIsNone(reg.get("nonexistent"))


class TestWorkflowRegistryList(unittest.TestCase):
    """Test list methods."""

    def test_list_workflows_returns_names(self) -> None:
        reg = WorkflowRegistry()
        names = reg.list_workflows()
        self.assertIsInstance(names, list)
        self.assertTrue(all(isinstance(n, str) for n in names))

    def test_list_definitions_returns_objects(self) -> None:
        reg = WorkflowRegistry()
        defs = reg.list_definitions()
        self.assertIsInstance(defs, list)
        self.assertTrue(all(isinstance(d, WorkflowDefinition) for d in defs))
        self.assertEqual(len(defs), 5)


class TestWorkflowRegistryHas(unittest.TestCase):
    """Test has method."""

    def test_has_true_for_registered(self) -> None:
        reg = WorkflowRegistry()
        self.assertTrue(reg.has("check_data"))
        self.assertTrue(reg.has("reactivate_fast"))
        self.assertTrue(reg.has("hardware_reset"))

    def test_has_false_for_unknown(self) -> None:
        reg = WorkflowRegistry()
        self.assertFalse(reg.has("nonexistent"))
        self.assertFalse(reg.has(""))


class TestWorkflowRegistryRegister(unittest.TestCase):
    """Test register method."""

    def test_register_custom_workflow(self) -> None:
        reg = WorkflowRegistry()
        custom = WorkflowDefinition(
            name="custom_flow",
            description="A custom workflow",
            steps=["step_a", "step_b"],
        )
        reg.register(custom)

        self.assertTrue(reg.has("custom_flow"))
        wf = reg.get("custom_flow")
        self.assertIsNotNone(wf)
        self.assertEqual(wf.steps, ["step_a", "step_b"])
        self.assertEqual(len(reg.list_workflows()), 6)


class TestWorkflowRegistryRemove(unittest.TestCase):
    """Test remove method."""

    def test_remove_existing(self) -> None:
        reg = WorkflowRegistry()
        result = reg.remove("hardware_restart")
        self.assertTrue(result)
        self.assertFalse(reg.has("hardware_restart"))
        self.assertEqual(len(reg.list_workflows()), 4)

    def test_remove_non_existing_returns_false(self) -> None:
        reg = WorkflowRegistry()
        result = reg.remove("nonexistent")
        self.assertFalse(result)
        self.assertEqual(len(reg.list_workflows()), 5)


class TestWorkflowRegistryBuiltinSteps(unittest.TestCase):
    """Test step lists of pre-registered workflows."""

    def test_check_data_steps(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.get("check_data")
        self.assertEqual(wf.steps, ["cek_nomor", "cek_nik", "cek_kk"])

    def test_reactivate_full_steps(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.get("reactivate_full")
        self.assertEqual(wf.steps, [
            "cek_nomor", "cek_status", "cek_nik", "cek_kk",
            "inject_reaktivasi", "verify_grace",
        ])

    def test_reactivate_fast_steps(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.get("reactivate_fast")
        self.assertEqual(wf.steps, ["inject_reaktivasi", "verify_grace"])

    def test_hardware_restart_steps(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.get("hardware_restart")
        self.assertEqual(wf.steps, ["restart_hardware"])

    def test_hardware_reset_steps(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.get("hardware_reset")
        self.assertEqual(wf.steps, ["reset_hardware"])


if __name__ == "__main__":
    unittest.main()
