"""Automation Engine — Orchestrates workflow execution based on hardware events.

Connects: Hardware Event → Automation Engine → Workflow Engine → Skills

Sprint 8: Automation Engine only.
"""

from automation.engine import AutomationEngine
from automation.queue import WorkflowQueue, QueueItem
from automation.scheduler import AutomationScheduler
from automation.policy import AutomationPolicy
from automation.triggers import Trigger, TriggerEvent
from automation.state import AutomationState, AutomationStatus
from automation.result import AutomationResult
from automation.retry import ReactivateRetryPolicy

__all__ = [
    "AutomationEngine",
    "WorkflowQueue",
    "QueueItem",
    "AutomationScheduler",
    "AutomationPolicy",
    "Trigger",
    "TriggerEvent",
    "AutomationState",
    "AutomationStatus",
    "AutomationResult",
    "ReactivateRetryPolicy",
]
