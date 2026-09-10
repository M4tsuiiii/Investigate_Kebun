"""Workflow Registry — Stores and retrieves workflow definitions."""

from __future__ import annotations

from typing import Dict, List, Optional

from workflow.definitions import WorkflowDefinition


class WorkflowRegistry:
    """Registry of all available workflow definitions.
    
    Pre-built workflows:
    - check_data: cek_nomor → cek_nik → cek_kk
    - reactivate_fast: inject_reaktivasi → verify_grace
    - reactivate_full: cek_nomor → cek_status → cek_nik → cek_kk → inject_reaktivasi → verify_grace
    - hardware_restart: restart_hardware
    - hardware_reset: reset_hardware
    """
    
    def __init__(self) -> None:
        self._workflows: Dict[str, WorkflowDefinition] = {}
        self._register_defaults()
    
    def _register_defaults(self) -> None:
        """Register pre-built workflows."""
        # Sprint 15S: Atomic workflows (one skill each)
        self.register(WorkflowDefinition(
            name="check_number",
            description="Check modem number (AT command)",
            steps=["cek_nomor"],
        ))
        self.register(WorkflowDefinition(
            name="check_status",
            description="Check SIM card status (AT+CPIN?)",
            steps=["cek_status"],
        ))
        self.register(WorkflowDefinition(
            name="check_nik",
            description="Check NIK via USSD",
            steps=["cek_nik"],
        ))
        self.register(WorkflowDefinition(
            name="check_kk",
            description="Check KK via USSD",
            steps=["cek_kk"],
        ))

        # Composite workflows
        self.register(WorkflowDefinition(
            name="check_data",
            description="Check modem data: number, NIK, KK",
            steps=["cek_nomor", "cek_nik", "cek_kk"],
        ))

        self.register(WorkflowDefinition(
            name="reactivate_fast",
            description="Fast reactivation: inject then verify",
            steps=["inject_reaktivasi", "verify_grace"],
        ))

        self.register(WorkflowDefinition(
            name="reactivate_full",
            description="Full reactivation flow with status checks",
            steps=["cek_nomor", "cek_status", "cek_nik", "cek_kk", "inject_reaktivasi", "verify_grace"],
        ))

        self.register(WorkflowDefinition(
            name="hardware_restart",
            description="Restart modem hardware",
            steps=["restart_hardware"],
        ))

        self.register(WorkflowDefinition(
            name="hardware_reset",
            description="Full hardware reset cycle",
            steps=["reset_hardware"],
        ))
    
    def register(self, workflow: WorkflowDefinition) -> None:
        """Register a workflow definition."""
        self._workflows[workflow.name] = workflow
    
    def get(self, name: str) -> Optional[WorkflowDefinition]:
        """Get a workflow by name."""
        return self._workflows.get(name)
    
    def list_workflows(self) -> List[str]:
        """List all registered workflow names."""
        return list(self._workflows.keys())
    
    def list_definitions(self) -> List[WorkflowDefinition]:
        """List all registered workflow definitions."""
        return list(self._workflows.values())
    
    def has(self, name: str) -> bool:
        """Check if a workflow is registered."""
        return name in self._workflows
    
    def remove(self, name: str) -> bool:
        """Remove a workflow. Returns True if removed."""
        return self._workflows.pop(name, None) is not None
