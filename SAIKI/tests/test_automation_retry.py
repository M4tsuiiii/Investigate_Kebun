"""Tests for automation.retry — ReactivateRetryPolicy."""

import unittest

from automation.retry import ReactivateRetryPolicy, MAX_REACTIVATION_RETRY


class TestReactivateRetryPolicy(unittest.TestCase):
    """Test ReactivateRetryPolicy — reactivation retry logic."""

    def test_should_retry_when_grace_unchanged_and_attempt_0(self) -> None:
        """Verify should_retry returns True when grace unchanged and attempt < max."""
        policy = ReactivateRetryPolicy()
        self.assertTrue(policy.should_retry(grace_before="2026-09-01", grace_after="2026-09-01", attempt=0))

    def test_should_not_retry_when_grace_changed(self) -> None:
        """Verify should_retry returns False when grace changed."""
        policy = ReactivateRetryPolicy()
        self.assertFalse(policy.should_retry(grace_before="2026-09-01", grace_after="2026-10-01", attempt=0))

    def test_should_not_retry_when_attempt_exhausted(self) -> None:
        """Verify should_retry returns False when attempt >= max_retries."""
        policy = ReactivateRetryPolicy(max_retries=2)
        self.assertFalse(policy.should_retry(grace_before="2026-09-01", grace_after="2026-09-01", attempt=2))

    def test_should_not_retry_when_attempt_equals_max(self) -> None:
        """Verify should_retry returns False when attempt == max_retries."""
        policy = ReactivateRetryPolicy(max_retries=1)
        self.assertFalse(policy.should_retry(grace_before="2026-09-01", grace_after="2026-09-01", attempt=1))

    def test_evaluate_result_success_when_grace_changed(self) -> None:
        """Verify evaluate_result returns success when grace changed."""
        policy = ReactivateRetryPolicy()
        success, reason = policy.evaluate_result(
            grace_before="2026-09-01",
            grace_after="2026-10-01",
            attempt=0,
        )
        self.assertTrue(success)
        self.assertIn("changed", reason.lower())

    def test_evaluate_result_retry_when_unchanged(self) -> None:
        """Verify evaluate_result returns not-success (retry) when grace unchanged."""
        policy = ReactivateRetryPolicy(max_retries=2)
        success, reason = policy.evaluate_result(
            grace_before="2026-09-01",
            grace_after="2026-09-01",
            attempt=0,
        )
        self.assertFalse(success)
        self.assertIn("retry", reason.lower())

    def test_evaluate_result_failed_when_exhausted(self) -> None:
        """Verify evaluate_result returns failed when retries exhausted."""
        policy = ReactivateRetryPolicy(max_retries=1)
        success, reason = policy.evaluate_result(
            grace_before="2026-09-01",
            grace_after="2026-09-01",
            attempt=1,
        )
        self.assertFalse(success)
        self.assertIn("FAILED", reason)

    def test_max_retries_property(self) -> None:
        """Verify max_retries returns configured value."""
        policy = ReactivateRetryPolicy()
        self.assertEqual(policy.max_retries, MAX_REACTIVATION_RETRY)

    def test_custom_max_retries(self) -> None:
        """Verify custom max_retries is stored correctly."""
        policy = ReactivateRetryPolicy(max_retries=3)
        self.assertEqual(policy.max_retries, 3)

    def test_default_max_retries_constant(self) -> None:
        """Verify MAX_REACTIVATION_RETRY is 1."""
        self.assertEqual(MAX_REACTIVATION_RETRY, 1)


if __name__ == "__main__":
    unittest.main()
