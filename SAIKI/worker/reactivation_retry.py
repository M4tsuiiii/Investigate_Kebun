"""ReactivationRetry — Inject-verify-retry flow with single-retry limit.

Requirement 3: Verification flow:
1. Inject
2. Verify grace date
3. If changed -> SUCCESS
4. If unchanged -> retry injection 1x
5. Verify again
6. If still unchanged -> FAILED
Never retry more than once.
"""

import time
from typing import Optional, Callable

from app.domain.enums import BusinessOutcome
from app.domain.constants import VERIFICATION_DELAY_SECONDS, DIAL_COOLDOWN_SECONDS


class ReactivationResult:
    """Result of a reactivation attempt."""

    def __init__(
        self,
        outcome: BusinessOutcome,
        attempts: int,
        initial_grace: Optional[str] = None,
        final_grace: Optional[str] = None,
        message: str = "",
    ) -> None:
        self.outcome: BusinessOutcome = outcome
        self.attempts: int = attempts
        self.initial_grace: Optional[str] = initial_grace
        self.final_grace: Optional[str] = final_grace
        self.message: str = message

    @property
    def is_success(self) -> bool:
        """Check if reactivation was successful."""
        return self.outcome == BusinessOutcome.SUKSES

    def __repr__(self) -> str:
        return (
            f"ReactivationResult(outcome={self.outcome.value}, "
            f"attempts={self.attempts}, message={self.message!r})"
        )


class ReactivationRetry:
    """Handles inject-verify-retry flow with single-retry limit.

    Flow:
    1. Inject reactivation command
    2. Wait VERIFICATION_DELAY_SECONDS (15s)
    3. Verify grace date via USSD
    4. Compare initial vs final grace date
    5. If changed -> SUCCESS
    6. If unchanged -> retry 1x (inject again)
    7. Wait + verify again
    8. If still unchanged -> FAILED

    Never retry more than once.
    """

    MAX_RETRIES: int = 1

    def __init__(self, step_executor: object) -> None:
        self._step_executor: object = step_executor

    def execute(
        self,
        reactivation_command: str,
        verify_command: str = "*185#",
        parse_grace_fn: Optional[Callable[[str], Optional[str]]] = None,
    ) -> ReactivationResult:
        """Execute full reactivation flow with retry.

        Args:
            reactivation_command: USSD command to inject reactivation.
            verify_command: USSD command to verify (default *185#).
            parse_grace_fn: Optional callable(response) -> grace_date string.

        Returns:
            ReactivationResult with outcome and details.
        """
        initial_grace: Optional[str] = None
        if parse_grace_fn is not None and self._step_executor is not None:
            verify_response = self._step_executor.execute(verify_command)
            if verify_response is not None:
                initial_grace = parse_grace_fn(verify_response)

        inject_response = self._step_executor.execute(reactivation_command)

        if inject_response is None:
            return ReactivationResult(
                outcome=BusinessOutcome.FAILED,
                attempts=1,
                initial_grace=initial_grace,
                message="Injection failed — no response",
            )

        time.sleep(VERIFICATION_DELAY_SECONDS)

        final_grace: Optional[str] = None
        if parse_grace_fn is not None and self._step_executor is not None:
            verify_response = self._step_executor.execute(verify_command)
            if verify_response is not None:
                final_grace = parse_grace_fn(verify_response)

        if self._grace_date_changed(initial_grace, final_grace):
            return ReactivationResult(
                outcome=BusinessOutcome.SUKSES,
                attempts=1,
                initial_grace=initial_grace,
                final_grace=final_grace,
                message="Grace date changed — reactivation successful",
            )

        time.sleep(DIAL_COOLDOWN_SECONDS)

        inject_response = self._step_executor.execute(reactivation_command)

        if inject_response is None:
            return ReactivationResult(
                outcome=BusinessOutcome.FAILED,
                attempts=2,
                initial_grace=initial_grace,
                final_grace=final_grace,
                message="Retry injection failed — no response",
            )

        time.sleep(VERIFICATION_DELAY_SECONDS)

        final_grace_2: Optional[str] = None
        if parse_grace_fn is not None and self._step_executor is not None:
            verify_response = self._step_executor.execute(verify_command)
            if verify_response is not None:
                final_grace_2 = parse_grace_fn(verify_response)

        if self._grace_date_changed(initial_grace, final_grace_2):
            return ReactivationResult(
                outcome=BusinessOutcome.SUKSES,
                attempts=2,
                initial_grace=initial_grace,
                final_grace=final_grace_2,
                message="Grace date changed on retry — reactivation successful",
            )

        return ReactivationResult(
            outcome=BusinessOutcome.FAILED,
            attempts=2,
            initial_grace=initial_grace,
            final_grace=final_grace_2,
            message="Grace date unchanged after retry — reactivation failed",
        )

    def _grace_date_changed(
        self,
        initial: Optional[str],
        final: Optional[str],
    ) -> bool:
        """Check if grace date changed between initial and final.

        Returns True if:
        - Both are None (unknown -> assume changed, best-effort)
        - initial is None and final is not
        - initial is not None and final is None
        - Both are not None and they differ
        """
        if initial is None and final is None:
            return True
        if initial is None or final is None:
            return True
        return initial.strip() != final.strip()
