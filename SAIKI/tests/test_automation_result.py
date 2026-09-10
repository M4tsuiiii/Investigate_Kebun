"""Tests for automation.result — AutomationResult."""

import unittest

from automation.result import AutomationResult


class TestAutomationResult(unittest.TestCase):
    """Test AutomationResult — outcome of an automation cycle."""

    def test_initial_defaults(self) -> None:
        """Verify default field values on creation."""
        result = AutomationResult()
        self.assertEqual(result.port, "")
        self.assertEqual(result.workflow_name, "")
        self.assertFalse(result.success)
        self.assertEqual(result.started_at, 0.0)
        self.assertEqual(result.finished_at, 0.0)
        self.assertEqual(result.trigger, "")
        self.assertIsNone(result.workflow_result)
        self.assertEqual(result.error, "")
        self.assertFalse(result.retried)

    def test_duration_seconds(self) -> None:
        """Verify duration_seconds computes difference correctly."""
        result = AutomationResult(started_at=100.0, finished_at=105.5)
        self.assertAlmostEqual(result.duration_seconds, 5.5, places=1)

    def test_duration_seconds_zero_when_no_times(self) -> None:
        """Verify duration_seconds returns 0.0 when timestamps missing."""
        result = AutomationResult()
        self.assertEqual(result.duration_seconds, 0.0)

    def test_duration_seconds_zero_when_only_started(self) -> None:
        """Verify duration_seconds returns 0.0 when only started_at set."""
        result = AutomationResult(started_at=100.0)
        self.assertEqual(result.duration_seconds, 0.0)

    def test_to_dict(self) -> None:
        """Verify to_dict returns all expected keys."""
        result = AutomationResult(
            port="COM3",
            workflow_name="reactivate_full",
            success=True,
            started_at=100.0,
            finished_at=105.0,
            trigger="MODEM_ONLINE",
            error="",
            retried=False,
        )
        d = result.to_dict()
        self.assertEqual(d["port"], "COM3")
        self.assertEqual(d["workflow_name"], "reactivate_full")
        self.assertTrue(d["success"])
        self.assertEqual(d["started_at"], 100.0)
        self.assertEqual(d["finished_at"], 105.0)
        self.assertEqual(d["duration_seconds"], 5.0)
        self.assertEqual(d["trigger"], "MODEM_ONLINE")
        self.assertEqual(d["error"], "")
        self.assertFalse(d["retried"])

    def test_repr(self) -> None:
        """Verify repr format includes port, workflow, and success."""
        result = AutomationResult(
            port="COM5",
            workflow_name="check_data",
            success=True,
        )
        r = repr(result)
        self.assertIn("AutomationResult", r)
        self.assertIn("COM5", r)
        self.assertIn("check_data", r)
        self.assertIn("True", r)

    def test_to_dict_with_error(self) -> None:
        """Verify to_dict includes error message."""
        result = AutomationResult(
            port="COM3",
            workflow_name="reactivate_full",
            error="timeout",
        )
        d = result.to_dict()
        self.assertEqual(d["error"], "timeout")

    def test_retried_flag(self) -> None:
        """Verify retried flag can be set to True."""
        result = AutomationResult(retried=True)
        self.assertTrue(result.retried)


if __name__ == "__main__":
    unittest.main()
