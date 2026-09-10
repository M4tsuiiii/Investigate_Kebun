# SAIKI Sprint 8 Report — Automation Engine

**Sprint:** 8
**Period:** Aug 27–29, 2026
**Status:** Complete

---

## 1. Sprint Overview

Build the Automation Engine that connects Hardware → Workflow → Skills. This layer sits between modem events (SIM changes, network state) and the workflow runner, deciding which workflows to run, when, and with what priority.

**Key deliverable:** `automation/` package — a fully asynchronous, thread-safe orchestrator that evaluates triggers, selects workflows via policy, queues work, and executes through `WorkflowRunner`.

---

## 2. Implementation Summary

| File | Purpose | Lines |
|------|---------|-------|
| `automation/__init__.py` | Package exports | ~40 |
| `automation/triggers.py` | `Trigger` enum + `TriggerEvent` dataclass | ~60 |
| `automation/state.py` | `AutomationState` + `AutomationStatus` enum | ~80 |
| `automation/result.py` | `AutomationResult` dataclass | ~70 |
| `automation/queue.py` | `WorkflowQueue` + `QueueItem` (FIFO priority queue with concurrency) | ~120 |
| `automation/policy.py` | `AutomationPolicy` + `AutomationMode` (workflow selection) | ~100 |
| `automation/retry.py` | `ReactivateRetryPolicy` (max 1 retry) | ~60 |
| `automation/scheduler.py` | `AutomationScheduler` (trigger → action evaluation) | ~150 |
| `automation/engine.py` | `AutomationEngine` (orchestrator) | ~180 |

**Total:** 9 files, ~860 lines

---

## 3. Architecture Diagram

```
Hardware Event
    ↓
Trigger (TriggerEvent)
    ↓
AutomationScheduler (evaluate → enqueue/standby/cancel)
    ↓
AutomationPolicy (select workflow)
    ↓
WorkflowQueue (FIFO with priority, max 2 concurrent)
    ↓
AutomationEngine._execute_workflow (thread)
    ↓
WorkflowRunner.run (Sprint 7)
    ↓
Skills (Sprint 6)
    ↓
AutomationResult + EventBus publish
```

---

## 4. Trigger System

Triggers map hardware events to actions the scheduler can evaluate.

| Trigger | Action |
|---------|--------|
| `MODEM_ONLINE` | `enqueue` |
| `MODEM_OFFLINE` | `cancel` |
| `SIM_INSERTED` | `enqueue` (if idle/standby) |
| `SIM_REMOVED` | `cancel` |
| `CPIN_READY` | `enqueue` (if idle/standby) |
| `CPIN_REQUIRED` | `standby` |
| `WORKFLOW_SUCCESS` | `standby` |
| `WORKFLOW_FAILED` | `none` |
| `USER_MASS_REACTIVATION` | `enqueue` |
| `USER_MASS_CHECK_NUMBER` | `enqueue` |

The scheduler matches incoming `TriggerEvent` instances against these rules, then delegates to `AutomationPolicy` for workflow selection.

---

## 5. Workflow Selection

`AutomationPolicy` maps `AutomationMode` to a concrete workflow:

| Mode | Workflow |
|------|----------|
| `CHECK_DATA` | `check_data` |
| `REACTIVATE_FAST` | `reactivate_fast` |
| `REACTIVATE_FULL` | `reactivate_full` |

---

## 6. Queue & Concurrency

- **FIFO priority queue** — items sorted by trigger priority (user-triggered > modem-triggered)
- **Max 2 concurrent workflows** — third request blocks until a slot opens
- **Cancel propagation** — `MODEM_OFFLINE` / `SIM_REMOVED` cancels pending queued items
- **Thread safety** — all shared state protected by `RLock`

---

## 7. Retry Policy

`ReactivateRetryPolicy` handles transient reactivation failures:

- **Max 1 retry** per workflow attempt
- Retry allowed only if grace period unchanged since last failure
- After max retries → status moves to `FAILED`

---

## 8. Test Coverage

| Sprint | Tests | Δ |
|--------|-------|---|
| 7 (Workflow Runner) | 761 | — |
| 8 (Automation Engine) | 835+ | +74 |

All tests passing. New tests cover scheduler evaluation logic, queue ordering, concurrency limits, retry boundaries, and state transitions.

---

## 9. What's NOT Done

- **UI integration** — no frontend wiring for automation controls
- **Telegram** — no bot-triggered automation
- **Mass Action wiring** — exists from Sprint 3, not connected to engine
- **Dashboard / Reporting** — no run history or stats view

---

## 10. Next Steps

1. **Sprint 9** — UI integration (automation toggle, mode selector, run status)
2. **Sprint 10** — Telegram bot triggers (remote start/stop)
3. **Sprint 11** — Dashboard & reporting (run history, success rates, average durations)
4. **Sprint 12** — Mass Action full wiring + advanced scheduling (cron-like)
