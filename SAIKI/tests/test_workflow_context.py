"""Tests for workflow.context — WorkflowContext.

WorkflowContext is the shared memory for a single workflow execution.
One context per workflow run, thread-safe, destroyed after completion.
"""

import threading
import unittest

from workflow.context import WorkflowContext


class TestWorkflowContextDefaults(unittest.TestCase):
    """Test WorkflowContext default field values."""

    def test_initial_defaults(self) -> None:
        ctx = WorkflowContext()
        self.assertEqual(ctx.port, "")
        self.assertEqual(ctx.nomor, "")
        self.assertEqual(ctx.nik, "")
        self.assertEqual(ctx.kk, "")
        self.assertEqual(ctx.status_awal, "")
        self.assertEqual(ctx.status_akhir, "")
        self.assertEqual(ctx.grace_awal, "")
        self.assertEqual(ctx.grace_akhir, "")
        self.assertEqual(ctx.injection_attempt, 0)
        self.assertEqual(ctx.step_results, {})
        self.assertEqual(ctx.metadata, {})


class TestWorkflowContextUpdate(unittest.TestCase):
    """Test WorkflowContext.update method."""

    def test_update_sets_attribute(self) -> None:
        ctx = WorkflowContext()
        ctx.update("port", "COM3")
        self.assertEqual(ctx.port, "COM3")

    def test_update_thread_safe(self) -> None:
        ctx = WorkflowContext()
        errors: list[Exception] = []

        def writer(key: str, value: str) -> None:
            try:
                for _ in range(200):
                    ctx.update(key, value)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=("nomor", "12345"))
        t2 = threading.Thread(target=writer, args=("nik", "67890"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [])
        self.assertIn(ctx.nomor, ("12345", ""))
        self.assertIn(ctx.nik, ("67890", ""))


class TestWorkflowContextGet(unittest.TestCase):
    """Test WorkflowContext.get method."""

    def test_get_returns_value(self) -> None:
        ctx = WorkflowContext(port="COM5")
        self.assertEqual(ctx.get("port"), "COM5")

    def test_get_returns_default_for_missing(self) -> None:
        ctx = WorkflowContext()
        self.assertIsNone(ctx.get("nonexistent"))
        self.assertEqual(ctx.get("nonexistent", "fallback"), "fallback")


class TestWorkflowContextStepResults(unittest.TestCase):
    """Test WorkflowContext step result storage."""

    def test_store_step_result(self) -> None:
        ctx = WorkflowContext()
        ctx.store_step_result("cek_nomor", {"found": True, "nomor": "08123"})
        self.assertIn("cek_nomor", ctx.step_results)

    def test_get_step_result_returns_data(self) -> None:
        ctx = WorkflowContext()
        data = {"found": True, "nomor": "08123"}
        ctx.store_step_result("cek_nomor", data)
        result = ctx.get_step_result("cek_nomor")
        self.assertEqual(result, data)

    def test_get_step_result_returns_none_when_missing(self) -> None:
        ctx = WorkflowContext()
        self.assertIsNone(ctx.get_step_result("nonexistent_step"))


class TestWorkflowContextSnapshot(unittest.TestCase):
    """Test WorkflowContext.snapshot method."""

    def test_snapshot_returns_dict(self) -> None:
        ctx = WorkflowContext(port="COM3")
        snap = ctx.snapshot()
        self.assertIsInstance(snap, dict)

    def test_snapshot_contains_all_fields(self) -> None:
        ctx = WorkflowContext(
            port="COM3",
            nomor="08123",
            nik="3201234567890001",
            kk="3201234567890002",
            status_awal="active",
            status_akhir="inactive",
            grace_awal="10",
            grace_akhir="0",
            injection_attempt=2,
        )
        ctx.store_step_result("cek_nomor", {"found": True})
        ctx.metadata["source"] = "test"

        snap = ctx.snapshot()
        self.assertEqual(snap["port"], "COM3")
        self.assertEqual(snap["nomor"], "08123")
        self.assertEqual(snap["nik"], "3201234567890001")
        self.assertEqual(snap["kk"], "3201234567890002")
        self.assertEqual(snap["status_awal"], "active")
        self.assertEqual(snap["status_akhir"], "inactive")
        self.assertEqual(snap["grace_awal"], "10")
        self.assertEqual(snap["grace_akhir"], "0")
        self.assertEqual(snap["injection_attempt"], 2)
        self.assertIn("cek_nomor", snap["step_results"])
        self.assertEqual(snap["metadata"]["source"], "test")


class TestWorkflowContextClear(unittest.TestCase):
    """Test WorkflowContext.clear method."""

    def test_clear_resets_all(self) -> None:
        ctx = WorkflowContext(
            port="COM3",
            nomor="08123",
            nik="3201234567890001",
            injection_attempt=5,
        )
        ctx.store_step_result("step", {"data": 1})
        ctx.metadata["key"] = "val"

        ctx.clear()

        self.assertEqual(ctx.port, "")
        self.assertEqual(ctx.nomor, "")
        self.assertEqual(ctx.nik, "")
        self.assertEqual(ctx.kk, "")
        self.assertEqual(ctx.status_awal, "")
        self.assertEqual(ctx.status_akhir, "")
        self.assertEqual(ctx.grace_awal, "")
        self.assertEqual(ctx.grace_akhir, "")
        self.assertEqual(ctx.injection_attempt, 0)
        self.assertEqual(ctx.step_results, {})
        self.assertEqual(ctx.metadata, {})


class TestWorkflowContextPerPort(unittest.TestCase):
    """Test that different ports do not share context data."""

    def test_context_per_port(self) -> None:
        ctx_a = WorkflowContext(port="COM3")
        ctx_b = WorkflowContext(port="COM5")

        ctx_a.update("nomor", "08123")
        ctx_b.update("nomor", "09999")

        self.assertEqual(ctx_a.get("nomor"), "08123")
        self.assertEqual(ctx_b.get("nomor"), "09999")


if __name__ == "__main__":
    unittest.main()
