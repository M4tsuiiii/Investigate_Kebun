"""Skills — Atomic, reusable business operations.

Each skill is independent, has clear input/output schemas,
and produces success/failure results.

Skills are designed for reuse by a future Workflow Engine.
"""

from worker.skills.base import Skill, SkillResult

__all__ = ["Skill", "SkillResult"]
