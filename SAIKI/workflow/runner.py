"""Workflow Runner — Orchestrates skill execution with cleanup discipline.

Pipeline: load -> resolve -> execute -> update context -> cleanup -> cooldown -> next
Failure: STOP on first skill failure

Thread-safe: Each workflow run creates its own context.

Sprint 15J: [STEP TRACE], [WORKFLOW LIFECYCLE] instrumentation.
Sprint 15L: [DELIVERY TRACE], [SKILL AUDIT] instrumentation.
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Any, Callable, Dict, List, Optional

from workflow.context import WorkflowContext
from workflow.definitions import WorkflowDefinition
from workflow.result import WorkflowResult
from workflow.exceptions import SkillNotFoundError, WorkflowExecutionError
from worker.cleanup import CleanupManager

logger = logging.getLogger("saiki.workflow")


class WorkflowRunner:
    """Executes workflows by resolving and running skills in order.
    
    Responsibilities:
    - Load workflow definition
    - Resolve skill names to Skill instances
    - Execute each skill with port + context
    - Update context after each skill
    - Cleanup and cooldown between steps
    - Stop on first failure
    - Produce WorkflowResult
    
    Thread-safe: Each run creates its own WorkflowContext.
    """
    
    def __init__(
        self,
        skill_map: Dict[str, Any],
        cleanup_manager: Optional[CleanupManager] = None,
        cooldown_seconds: float = 4.0,
    ) -> None:
        """
        Args:
            skill_map: Dict mapping skill names to Skill instances or _SkillFactoryBase
            cleanup_manager: Optional cleanup manager for between-step cleanup
            cooldown_seconds: Cooldown between steps (default: DIAL_COOLDOWN_SECONDS)
        """
        self._skill_map: Dict[str, Any] = skill_map
        self._cleanup: Optional[CleanupManager] = cleanup_manager
        self._cooldown_seconds: float = cooldown_seconds
        self._lock: threading.Lock = threading.Lock()
        self._port_workers: Dict[str, Any] = {}  # Sprint 15S.2

    def set_port_workers(self, port_workers: Dict[str, Any]) -> None:
        """Set per-port worker registry for dependency resolution (Sprint 15S.2)."""
        self._port_workers = port_workers
    
    def run(
        self,
        workflow: WorkflowDefinition,
        port: str,
        context: Optional[WorkflowContext] = None,
        on_step_complete: Optional[Callable[[str, Any, WorkflowContext], None]] = None,
        trigger_id: int = 0,
    ) -> WorkflowResult:
        """Execute a workflow.

        Args:
            workflow: Workflow definition to execute
            port: Port ID to execute on
            context: Optional existing context (creates new if None)
            on_step_complete: Optional callback after each step (step_name, skill_result, context)
            trigger_id: Unique trigger ID for trace logging (Sprint 15J)

        Returns:
            WorkflowResult with success/failure and all step details
        """
        # Create context if not provided
        if context is None:
            context = WorkflowContext(port=port)
        else:
            context.update("port", port)

        result = WorkflowResult(
            workflow_name=workflow.name,
            started_at=time.time(),
            context=context,
        )

        total_steps = len(workflow.steps)
        lifecycle_events = ["START"]

        logger.info("[WORKFLOW LIFECYCLE] trigger_id=%d WORKFLOW=%s STEPS=%d START", trigger_id, workflow.name, total_steps)
        logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s port=%s stage=WORKFLOW_START steps=%d", trigger_id, workflow.name, port, total_steps)

        try:
            for step_idx, step_name in enumerate(workflow.steps, 1):
                # 1. Resolve skill (Sprint 15S.2: factory or instance)
                logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s step=%d/%d port=%s stage=SKILL_LOOKUP skill=%s",
                            trigger_id, workflow.name, step_idx, total_steps, port, step_name)
                skill_entry = self._skill_map.get(step_name)
                if skill_entry is None:
                    err_msg = f"Skill not found: {step_name}"
                    lifecycle_events.append(f"STEP_{step_idx}_MISSING")
                    logger.info("[SKILL AUDIT] WORKFLOW=%s STEP=%s SKILL=%s FOUND=NO", workflow.name, step_name, step_name)
                    logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s step=%d/%d port=%s stage=SKILL_MISSING skill=%s",
                                trigger_id, workflow.name, step_idx, total_steps, port, step_name)
                    logger.info("[STEP TRACE] trigger_id=%d WORKFLOW=%s STEP=%d/%d ACTION=start SKIPPED reason=skill_not_found",
                                trigger_id, workflow.name, step_idx, total_steps)
                    logger.info("[WORKFLOW LIFECYCLE] trigger_id=%d WORKFLOW=%s %s END=FAILED reason=%s",
                                trigger_id, workflow.name, " ".join(lifecycle_events), err_msg)
                    raise SkillNotFoundError(step_name)

                # Sprint 15S.2: Resolve factory with per-port dependency resolver
                from worker.skills.dependency_resolver import SkillDependencyResolver
                resolver = SkillDependencyResolver.__new__(SkillDependencyResolver)
                resolver._port = port
                resolver._worker_manager = None
                resolver._worker = self._port_workers.get(port)
                skill = skill_entry.resolve(resolver) if hasattr(skill_entry, 'resolve') else skill_entry

                logger.info("[SKILL AUDIT] WORKFLOW=%s STEP=%s SKILL=%s FOUND=YES", workflow.name, step_name, step_name)

                # 2. Execute skill
                logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s step=%d/%d port=%s stage=SKILL_EXECUTE skill=%s",
                            trigger_id, workflow.name, step_idx, total_steps, port, step_name)
                logger.info("[STEP TRACE] trigger_id=%d WORKFLOW=%s STEP=%d/%d ACTION=start SKILL=%s",
                            trigger_id, workflow.name, step_idx, total_steps, step_name)
                try:
                    skill_result = skill.execute(port=port, skill_resolver=resolver, command_id=trigger_id)
                except Exception as e:
                    skill_result = type('SkillResult', (), {
                        'success': False,
                        'error': str(e),
                        'data': {},
                        'skill_name': step_name,
                        'port': port,
                    })()

                # 3. Update result tracking
                result.steps_executed.append(step_name)

                # 4. Store in context
                context.store_step_result(step_name, skill_result.data)

                # 5. Check success
                if not skill_result.success:
                    result.steps_failed.append(step_name)
                    result.errors.append(f"{step_name}: {skill_result.error}")
                    result.success = False
                    result.finished_at = time.time()
                    lifecycle_events.append(f"STEP_{step_idx}_FAILED")
                    logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s step=%d/%d port=%s stage=STEP_FAILED skill=%s error=%s",
                                trigger_id, workflow.name, step_idx, total_steps, port, step_name, skill_result.error)
                    logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s port=%s stage=WORKFLOW_END result=FAILED reason=%s",
                                trigger_id, workflow.name, port, skill_result.error)
                    logger.info("[STEP TRACE] trigger_id=%d WORKFLOW=%s STEP=%d/%d RESULT=failed SKILL=%s ERROR=%s",
                                trigger_id, workflow.name, step_idx, total_steps, step_name, skill_result.error)
                    logger.info("[WORKFLOW LIFECYCLE] trigger_id=%d WORKFLOW=%s %s END=FAILED",
                                trigger_id, workflow.name, " ".join(lifecycle_events))
                    return result

                # 6. Step succeeded
                lifecycle_events.append(f"STEP_{step_idx}_OK")
                logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s step=%d/%d port=%s stage=STEP_COMPLETE skill=%s",
                            trigger_id, workflow.name, step_idx, total_steps, port, step_name)
                logger.info("[STEP TRACE] trigger_id=%d WORKFLOW=%s STEP=%d/%d RESULT=success SKILL=%s",
                            trigger_id, workflow.name, step_idx, total_steps, step_name)

                # 7. Callback
                if on_step_complete:
                    try:
                        on_step_complete(step_name, skill_result, context)
                    except Exception:
                        pass

                # 8. Cleanup between steps (not after last step)
                if step_name != workflow.steps[-1]:
                    self._cleanup_between_steps()

            # All steps succeeded
            result.success = True
            result.finished_at = time.time()
            logger.info("[DELIVERY TRACE] trigger_id=%d workflow=%s port=%s stage=WORKFLOW_END result=SUCCESS",
                        trigger_id, workflow.name, port)
            logger.info("[WORKFLOW LIFECYCLE] trigger_id=%d WORKFLOW=%s %s END=SUCCESS",
                        trigger_id, workflow.name, " ".join(lifecycle_events))
            return result

        except SkillNotFoundError:
            raise
        except Exception as e:
            result.errors.append(f"Unexpected error: {e}")
            result.success = False
            result.finished_at = time.time()
            lifecycle_events.append("ERROR")
            logger.info("[WORKFLOW LIFECYCLE] trigger_id=%d WORKFLOW=%s %s END=FAILED reason=%s",
                        trigger_id, workflow.name, " ".join(lifecycle_events), e)
            return result
    
    def run_by_name(
        self,
        workflow_name: str,
        port: str,
        registry: Any,
        context: Optional[WorkflowContext] = None,
        on_step_complete: Optional[Callable[[str, Any, WorkflowContext], None]] = None,
        trigger_id: int = 0,
    ) -> WorkflowResult:
        """Run a workflow by name from a registry.

        Args:
            workflow_name: Name of workflow to run
            port: Port ID
            registry: WorkflowRegistry to look up workflow
            context: Optional existing context
            on_step_complete: Optional callback
            trigger_id: Unique trigger ID for trace logging (Sprint 15J)

        Returns:
            WorkflowResult
        """
        workflow = registry.get(workflow_name)
        if workflow is None:
            from workflow.exceptions import WorkflowError
            raise WorkflowError(f"Workflow not found: {workflow_name!r}")

        return self.run(workflow, port, context, on_step_complete, trigger_id=trigger_id)
    
    def _cleanup_between_steps(self) -> None:
        """Execute cleanup and cooldown between steps."""
        if self._cleanup:
            self._cleanup.close_session()
            time.sleep(0.5)  # Grace read wait
            self._cleanup.clear_buffer()
            self._cleanup.cooldown(self._cooldown_seconds)
        else:
            time.sleep(self._cooldown_seconds)
    
    @property
    def skill_names(self) -> List[str]:
        """List available skill names."""
        return list(self._skill_map.keys())
