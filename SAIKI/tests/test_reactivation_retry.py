"""Tests for worker/reactivation_retry.py — inject-verify-retry flow."""

import time
import unittest
from unittest.mock import MagicMock, patch

from app.domain.enums import BusinessOutcome
from app.domain.constants import VERIFICATION_DELAY_SECONDS, DIAL_COOLDOWN_SECONDS
from worker.reactivation_retry import ReactivationResult, ReactivationRetry


class TestReactivationResult(unittest.TestCase):
    """Tests for ReactivationResult data class."""

    def test_is_success_true_for_sukses(self):
        """is_success should be True when outcome is SUKSES."""
        result = ReactivationResult(
            outcome=BusinessOutcome.SUKSES,
            attempts=1,
            message="done",
        )
        self.assertTrue(result.is_success)

    def test_is_success_false_for_failed(self):
        """is_success should be False when outcome is FAILED."""
        result = ReactivationResult(
            outcome=BusinessOutcome.FAILED,
            attempts=1,
            message="failed",
        )
        self.assertFalse(result.is_success)

    def test_is_success_false_for_tenggang(self):
        """is_success should be False when outcome is TENGGANG."""
        result = ReactivationResult(
            outcome=BusinessOutcome.TENGGANG,
            attempts=1,
            message="tenggang",
        )
        self.assertFalse(result.is_success)

    def test_repr_contains_outcome(self):
        """__repr__ should contain the outcome value."""
        result = ReactivationResult(
            outcome=BusinessOutcome.SUKSES,
            attempts=1,
            message="ok",
        )
        self.assertIn("SUKSES", repr(result))

    def test_repr_contains_attempts(self):
        """__repr__ should contain the attempts count."""
        result = ReactivationResult(
            outcome=BusinessOutcome.FAILED,
            attempts=2,
            message="err",
        )
        self.assertIn("2", repr(result))

    def test_attributes_stored(self):
        """All constructor attributes should be stored on the instance."""
        result = ReactivationResult(
            outcome=BusinessOutcome.SUKSES,
            attempts=1,
            initial_grace="2025-01-01",
            final_grace="2025-06-01",
            message="changed",
        )
        self.assertEqual(result.outcome, BusinessOutcome.SUKSES)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.initial_grace, "2025-01-01")
        self.assertEqual(result.final_grace, "2025-06-01")
        self.assertEqual(result.message, "changed")


class TestReactivationRetrySuccess(unittest.TestCase):
    """Tests for ReactivationRetry successful flows."""

    def setUp(self):
        """Create fresh ReactivationRetry with mock step executor."""
        self.step_executor = MagicMock()
        self.retry = ReactivationRetry(self.step_executor)

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_success_on_first_verify_grace_date_changed(self, mock_sleep):
        """execute should return SUKSES when grace date changes on first verify."""
        self.step_executor.execute.side_effect = [
            "initial_response",   # initial verify
            "inject_response",    # inject
            "final_response",     # final verify
        ]

        def parse_grace(response):
            if response == "initial_response":
                return "2025-01-01"
            return "2025-06-01"

        result = self.retry.execute(
            reactivation_command="*123#",
            parse_grace_fn=parse_grace,
        )

        self.assertTrue(result.is_success)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.initial_grace, "2025-01-01")
        self.assertEqual(result.final_grace, "2025-06-01")

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_success_on_retry_grace_date_changed(self, mock_sleep):
        """execute should return SUKSES with attempts=2 when grace changes on retry."""
        call_count = [0]

        def execute_side_effect(cmd):
            call_count[0] += 1
            if call_count[0] == 1:
                return "initial_response"  # initial verify
            elif call_count[0] == 2:
                return "inject_response"   # first inject
            elif call_count[0] == 3:
                return "unchanged_resp"    # first final verify (grace same)
            elif call_count[0] == 4:
                return "retry_inject"      # retry inject
            return "retry_verify"          # retry verify

        self.step_executor.execute.side_effect = execute_side_effect

        def parse_grace(response):
            if response == "initial_response":
                return "2025-01-01"
            elif response == "unchanged_resp":
                return "2025-01-01"
            return "2025-06-01"

        result = self.retry.execute(
            reactivation_command="*123#",
            parse_grace_fn=parse_grace,
        )

        self.assertTrue(result.is_success)
        self.assertEqual(result.attempts, 2)

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_failed_after_retry_grace_unchanged(self, mock_sleep):
        """execute should return FAILED when grace date is unchanged after retry."""
        call_count = [0]

        def execute_side_effect(cmd):
            call_count[0] += 1
            if call_count[0] == 1:
                return "initial"
            elif call_count[0] == 2:
                return "inject"
            elif call_count[0] == 3:
                return "verify1"
            elif call_count[0] == 4:
                return "retry_inject"
            return "retry_verify"

        self.step_executor.execute.side_effect = execute_side_effect

        def parse_grace(response):
            return "2025-01-01"

        result = self.retry.execute(
            reactivation_command="*123#",
            parse_grace_fn=parse_grace,
        )

        self.assertFalse(result.is_success)
        self.assertEqual(result.outcome, BusinessOutcome.FAILED)
        self.assertEqual(result.attempts, 2)

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_failed_on_injection_failure_no_response(self, mock_sleep):
        """execute should return FAILED when initial injection returns None."""
        self.step_executor.execute.side_effect = [
            "initial_verify",  # initial verify
            None,              # inject fails
        ]

        def parse_grace(response):
            return "2025-01-01"

        result = self.retry.execute(
            reactivation_command="*123#",
            parse_grace_fn=parse_grace,
        )

        self.assertFalse(result.is_success)
        self.assertEqual(result.outcome, BusinessOutcome.FAILED)
        self.assertEqual(result.attempts, 1)
        self.assertIn("no response", result.message)

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_failed_on_retry_injection_failure(self, mock_sleep):
        """execute should return FAILED when retry injection returns None."""
        self.step_executor.execute.side_effect = [
            "initial_verify",  # initial verify
            "inject_ok",       # first inject succeeds
            "verify_same",     # first verify (grace same)
            None,              # retry inject fails
        ]

        def parse_grace(response):
            if response == "initial_verify":
                return "2025-01-01"
            return "2025-01-01"

        result = self.retry.execute(
            reactivation_command="*123#",
            parse_grace_fn=parse_grace,
        )

        self.assertFalse(result.is_success)
        self.assertEqual(result.outcome, BusinessOutcome.FAILED)
        self.assertEqual(result.attempts, 2)
        self.assertIn("Retry injection failed", result.message)


