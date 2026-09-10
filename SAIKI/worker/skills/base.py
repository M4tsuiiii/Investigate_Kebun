"""Base Skill — ABC and SkillResult for all skills.

Every skill must:
- Have execute() method
- Accept typed InputSchema
- Return SkillResult with success/failure
- Be independent (no skill-to-skill calls)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SkillResult:
    """Unified result from any skill execution.
    
    Attributes:
        success: Whether the skill completed successfully
        data: Result payload (skill-specific)
        error: Error message if failed
        skill_name: Name of the skill that produced this result
        port: Port ID this result is for
    """
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    skill_name: str = ""
    port: str = ""

    def __repr__(self) -> str:
        return (
            f"SkillResult(success={self.success}, skill={self.skill_name!r}, "
            f"port={self.port!r}, error={self.error!r})"
        )


class Skill(ABC):
    """Base class for all skills.
    
    A skill is an atomic, reusable business operation.
    
    Constraints:
    - Each skill is independent
    - No skill may call another skill
    - Skills receive dependencies via __init__ (ATClient, USSDRuntime, etc.)
    - Skills produce SkillResult with clear success/failure
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill name (e.g., 'cek_nomor')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the skill does."""
        ...

    @abstractmethod
    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        """Execute the skill.
        
        Args:
            port: Port ID to execute on
            **kwargs: Skill-specific input parameters
            
        Returns:
            SkillResult with success/failure and data
        """
        ...

    def _success(self, port: str, data: Optional[Dict[str, Any]] = None) -> SkillResult:
        """Helper to create a success result."""
        return SkillResult(
            success=True,
            data=data or {},
            skill_name=self.name,
            port=port,
        )

    def _failure(self, port: str, error: str) -> SkillResult:
        """Helper to create a failure result."""
        return SkillResult(
            success=False,
            error=error,
            skill_name=self.name,
            port=port,
        )
