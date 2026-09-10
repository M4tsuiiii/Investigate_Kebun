"""Workflow Result — Outcome of a workflow execution."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflow.context import WorkflowContext


@dataclass
class WorkflowResult:
    """Result of a workflow execution.
    
    Tracks:
    - Which workflow ran
    - Success/failure
    - Timing
    - Step execution details
    - Final context
    - Error list
    """
    
    workflow_name: str = ""
    success: bool = False
    
    started_at: float = 0.0
    finished_at: float = 0.0
    
    steps_executed: List[str] = field(default_factory=list)
    steps_failed: List[str] = field(default_factory=list)
    
    context: Optional[WorkflowContext] = None
    errors: List[str] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return (
            f"WorkflowResult(workflow={self.workflow_name!r}, "
            f"success={self.success}, steps={len(self.steps_executed)})"
        )
    
    @property
    def duration_seconds(self) -> float:
        """Total execution time in seconds."""
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return 0.0
    
    @property
    def last_step(self) -> Optional[str]:
        """Name of the last executed step."""
        if self.steps_executed:
            return self.steps_executed[-1]
        return None
    
    @property
    def failed_step(self) -> Optional[str]:
        """Name of the step that caused failure."""
        if self.steps_failed:
            return self.steps_failed[-1]
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize result to dict."""
        return {
            "workflow_name": self.workflow_name,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "steps_executed": list(self.steps_executed),
            "steps_failed": list(self.steps_failed),
            "errors": list(self.errors),
            "context": self.context.snapshot() if self.context else None,
        }
