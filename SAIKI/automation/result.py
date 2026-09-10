"""Automation Result — Outcome of an automation cycle."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AutomationResult:
    """Result of an automation cycle for a single port."""

    port: str = ""
    workflow_name: str = ""
    success: bool = False

    started_at: float = 0.0
    finished_at: float = 0.0

    trigger: str = ""
    workflow_result: Any = None  # WorkflowResult

    error: str = ""
    retried: bool = False

    def __repr__(self) -> str:
        return (
            f"AutomationResult(port={self.port!r}, workflow={self.workflow_name!r}, "
            f"success={self.success})"
        )

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "port": self.port,
            "workflow_name": self.workflow_name,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "trigger": self.trigger,
            "error": self.error,
            "retried": self.retried,
        }
