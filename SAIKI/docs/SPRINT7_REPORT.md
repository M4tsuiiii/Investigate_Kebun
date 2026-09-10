# SPRINT 7 REPORT — SAIKI Workflow Engine

**Sprint:** 7
**Theme:** Workflow Engine
**Date:** 2026-08-29

---

## 1. Sprint Overview

Sprint 7 builds the **Workflow Engine** that connects Sprint 6 Skills into executable, multi-step flows. Each workflow is a declarative sequence of skill calls with shared context, cleanup discipline, and failure handling.

**Goal:** Create a workflow layer that:
- Orchestrates Skills into multi-step business flows
- Maintains shared state via `WorkflowContext` (per-run, per-port)
- Stops on first failure (no partial execution)
- Reuses `CleanupManager` from Sprint 2 for between-step cleanup
- Exposes `on_step_complete` callback for UI/Automation integration

---

## 2. Implementation Summary

### Core Infrastructure

| # | File | Purpose |
|---|------|---------|
| 1 | `workflow/__init__.py` | Package exports — `WorkflowContext`, `WorkflowDefinition`, `WorkflowRegistry`, `WorkflowRunner`, `WorkflowResult` |
| 2 | `workflow/context.py` | `WorkflowContext` — shared memory per workflow run (per-port isolation) |
| 3 | `workflow/definitions.py` | `WorkflowDefinition` — declarative step list with skill name, args, and timeout |
| 4 | `workflow/registry.py` | `WorkflowRegistry` — stores and retrieves workflow definitions by name |
| 5 | `workflow/runner.py` | `WorkflowRunner` — orchestrates skill execution, context propagation, cleanup |
| 6 | `workflow/result.py` | `WorkflowResult` — execution outcome with step-by-step trace |
| 7 | `workflow/exceptions.py` | `WorkflowError`, `SkillNotFoundError`, `WorkflowExecutionError` |

### Tests

| # | File | Coverage |
|---|------|----------|
| 8 | `tests/test_workflow_context.py` | `WorkflowContext` — get/set, thread isolation |
| 9 | `tests/test_workflow_definitions.py` | `WorkflowDefinition` — creation, validation, serialization |
| 10 | `tests/test_workflow_registry.py` | `WorkflowRegistry` — register, retrieve, list |
| 11 | `tests/test_workflow_runner.py` | `WorkflowRunner` — happy path, failure path, cleanup, callback |
| 12 | `tests/test_workflow_result.py` | `WorkflowResult` — success, failure, step tracking |
| 13 | `tests/test_workflow_integration.py` | End-to-end workflows with mocked skills |

---

## 3. Architecture

```
┌──────────────────────────────────────────────────┐
│                    UI (Future)                    │
│         CLI · Web · API · Scheduler              │
├──────────────────────────────────────────────────┤
│            Automation Engine (Sprint 8)           │
│   Queuing · Scheduling · Mass Actions · Retry    │
├──────────────────────────────────────────────────┤
│             Workflow Engine (Sprint 7)            │
│   Orchestrates skills into multi-step flows      │
│   Context · Registry · Runner · Result           │
├──────────────────────────────────────────────────┤
│                Skill Layer (Sprint 6)             │
│   Each skill = one atomic business operation     │
│   Uniform execute() interface                    │
├──────────────────────────────────────────────────┤
│             Transport Layer (Sprint 2-3)          │
│   ATClient · USSDRuntime · SerialAdapter          │
│   Low-level modem/serial communication            │
└──────────────────────────────────────────────────┘
```

**Key separation:**
- **UI** knows *what the user wants to trigger*
- **Automation** knows *when and how often* to run workflows
- **Workflow** knows *which skills to call and in what order*
- **Skills** know *what to do* (verify NIK, restart modem)
- **Transport** knows *how to talk to hardware*

Workflows never call skills directly. Automation Engine triggers them.

---

## 4. Workflow Flow

```
┌─────────────────┐
│  Load Definition │
│  (by name)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Resolve Skill   │
│  from skill_map  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Execute Skill   │
│  (port, **args)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Update Context  │
│  with result     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Cleanup +       │
│  Cooldown        │
└────────┬────────┘
         │
    ┌────┴────┐
    │  Next   │
    │  Step?  │
    └────┬────┘
    Yes  │  No
    │    └──────► WorkflowResult
    ▼
  (repeat)
```

**Failure path:** Any skill failure triggers immediate stop → `WorkflowResult(success=False, error=...)`.

---

## 5. Context Design

`WorkflowContext` is a per-run, per-port key-value store.

```python
ctx = WorkflowContext(port="COM3")
ctx.set("modem_responsive", True)
ctx.set("nik", "3201234567890001")
ctx.get("modem_responsive")  # True
```

