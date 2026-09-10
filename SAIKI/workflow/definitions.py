"""Workflow Definitions — Declarative workflow structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class WorkflowDefinition:
    """Declarative definition of a workflow.
    
    A workflow is an ordered list of skill names to execute.
    
    Rules:
    - Steps are executed in order
    - First failure stops the workflow
    - Each step maps to exactly one skill
    """
    
    name: str
    description: str = ""
    steps: List[str] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return f"WorkflowDefinition(name={self.name!r}, steps={self.steps})"
    
    def step_count(self) -> int:
        """Number of steps in this workflow."""
        return len(self.steps)
    
    def has_step(self, step_name: str) -> bool:
        """Check if a step exists in this workflow."""
        return step_name in self.steps
