"""Triggers — Hardware and workflow events that drive automation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Trigger(str, Enum):
    """Types of triggers that can drive automation."""
    MODEM_ONLINE = "MODEM_ONLINE"
    MODEM_OFFLINE = "MODEM_OFFLINE"
    SIM_INSERTED = "SIM_INSERTED"
    SIM_REMOVED = "SIM_REMOVED"
    CPIN_READY = "CPIN_READY"
    CPIN_REQUIRED = "CPIN_REQUIRED"
    WORKFLOW_SUCCESS = "WORKFLOW_SUCCESS"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    USER_MASS_REACTIVATION = "USER_MASS_REACTIVATION"
    USER_MASS_CHECK_NUMBER = "USER_MASS_CHECK_NUMBER"


@dataclass(frozen=True)
class TriggerEvent:
    """A trigger event with context."""
    trigger: Trigger
    port: str
    detail: str = ""

    def __repr__(self) -> str:
        return f"TriggerEvent({self.trigger.value}, port={self.port!r})"
