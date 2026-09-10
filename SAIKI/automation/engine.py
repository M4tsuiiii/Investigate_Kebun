"""Automation Engine — Orchestrates workflow execution (Sprint 15F: lifecycle audit).

Pipeline: trigger -> evaluate -> select workflow -> enqueue -> execute -> publish
Lifecycle logs: [ENGINE], [AUTORUN], [WORKFLOW]
Sprint 15I: trigger_id tracking, duplicate detection, source ownership.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from automation.triggers import Trigger, TriggerEvent
from automation.state import AutomationState, AutomationStatus
from automation.queue import WorkflowQueue, QueueItem
from automation.policy import AutomationPolicy, AutomationMode
from automation.retry import ReactivateRetryPolicy
from automation.result import AutomationResult
from automation.scheduler import AutomationScheduler
from workflow.runner import WorkflowRunner
from workflow.registry import WorkflowRegistry

logger = logging.getLogger("saiki.automation")


class AutomationEngine:
    """Orchestrates workflow execution based on hardware triggers.

    Responsibilities:
    - Receive trigger events
    - Evaluate policy (should we run?)
    - Select workflow (which one?)
    - Enqueue workflow
    - Execute workflow via WorkflowRunner
    - Handle retry logic
    - Publish progress events

    Does NOT:
    - Call skills directly
    - Contain business logic
    - Manage UI
    """

    def __init__(
        self,
        workflow_runner: WorkflowRunner,
        workflow_registry: WorkflowRegistry,
        auto_run_config: Any,
        event_bus: Any = None,
        max_concurrent: int = 2,
        port_state_provider: Any = None,
    ) -> None:
        self._runner: WorkflowRunner = workflow_runner
        self._registry: WorkflowRegistry = workflow_registry
        self._auto_run_config: Any = auto_run_config
        self._event_bus: Any = event_bus
        self._port_state_provider: Any = port_state_provider
        self._queue: WorkflowQueue = WorkflowQueue(max_concurrent=max_concurrent)
        self._scheduler: AutomationScheduler = AutomationScheduler()
        self._policy: AutomationPolicy = AutomationPolicy()
        self._retry_policy: ReactivateRetryPolicy = ReactivateRetryPolicy()

        self._lock: threading.RLock = threading.RLock()
        self._running: threading.Event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._results: List[AutomationResult] = []

        # Sprint 15I: trigger ownership tracking
        self._recent_triggers: Dict[Tuple[str, str], List[Tuple[float, int, str]]] = {}
        self._trigger_source_counts: Dict[Tuple[str, str], int] = {}
        self._workflow_exec_count: int = 0
        self._duplicate_detected: bool = False
        self._duplicate_events: List[Dict[str, str]] = []

        # Sprint 15J: workflow runtime tracking
        self._workflow_started: int = 0
        self._workflow_completed: int = 0
        self._workflow_failed: int = 0
        self._workflow_cancelled: int = 0
        self._failure_reasons: Dict[str, int] = {}

        # Sprint 15L: delivery tracking
        self._triggers_received: int = 0
        self._skills_found: int = 0
        self._skills_missing: int = 0
        self._commands_built: int = 0
        self._commands_sent: int = 0
        self._responses_received: int = 0
        self._responses_timeout: int = 0
        self._last_breakpoint: str = "none"

        # Sprint 15T: execution audit
        self._dispatched: int = 0

    def log_execution_audit(self) -> None:
        """Sprint 15T: Log WORKFLOW EXECUTION AUDIT."""
        logger.info(
            "[WORKFLOW EXECUTION AUDIT] DISPATCHED=%d STARTED=%d COMPLETED=%d FAILED=%d CANCELLED=%d",
            self._dispatched, self._workflow_started, self._workflow_completed,
            self._workflow_failed, self._workflow_cancelled,
        )
        if self._failure_reasons:
            for reason, count in self._failure_reasons.items():
                logger.info("[WORKFLOW EXECUTION AUDIT] FAILURE_REASON=%s COUNT=%d", reason, count)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the automation engine worker thread."""
        self._running.set()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="AutomationEngine",
            daemon=True,
        )
        self._worker_thread.start()
        # Listen for port.excluded to cancel queued workflows (Sprint 11A)
        if self._event_bus:
            self._event_bus.subscribe("port.excluded", self._on_port_excluded)

    def stop(self) -> None:
        """Stop the automation engine."""
        # Log all queued items as cancelled
        snapshot = self._queue.snapshot()
        for item in snapshot:
            with self._lock:
                self._workflow_cancelled += 1
            logger.info("[WORKFLOW CANCELLED] PORT=%s REASON=engine_stop removed_from_queue=1", item["port"])
        self._running.clear()
        self._queue.clear()

    def handle_trigger(self, trigger: Trigger, port: str, detail: str = "", trigger_id: int = 0, source: str = "UNKNOWN") -> None:
        """Handle a trigger event.

        This is the main entry point for hardware events.
        Skips EXCLUDED ports (Sprint 11A).
        Lifecycle log: [ENGINE], [AUTORUN GATE], [WORKFLOW SELECT], [QUEUE AUDIT]
        Sprint 15I: trigger_id propagated, duplicate detection, source ownership.
        Sprint 15P: boundary traces with timestamps and thread names.
        """
        import threading as _threading
        _tname = _threading.current_thread().name
        logger.info("[ENGINE ENTER] port=%s trigger=%s trigger_id=%d source=%s thread=%s",
                    port, trigger.value, trigger_id, source, _tname)
        with self._lock:
            self._triggers_received += 1
        event = TriggerEvent(trigger=trigger, port=port, detail=detail)

        # Sprint 15I: track source ownership
        source_key = (trigger.value, source)
        with self._lock:
            self._trigger_source_counts[source_key] = self._trigger_source_counts.get(source_key, 0) + 1

        # Sprint 15I: duplicate detection (same port + trigger within 5s)
        dedup_key = (port, trigger.value)
        now = time.time()
        with self._lock:
            if dedup_key not in self._recent_triggers:
                self._recent_triggers[dedup_key] = []
            recent = self._recent_triggers[dedup_key]
            # Purge entries older than 5s
            recent = [(t, tid, src) for t, tid, src in recent if now - t < 5.0]
            if recent:
                prev_time, prev_id, prev_source = recent[-1]
                self._duplicate_detected = True
                dup_info = {
                    "port": port,
                    "trigger": trigger.value,
                    "source_1": prev_source,
                    "source_2": source,
                    "id_1": prev_id,
                    "id_2": trigger_id,
                    "delta_ms": int((now - prev_time) * 1000),
                }
                self._duplicate_events.append(dup_info)
                logger.info("[DUPLICATE TRIGGER] PORT=%s TRIGGER=%s SOURCE_1=%s(id=%d) SOURCE_2=%s(id=%d) delta_ms=%d",
                            port, trigger.value, prev_source, prev_id, source, trigger_id, dup_info["delta_ms"])
            recent.append((now, trigger_id, source))
            self._recent_triggers[dedup_key] = recent

        # 0. Check port participation (Sprint 11A)
        logger.info("[ENGINE LOCK WAIT] port=%s trigger=%s reason=port_exclusion_check", port, trigger.value)
        if self._port_state_provider is not None:
            logger.info("[ENGINE LOCK ACQUIRED] port=%s trigger=%s", port, trigger.value)
            port_state = self._port_state_provider.get_port_state(port)
            if port_state is not None and port_state.value == "EXCLUDED":
                logger.info("[AUTORUN GATE] trigger_id=%d PORT=%s AUTO_RUN=%s BLOCKED reason=port_excluded", trigger_id, port, self._auto_run_config.auto_run_enabled)
                logger.info("[ENGINE EXIT] port=%s trigger=%s trigger_id=%d reason=port_excluded", port, trigger.value, trigger_id)
                self._publish("automation.skipped", {
                    "port": port,
                    "reason": "Port excluded from automation",
                    "trigger": trigger.value,
                })
                return

        # 1. Check global auto-run
        logger.info("[ENGINE AUTORUN GATE BEGIN] trigger_id=%d port=%s", trigger_id, port)
        if not self._auto_run_config.auto_run_enabled:
            logger.info("[AUTORUN GATE] trigger_id=%d PORT=%s AUTO_RUN=%s BLOCKED reason=auto_run_disabled", trigger_id, port, self._auto_run_config.auto_run_enabled)
            logger.info("[ENGINE AUTORUN GATE END] trigger_id=%d port=%s result=BLOCKED reason=auto_run_disabled", trigger_id, port)
            logger.info("[ENGINE EXIT] port=%s trigger=%s trigger_id=%d reason=auto_run_disabled", port, trigger.value, trigger_id)
            self._publish("automation.skipped", {
                "port": port,
                "reason": "Auto-run disabled",
                "trigger": trigger.value,
            })
            return

        logger.info("[AUTORUN GATE] trigger_id=%d PORT=%s AUTO_RUN=%s PASSED", trigger_id, port, self._auto_run_config.auto_run_enabled)
        logger.info("[ENGINE AUTORUN GATE END] trigger_id=%d port=%s result=PASSED", trigger_id, port)

        # 2. Evaluate scheduler
        logger.info("[ENGINE WORKFLOW SELECT BEGIN] trigger_id=%d port=%s trigger=%s", trigger_id, port, trigger.value)
        action = self._scheduler.evaluate_trigger(event)
        logger.info("[ENGINE] SCHEDULER trigger_id=%d port=%s trigger=%s action=%s", trigger_id, port, trigger.value, action)
        logger.info("[ENGINE WORKFLOW SELECT END] trigger_id=%d port=%s action=%s", trigger_id, port, action)

        if action == "cancel":
            removed = self._queue.remove_by_port(port)
            if removed > 0:
                with self._lock:
                    self._workflow_cancelled += 1
                logger.info("[WORKFLOW CANCELLED] trigger_id=%d PORT=%s REASON=%s removed_from_queue=%d",
                            trigger_id, port, trigger.value, removed)
            state = self._scheduler.get_state(port)
            state.set_idle()
            logger.info("[QUEUE AUDIT] trigger_id=%d PORT=%s SKIPPED reason=cancel", trigger_id, port)
            logger.info("[ENGINE EXIT] port=%s trigger=%s trigger_id=%d reason=cancel", port, trigger.value, trigger_id)
            self._publish("automation.skipped", {
                "port": port,
                "reason": f"Cancelled by {trigger.value}",
            })
            return

        if action == "standby":
            state = self._scheduler.get_state(port)
            state.set_standby()
            logger.info("[QUEUE AUDIT] trigger_id=%d PORT=%s SKIPPED reason=standby", trigger_id, port)
            logger.info("[ENGINE EXIT] port=%s trigger=%s trigger_id=%d reason=standby", port, trigger.value, trigger_id)
            self._publish("automation.skipped", {
                "port": port,
                "reason": "Standby",
                "trigger": trigger.value,
            })
            return

        if action == "enqueue":
            logger.info("[WORKFLOW SELECT] trigger_id=%d trigger=%s port=%s", trigger_id, trigger.value, port)
            workflow_name = self._policy.select_workflow(trigger=trigger.value)
            if workflow_name:
                logger.info("[WORKFLOW SELECT] trigger_id=%d workflow=%s", trigger_id, workflow_name)
                logger.info("[ENGINE ENQUEUE BEGIN] trigger_id=%d port=%s workflow=%s", trigger_id, port, workflow_name)
                logger.info("[QUEUE AUDIT] trigger_id=%d ENQUEUE PORT=%s WORKFLOW=%s", trigger_id, port, workflow_name)
                self._enqueue(port, workflow_name, trigger.value, trigger_id=trigger_id)
                logger.info("[ENGINE ENQUEUED] trigger_id=%d port=%s workflow=%s", trigger_id, port, workflow_name)
            else:
                logger.info("[WORKFLOW SELECT] trigger_id=%d workflow=None", trigger_id)
                logger.info("[QUEUE AUDIT] trigger_id=%d PORT=%s SKIPPED reason=no_workflow", trigger_id, port)

        logger.info("[ENGINE EXIT] port=%s trigger=%s trigger_id=%d action=%s", port, trigger.value, trigger_id, action)

    def enqueue_workflow(self, port: str, workflow_name: str, priority: int = 10, trigger_id: int = 0) -> None:
        """Manually enqueue a workflow (for user-triggered actions).
        
        Sprint 15S.2: trigger_id parameter for command_id propagation.
        Skips EXCLUDED ports (Sprint 11A).
        """
        if self._port_state_provider is not None:
            port_state = self._port_state_provider.get_port_state(port)
            if port_state is not None and port_state.value == "EXCLUDED":
                return
        self._enqueue(port, workflow_name, "manual", priority, trigger_id=trigger_id)

    def get_queue_size(self) -> int:
        return self._queue.size

    def get_running_count(self) -> int:
        return self._queue.running_count

    def get_results(self) -> List[AutomationResult]:
        """Get recent automation results."""
        with self._lock:
            return list(self._results[-50:])

    def get_state(self, port: str) -> AutomationState:
        return self._scheduler.get_state(port)

    @property
    def mode(self) -> AutomationMode:
        return self._policy.mode

    def set_mode(self, mode: AutomationMode) -> None:
        self._policy.set_mode(mode)

    def set_mode_from_name(self, mode_name: str) -> None:
        """Set automation mode by name string."""
        from automation.policy import AutomationMode
        try:
            mode = AutomationMode(mode_name)
            self._policy.set_mode(mode)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _enqueue(self, port: str, workflow_name: str, trigger: str, priority: int = 10, trigger_id: int = 0) -> None:
        """Internal enqueue with duplicate check. Lifecycle log: [ENGINE]"""
        with self._lock:
            # Check if already queued for this port
            for item_snapshot in self._queue.snapshot():
                if item_snapshot["port"] == port:
                    logger.info("[ENGINE] ENQUEUE_SKIP trigger_id=%d port=%s already queued", trigger_id, port)
                    return  # Already queued

            item = QueueItem(
                priority=priority,
                port=port,
                workflow_name=workflow_name,
                trigger_id=trigger_id,
            )
            self._queue.enqueue(item)
            logger.info("[ENGINE] ENQUEUED trigger_id=%d port=%s workflow=%s priority=%d queue_size=%d",
                        trigger_id, port, workflow_name, priority, self._queue.size)

            state = self._scheduler.get_state(port)
            state.set_queued()

            self._publish("automation.queue_changed", {
                "port": port,
                "workflow": workflow_name,
                "queue_size": self._queue.size,
            })

    def _worker_loop(self) -> None:
        """Main worker loop — processes queue."""
        while self._running.is_set():
            try:
                self._process_queue()
            except Exception:
                pass
            time.sleep(0.5)

    def _process_queue(self) -> None:
        """Process next item from queue."""
        while self._queue.available_slots > 0 and self._queue.size > 0:
            item = self._queue.dequeue()
            if item is None:
                break

            if not self._queue.acquire_slot():
                # Put it back
                self._queue.enqueue(item)
                break

            thread = threading.Thread(
                target=self._execute_workflow,
                args=(item,),
                daemon=True,
            )
            thread.start()

    def _execute_workflow(self, item: QueueItem) -> None:
        """Execute a workflow in a separate thread. Lifecycle log: [WORKFLOW]"""
        with self._lock:
            self._workflow_exec_count += 1
            self._workflow_started += 1
            self._dispatched += 1
            exec_num = self._workflow_exec_count
        logger.info("[WORKFLOW EXECUTE] trigger_id=%d EXEC_NUM=%d START port=%s workflow=%s", item.trigger_id, exec_num, item.port, item.workflow_name)
        state = self._scheduler.get_state(item.port)
        state.set_running(item.workflow_name)

        result = AutomationResult(
            port=item.port,
            workflow_name=item.workflow_name,
            started_at=time.time(),
            trigger="queued",
        )

        self._publish("automation.started", {
            "port": item.port,
            "workflow": item.workflow_name,
        })

        try:
            workflow = self._registry.get(item.workflow_name)
            if workflow is None:
                raise ValueError(f"Workflow not found: {item.workflow_name}")

            workflow_result = self._runner.run(
                workflow, item.port,
                on_step_complete=self._on_step_complete,
                trigger_id=item.trigger_id,
            )
            result.workflow_result = workflow_result
            result.success = workflow_result.success
            result.finished_at = time.time()

            if workflow_result.success:
                with self._lock:
                    self._workflow_completed += 1
                logger.info("[WORKFLOW EXECUTE] trigger_id=%d OK port=%s workflow=%s duration=%.2fs",
                            item.trigger_id, item.port, item.workflow_name, result.duration_seconds)
                self.log_execution_audit()
                state.record_result(item.workflow_name, True)
                state.set_idle()
                self._publish("automation.completed", {
                    "port": item.port,
                    "workflow": item.workflow_name,
                    "duration": result.duration_seconds,
                })
            else:
                # Check retry for reactivation workflows
                if self._should_retry(item.port, item.workflow_name, workflow_result):
                    result.retried = True
                    logger.info("[WORKFLOW EXECUTE] trigger_id=%d RETRY port=%s workflow=%s", item.trigger_id, item.port, item.workflow_name)
                    self._enqueue(item.port, item.workflow_name, "retry", priority=5, trigger_id=item.trigger_id)
                    self._publish("automation.retry", {
                        "port": item.port,
                        "workflow": item.workflow_name,
                    })
                else:
                    failure_reason = "; ".join(workflow_result.errors) if workflow_result.errors else "unknown"
                    with self._lock:
                        self._workflow_failed += 1
                        self._failure_reasons[failure_reason] = self._failure_reasons.get(failure_reason, 0) + 1
                    logger.info("[WORKFLOW EXECUTE] trigger_id=%d FAIL port=%s workflow=%s errors=%s",
                                item.trigger_id, item.port, item.workflow_name, workflow_result.errors)
                    self.log_execution_audit()
                    state.record_result(item.workflow_name, False)
                    state.set_idle()
                    result.error = failure_reason
                    self._publish("automation.failed", {
                        "port": item.port,
                        "workflow": item.workflow_name,
                        "error": result.error,
                    })
        except Exception as e:
            with self._lock:
                self._workflow_failed += 1
                err_str = str(e)
                self._failure_reasons[err_str] = self._failure_reasons.get(err_str, 0) + 1
            logger.info("[WORKFLOW EXECUTE] trigger_id=%d ERROR port=%s workflow=%s error=%s", item.trigger_id, item.port, item.workflow_name, e)
            self.log_execution_audit()
            result.success = False
            result.error = str(e)
            result.finished_at = time.time()
            state.set_idle()
            self._publish("automation.failed", {
                "port": item.port,
                "workflow": item.workflow_name,
                "error": str(e),
            })
        finally:
            self._queue.release_slot()
            with self._lock:
                self._results.append(result)

    # ------------------------------------------------------------------
    # Sprint 15U: Skill result → PortWorkerState → EventBus
    # ------------------------------------------------------------------

    # Maps SkillResult.data keys → PortWorkerState field names
    _SKILL_RESULT_TO_STATE: Dict[str, str] = {
        "number": "nomor",
        "nik": "nik",
        "kk": "kk",
        "grace_date": "masa_aktif",
    }

    # Skill data keys that map to RESPON (status/detail column)
    _SKILL_RESULT_TO_RESPON: Dict[str, str] = {
        "cpin_state": "cpin_state",
        "card_status": "card_status",
        "modem_online": "modem_online",
        "ready": "ready",
        "injected": "injected",
        "provisional": "provisional",
        "success": "success",
    }

    def _on_step_complete(self, step_name: str, skill_result: Any, context: Any) -> None:
        """Callback after each skill step: map result → PortWorkerState → EventBus.

        Sprint 15U: This is the bridge that makes skill data reach the UI.
        BUILD-B: Added [COMMAND] and [RESULT] tracing.
        """
        port = skill_result.port
        data = skill_result.data

        # [RESULT] trace — every step result
        logger.info("[RESULT] PORT=%s SKILL=%s SUCCESS=%s DATA_KEYS=%s",
                     port, step_name, skill_result.success,
                     list(data.keys()) if data else [])

        if not skill_result.success:
            return

        if not data or not port:
            return

        # [COMMAND] trace — what command was used (from data if available)
        ussd_code = data.get("ussd_code") or data.get("raw_cnum")
        if ussd_code:
            logger.info("[COMMAND] PORT=%s SKILL=%s COMMAND=%s", port, step_name, ussd_code)

        # 1. Update PortWorkerState card data via WorkerManager
        card_updates: Dict[str, str] = {}
        for data_key, state_field in self._SKILL_RESULT_TO_STATE.items():
            value = data.get(data_key)
            if value is not None and value != "":
                card_updates[state_field] = str(value)

        if card_updates and self._port_state_provider is not None:
            port_state = self._port_state_provider.get_port_state(port)
            if port_state is not None:
                port_state.set_card_data(**card_updates)

        # 2. Build RESPON from status-like skill data
        respon_parts: list = []
        for data_key in self._SKILL_RESULT_TO_RESPON:
            value = data.get(data_key)
            if value is not None and value != "":
                respon_parts.append(str(value))

        # 3. Publish port.data.updated for UI refresh
        if self._event_bus is not None:
            payload: Dict[str, Any] = {"port": port}
            for field, value in card_updates.items():
                payload[field] = value
            if respon_parts:
                payload["respon"] = ", ".join(respon_parts)
            if len(payload) > 1:
                self._event_bus.publish("port.data.updated", payload)

    def _should_retry(self, port: str, workflow_name: str, workflow_result: Any) -> bool:
        """Check if retry is needed for reactivation workflows."""
        if workflow_name not in ("reactivate_fast", "reactivate_full"):
            return False

        context = workflow_result.context
        if context is None:
            return False

        grace_before = context.get("grace_awal", "")
        grace_after = context.get("grace_akhir", "")
        attempt = context.get("injection_attempt", 0)

        should, _ = self._retry_policy.evaluate_result(grace_before, grace_after, attempt)
        return should

    def _publish(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Publish event to event bus."""
        if self._event_bus:
            try:
                self._event_bus.publish(event_name, payload)
            except Exception:
                pass

    def _on_port_excluded(self, payload: Dict[str, Any]) -> None:
        """Cancel queued workflow when port is excluded (Sprint 11A)."""
        port = payload.get("port")
        if port:
            removed = self._queue.remove_by_port(port)
            if removed > 0:
                with self._lock:
                    self._workflow_cancelled += 1
                logger.info("[WORKFLOW CANCELLED] PORT=%s REASON=port_excluded removed_from_queue=%d", port, removed)

    # ------------------------------------------------------------------
    # Sprint 15I: Trigger Ownership Stats
    # ------------------------------------------------------------------

    def get_trigger_source_counts(self) -> Dict[Tuple[str, str], int]:
        """Return trigger counts by (trigger_type, source)."""
        with self._lock:
            return dict(self._trigger_source_counts)

    def is_duplicate_detected(self) -> bool:
        """Return True if any duplicate trigger was detected."""
        return self._duplicate_detected

    def get_duplicate_events(self) -> List[Dict[str, str]]:
        """Return list of duplicate trigger events."""
        with self._lock:
            return list(self._duplicate_events)

    def get_workflow_exec_count(self) -> int:
        """Return total workflow executions started."""
        with self._lock:
            return self._workflow_exec_count

    def get_runtime_stats(self) -> Dict[str, int]:
        """Return workflow runtime stats (Sprint 15J)."""
        with self._lock:
            return {
                "started": self._workflow_started,
                "completed": self._workflow_completed,
                "failed": self._workflow_failed,
                "cancelled": self._workflow_cancelled,
            }

    def get_top_failure_reason(self) -> str:
        """Return the most common failure reason (Sprint 15J)."""
        with self._lock:
            if not self._failure_reasons:
                return "none"
            return max(self._failure_reasons, key=self._failure_reasons.get)

    # ------------------------------------------------------------------
    # Sprint 15L: Delivery Report
    # ------------------------------------------------------------------

    def get_delivery_report(self) -> str:
        """Generate full delivery audit report (Sprint 15L)."""
        with self._lock:
            started = self._workflow_started
            completed = self._workflow_completed
            failed = self._workflow_failed
            cancelled = self._workflow_cancelled
            reasons = dict(self._failure_reasons)
            top_reason = max(reasons, key=reasons.get) if reasons else "none"

        report = (
            "=================================================\n"
            "WORKFLOW DELIVERY AUDIT\n"
            "=================================================\n"
            f"\n"
            f"TRIGGERS RECEIVED: {self._triggers_received}\n"
            f"WORKFLOWS STARTED: {started}\n"
            f"WORKFLOWS COMPLETED: {completed}\n"
            f"WORKFLOWS FAILED: {failed}\n"
            f"WORKFLOWS CANCELLED: {cancelled}\n"
            f"SKILLS FOUND: {self._skills_found}\n"
            f"SKILLS MISSING: {self._skills_missing}\n"
            f"COMMANDS BUILT: {self._commands_built}\n"
            f"COMMANDS SENT: {self._commands_sent}\n"
            f"RESPONSES RECEIVED: {self._responses_received}\n"
            f"TIMEOUTS: {self._responses_timeout}\n"
            f"LAST BREAKPOINT: {self._last_breakpoint}\n"
            f"TOP FAILURE: {top_reason}\n"
            f"\n"
            "=================================================\n"
        )
        return report

    def update_delivery_stats(self, **kwargs) -> None:
        """Update delivery stats from instrumented components."""
        with self._lock:
            if "skills_found" in kwargs:
                self._skills_found += kwargs["skills_found"]
            if "skills_missing" in kwargs:
                self._skills_missing += kwargs["skills_missing"]
            if "commands_built" in kwargs:
                self._commands_built += kwargs["commands_built"]
            if "commands_sent" in kwargs:
                self._commands_sent += kwargs["commands_sent"]
            if "responses_received" in kwargs:
                self._responses_received += kwargs["responses_received"]
            if "responses_timeout" in kwargs:
                self._responses_timeout += kwargs["responses_timeout"]
            if "last_breakpoint" in kwargs:
                self._last_breakpoint = kwargs["last_breakpoint"]

    def log_delivery_report(self) -> None:
        """Log the full delivery audit report."""
        report = self.get_delivery_report()
        for line in report.split("\n"):
            logger.info("[DELIVERY REPORT] %s", line)
