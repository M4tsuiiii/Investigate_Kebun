"""Retry Policy — Handles reactivation retry logic.

Rule:
- inject → verify grace
- If grace changed → SUCCESS
- If grace unchanged → retry inject 1x
- verify again
- If still unchanged → FAILED

MAX_REACTIVATION_RETRY = 1
"""

from __future__ import annotations

from typing import Optional, Tuple

MAX_REACTIVATION_RETRY: int = 1


class ReactivateRetryPolicy:
    """Handles reactivation retry logic.

    Retry flow:
    1. Initial injection
    2. Verify grace
    3. If grace unchanged → retry (max 1x)
    4. Verify again
    5. If still unchanged → FAILED
    """

    def __init__(self, max_retries: int = MAX_REACTIVATION_RETRY) -> None:
        self._max_retries: int = max_retries

    def should_retry(
        self,
        grace_before: str,
        grace_after: str,
        attempt: int,
    ) -> bool:
        """Determine if a retry is needed.

        Returns True if:
        - grace unchanged (grace_before == grace_after)
        - attempt < max_retries
        """
        if grace_before == grace_after and attempt < self._max_retries:
            return True
        return False

    def evaluate_result(
        self,
        grace_before: str,
        grace_after: str,
        attempt: int,
    ) -> Tuple[bool, str]:
        """Evaluate reactivation result.

        Returns:
            (success, reason)
        """
        if grace_before != grace_after:
            return True, "Grace date changed — reactivation successful"

        if attempt < self._max_retries:
            return False, f"Grace unchanged, retry {attempt + 1}/{self._max_retries}"

        return False, f"Grace unchanged after {self._max_retries} retries — FAILED"

    @property
    def max_retries(self) -> int:
        return self._max_retries