**Rules:**
- Each workflow run gets its own `WorkflowContext` — no sharing between ports
- Context survives across steps within a single workflow
- Context is read-only from skill perspective (set by runner after skill execution)
- `injection_attempt` field exists for future Sprint 8 retry logic

**Thread Safety:**
- One `WorkflowContext` per workflow run
- No concurrent access to the same context instance
- Port-level isolation prevents cross-contamination

---

## 6. Registry Design

`WorkflowRegistry` stores and retrieves `WorkflowDefinition` objects by name.

```python
registry = WorkflowRegistry()
registry.register(reactivate_full)  # WorkflowDefinition
registry.get("reactivate_full")     # -> WorkflowDefinition
registry.list_workflows()           # -> ["check_data", "reactivate_fast", ...]
```

**Pre-Built Workflows:**

| Workflow | Steps | Purpose |
|----------|-------|---------|
| `check_data` | `cek_nomor` → `cek_nik` → `cek_kk` | Verify modem data and NIK/KK |
| `reactivate_fast` | `inject_reaktivasi` → `verify_grace` | Quick reactivation (skip checks) |
| `reactivate_full` | `cek_nomor` → `cek_status` → `cek_nik` → `cek_kk` → `inject_reaktivasi` → `verify_grace` | Full reactivation flow |
| `hardware_restart` | `restart_hardware` | Restart modem only |
| `hardware_reset` | `reset_hardware` | Full hardware reset cycle |

---

## 7. Runner Design

`WorkflowRunner` is the core orchestrator.

```python
runner = WorkflowRunner(
    skill_map=skill_map,
    cleanup_manager=cleanup_manager,
    on_step_complete=callback  # optional
)
result = runner.run("reactivate_full", port="COM3", timeout=30)
```

**Execution logic:**
1. Load workflow definition from registry
2. For each step: resolve skill → inject dependencies → execute → update context
3. Run `CleanupManager` between steps (reuse Sprint 2 cleanup)
4. Apply cooldown between steps if configured
5. On failure: stop immediately, return `WorkflowResult(success=False)`
6. On success: return `WorkflowResult(success=True, context=ctx)`

**Callback support:**
- `on_step_complete(step_name, result, context)` fires after each step
- Designed for UI progress updates and Automation Engine hooks

---

## 8. Design Decisions

1. **Stop on Failure** — First skill failure stops entire workflow. No partial execution.
2. **Cleanup Discipline** — `CleanupManager` handles between-step cleanup (reuse Sprint 2).
3. **Thread Safety** — Each workflow run gets its own `WorkflowContext` (no sharing between ports).
4. **Retry Ready** — `injection_attempt` field exists for future Sprint 8 retry logic.
5. **Callback Support** — `on_step_complete` callback for UI/Automation integration.
6. **Declarative Definitions** — Workflows are data, not code. Easy to serialize, version, store.
7. **Skill-agnostic Runner** — Runner doesn't know skill internals. Only calls `execute()`.

---

## 9. Test Results

| Sprint | Total Tests | Status |
|--------|-------------|--------|
| Sprint 5 | 571 | ✅ All passing |
| Sprint 6 | 655+ | ✅ All passing |
| Sprint 7 | 767+ | ✅ All passing |
| **Delta** | **+76** | |

All 76+ new tests cover:
- Context get/set operations and thread isolation
- Definition creation, validation, serialization
- Registry register/retrieve/list operations
- Runner happy path, failure path, cleanup, callback
- Result success/failure tracking
- End-to-end integration with mocked skills

---

## 10. What's NOT Done

- **Automation Engine** — no scheduling, queuing, or mass action support yet
- **UI wiring** — workflows exist but no frontend to trigger them
- **Scheduler** — no cron-like or interval-based triggering
- **Queue Manager** — no multi-port concurrent execution
- **Mass Action integration** — no batch processing across multiple modems
- **Dynamic workflow creation** — workflows are hardcoded in registry, not loaded from files
- **Workflow versioning** — no version tracking or rollback support
- **Persistent workflow state** — context is ephemeral, not saved to disk

---

## 11. Next Steps — Sprint 8: Automation Engine

Sprint 8 will build the **Automation Engine** on top of the workflow layer:

1. **Queue Manager** — concurrent port execution with pool management
2. **Scheduler** — cron-like and interval-based workflow triggering
3. **Mass Actions** — batch workflow execution across multiple modems
4. **Retry Logic** — exponential backoff using `injection_attempt` field
5. **Persistent State** — save workflow state to database for crash recovery
6. **Dashboard Integration** — real-time progress via WebSocket/CLI
7. **Workflow Templates** — load workflows from YAML/JSON files instead of hardcoding
