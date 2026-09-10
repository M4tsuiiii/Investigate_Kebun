"""Rules — Single source of truth for auto-run gating.

DD-014: Global Auto Run Toggle — no per-port enable/disable.
DD-013: Single Hardware Restart — restart clears state, re-evaluates.
"""

import threading
from typing import Tuple

from app.domain.enums import CpinState
from app.domain.constants import CPIN_UNKNOWN_THRESHOLD


class AutoRunConfig:
    """Global auto-run configuration. Shared across all ports."""

    def __init__(self) -> None:
        self._auto_run_enabled: bool = False
        self._lock = threading.RLock()

    @property
    def auto_run_enabled(self) -> bool:
        with self._lock:
            return self._auto_run_enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._auto_run_enabled = enabled

    def toggle(self) -> bool:
        with self._lock:
            self._auto_run_enabled = not self._auto_run_enabled
            return self._auto_run_enabled


def should_block_auto_run(
    state_snapshot: dict,
    auto_run_config: AutoRunConfig,
    modem_online: bool = False,
) -> Tuple[bool, str]:
    """Determine if auto-run should be blocked for a port.

    Checks (in order):
    1. Global auto-run toggle (DD-014)
    2. Modem offline
    3. SIM not inserted
    4. SIM in PIN_REQUIRED state
    5. Awaiting card cycle (HR-004)
    6. CPIN unknown threshold reached (HR-019)

    Returns:
        (blocked, reason)
    """
    if not auto_run_config.auto_run_enabled:
        return True, "Auto-run disabled"

    if not modem_online:
        return True, "Modem offline"

    cpin = state_snapshot.get("cpin_state")
    if cpin == CpinState.NOT_INSERTED:
        return True, "SIM not inserted"

    if cpin == CpinState.PIN_REQUIRED:
        return True, "SIM requires PIN"

    if state_snapshot.get("awaiting_card_cycle", False):
        return True, "Awaiting card cycle"

    if state_snapshot.get("unknown_failure_count", 0) >= CPIN_UNKNOWN_THRESHOLD:
        return True, "CPIN unknown threshold reached"

    return False, ""
