"""Workflow Context — Shared memory during workflow execution.

One context per workflow run. Not shared between ports.
Destroyed after workflow completes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class WorkflowContext:
    """Shared memory for a single workflow execution.
    
    Rules:
    - All skills can read context
    - Skills can write to context
    - Context lives for the duration of the workflow
    - Context is destroyed after workflow completes
    - One context per workflow run (thread-safe)
    """
    
    port: str = ""
    
    # Card data
    nomor: str = ""
    nik: str = ""
    kk: str = ""
    
    # Status tracking
    status_awal: str = ""
    status_akhir: str = ""
    
    # Grace tracking
    grace_awal: str = ""
    grace_akhir: str = ""
    
    # Retry tracking (Sprint 8 ready)
    injection_attempt: int = 0
    
    # Step results: step_name -> SkillResult data
    step_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Lock for thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    
    def update(self, key: str, value: Any) -> None:
        """Thread-safe context update."""
        with self._lock:
            setattr(self, key, value)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Thread-safe context read."""
        with self._lock:
            return getattr(self, key, default)
    
    def store_step_result(self, step_name: str, data: Dict[str, Any]) -> None:
        """Store result from a skill execution."""
        with self._lock:
            self.step_results[step_name] = dict(data)
    
    def get_step_result(self, step_name: str) -> Optional[Dict[str, Any]]:
        """Get result from a previous step."""
        with self._lock:
            return self.step_results.get(step_name)
    
    def snapshot(self) -> Dict[str, Any]:
        """Return a snapshot of the context."""
        with self._lock:
            return {
                "port": self.port,
                "nomor": self.nomor,
                "nik": self.nik,
                "kk": self.kk,
                "status_awal": self.status_awal,
                "status_akhir": self.status_akhir,
                "grace_awal": self.grace_awal,
                "grace_akhir": self.grace_akhir,
                "injection_attempt": self.injection_attempt,
                "step_results": dict(self.step_results),
                "metadata": dict(self.metadata),
            }
    
    def clear(self) -> None:
        """Clear all context data."""
        with self._lock:
            self.port = ""
            self.nomor = ""
            self.nik = ""
            self.kk = ""
            self.status_awal = ""
            self.status_akhir = ""
            self.grace_awal = ""
            self.grace_akhir = ""
            self.injection_attempt = 0
            self.step_results.clear()
            self.metadata.clear()
