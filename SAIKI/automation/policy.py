"""Automation Policy — Workflow selection based on mode and state."""

from __future__ import annotations

from enum import Enum
from typing import Optional


class AutomationMode(str, Enum):
    """Automation modes for workflow selection."""
    CHECK_DATA = "CHECK_DATA"
    REACTIVATE_FAST = "REACTIVATE_FAST"
    REACTIVATE_FULL = "REACTIVATE_FULL"


class AutomationPolicy:
    """Selects workflow based on automation mode.

    Mode → Workflow mapping:
    - CHECK_DATA → check_data
    - REACTIVATE_FAST → reactivate_fast
    - REACTIVATE_FULL → reactivate_full
    """

    MODE_TO_WORKFLOW = {
        AutomationMode.CHECK_DATA: "check_data",
        AutomationMode.REACTIVATE_FAST: "reactivate_fast",
        AutomationMode.REACTIVATE_FULL: "reactivate_full",
    }

    def __init__(self, default_mode: AutomationMode = AutomationMode.REACTIVATE_FULL) -> None:
        self._mode: AutomationMode = default_mode

    @property
    def mode(self) -> AutomationMode:
        return self._mode

    @property
    def workflow_name(self) -> str:
        """Get workflow name for current mode."""
        return self.MODE_TO_WORKFLOW[self._mode]

    def set_mode(self, mode: AutomationMode) -> None:
        self._mode = mode

    def select_workflow(self, trigger: str = "", cpin_state: str = "") -> Optional[str]:
        """Select workflow based on trigger and state.

        Returns workflow name or None if no workflow should run.
        """
        # User-triggered overrides
        if trigger == "USER_MASS_CHECK_NUMBER":
            return "check_data"
        if trigger == "USER_MASS_REACTIVATION":
            return self.MODE_TO_WORKFLOW[self._mode]

        # Hardware triggers — use current mode
        if trigger in ("MODEM_ONLINE", "SIM_INSERTED", "CPIN_READY"):
            return self.MODE_TO_WORKFLOW[self._mode]

        # No trigger — use current mode
        return self.MODE_TO_WORKFLOW[self._mode]
