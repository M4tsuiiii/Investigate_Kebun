"""Workflow Exceptions — Error types for workflow engine."""


class WorkflowError(Exception):
    """Base exception for workflow errors."""
    pass


class SkillNotFoundError(WorkflowError):
    """Raised when a skill is not found in the registry."""

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"Skill not found: {skill_name!r}")


class WorkflowExecutionError(WorkflowError):
    """Raised when a workflow step fails."""

    def __init__(self, workflow_name: str, step: str, error: str) -> None:
        self.workflow_name = workflow_name
        self.step = step
        self.error = error
        super().__init__(f"Workflow {workflow_name!r} failed at step {step!r}: {error}")