class TestReactivationRetryGraceDateChanged(unittest.TestCase):
    """Tests for ReactivationRetry._grace_date_changed."""

    def setUp(self):
        """Create fresh ReactivationRetry."""
        self.retry = ReactivationRetry(MagicMock())

    def test_returns_true_when_different(self):
        """_grace_date_changed should return True when values differ."""
        self.assertTrue(self.retry._grace_date_changed("2025-01-01", "2025-06-01"))

    def test_returns_false_when_same(self):
        """_grace_date_changed should return False when values are the same."""
        self.assertFalse(self.retry._grace_date_changed("2025-01-01", "2025-01-01"))

    def test_returns_true_when_both_none(self):
        """_grace_date_changed should return True when both are None (best-effort)."""
        self.assertTrue(self.retry._grace_date_changed(None, None))

    def test_returns_true_when_initial_none(self):
        """_grace_date_changed should return True when initial is None."""
        self.assertTrue(self.retry._grace_date_changed(None, "2025-06-01"))

    def test_returns_true_when_final_none(self):
        """_grace_date_changed should return True when final is None."""
        self.assertTrue(self.retry._grace_date_changed("2025-01-01", None))

    def test_handles_whitespace_in_values(self):
        """_grace_date_changed should strip whitespace before comparing."""
        self.assertFalse(self.retry._grace_date_changed(" 2025-01-01 ", "2025-01-01"))
        self.assertTrue(self.retry._grace_date_changed(" 2025-01-01 ", " 2025-06-01 "))

    def test_empty_strings_are_same(self):
        """_grace_date_changed should treat empty strings as equal."""
        self.assertFalse(self.retry._grace_date_changed("", ""))


class TestReactivationRetryMaxRetries(unittest.TestCase):
    """Tests for ReactivationRetry.MAX_RETRIES constant."""

    def test_max_retries_is_one(self):
        """MAX_RETRIES should be 1 — single retry limit."""
        self.assertEqual(ReactivationRetry.MAX_RETRIES, 1)

    def test_max_retries_is_int(self):
        """MAX_RETRIES should be an integer."""
        self.assertIsInstance(ReactivationRetry.MAX_RETRIES, int)


class TestReactivationRetryEdgeCases(unittest.TestCase):
    """Edge case tests for ReactivationRetry."""

    def setUp(self):
        """Create fresh ReactivationRetry with mock step executor."""
        self.step_executor = MagicMock()
        self.retry = ReactivationRetry(self.step_executor)

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_no_parse_grace_fn_skips_verification(self, mock_sleep):
        """execute without parse_grace_fn should skip verification steps."""
        self.step_executor.execute.return_value = "inject_ok"

        result = self.retry.execute(reactivation_command="*123#")

        self.assertTrue(result.is_success)
        self.assertIsNone(result.initial_grace)
        self.assertIsNone(result.final_grace)

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_parse_grace_fn_returning_none_for_all(self, mock_sleep):
        """execute with parse_grace_fn returning None should treat as changed (best-effort)."""
        self.step_executor.execute.side_effect = [
            "initial_verify",
            "inject_ok",
            "final_verify",
        ]

        def parse_grace(response):
            return None

        result = self.retry.execute(
            reactivation_command="*123#",
            parse_grace_fn=parse_grace,
        )

        self.assertTrue(result.is_success)
        self.assertEqual(result.attempts, 1)

    @patch("worker.reactivation_retry.time.sleep", return_value=None)
    def test_sleep_calls_use_correct_delays(self, mock_sleep):
        """execute should sleep for VERIFICATION_DELAY_SECONDS after inject."""
        self.step_executor.execute.side_effect = [
            None,  # initial verify
            "ok",  # inject
            None,  # final verify
        ]

        def parse_grace(response):
            return "2025-01-01"

        self.retry.execute(
            reactivation_command="*123#",
            parse_grace_fn=parse_grace,
        )

        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        self.assertIn(VERIFICATION_DELAY_SECONDS, sleep_calls)


if __name__ == "__main__":
    unittest.main()
