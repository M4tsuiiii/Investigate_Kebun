# SPRINT 6 REPORT — SAIKI Skill Engine Foundation

**Sprint:** 6
**Theme:** Skill Engine Foundation
**Date:** 2026-08-29

---

## 1. Sprint Overview

Sprint 6 refactors SAIKI into a **Skill-Based Architecture**. Each business operation — checking a modem, reading SIM status, verifying NIK, sending USSD — becomes an atomic, reusable **Skill**. Skills are independent units of work with a uniform interface, designed for composition by a future Workflow Engine (Sprint 7).

**Goal:** Extract every discrete operation into a `Skill` subclass with:
- A standard `execute(port, **kwargs) -> SkillResult` signature
- Dependency injection via `__init__`
- Unified success/failure reporting via `SkillResult`
- Zero inter-skill dependencies

---

## 2. Implementation Summary

### Base Infrastructure

| # | File | Purpose |
|---|------|---------|
| 1 | `worker/skills/__init__.py` | Exports `Skill`, `SkillResult` |
| 2 | `worker/skills/base.py` | Abstract `Skill` ABC + `SkillResult` dataclass |

### Skills

| # | File | Skill |
|---|------|-------|
| 3 | `worker/skills/cek_nomor.py` | `CekNomor` — modem responsiveness via AT |
| 4 | `worker/skills/cek_status.py` | `CekStatus` — SIM/CPIN status via AT+CPIN? |
| 5 | `worker/skills/cek_nik.py` | `CekNik` — NIK lookup via USSD *185# |
| 6 | `worker/skills/cek_kk.py` | `CekKk` — KK lookup via USSD *185# |
| 7 | `worker/skills/inject_reaktivasi.py` | `InjectReaktivasi` — USSD reactivation |
| 8 | `worker/skills/verify_grace.py` | `VerifyGrace` — card grace period via USSD |
| 9 | `worker/skills/restart_hardware.py` | `RestartHardware` — modem restart via ATZ |
| 10 | `worker/skills/reset_hardware.py` | `ResetHardware` — full hardware reset cycle |

### Tests

| # | File | Coverage |
|---|------|----------|
| 11 | `tests/test_skill_base.py` | `Skill` ABC + `SkillResult` |
| 12 | `tests/test_skill_cek_nomor.py` | `CekNomor` |
| 13 | `tests/test_skill_cek_status.py` | `CekStatus` |
| 14 | `tests/test_skill_cek_nik.py` | `CekNik` |
| 15 | `tests/test_skill_cek_kk.py` | `CekKk` |
| 16 | `tests/test_skill_inject_reaktivasi.py` | `InjectReaktivasi` |
| 17 | `tests/test_skill_verify_grace.py` | `VerifyGrace` |
| 18 | `tests/test_skill_restart_hardware.py` | `RestartHardware` |
| 19 | `tests/test_skill_reset_hardware.py` | `ResetHardware` |

---

## 3. Skill Catalog

| Skill | Input | Output | Dependencies |
|-------|-------|--------|-------------|
| **cek_nomor** | `port`, `timeout` | `modem_responsive`, `raw_response` | `ATClient` |
| **cek_status** | `port`, `timeout` | `cpin_state`, `raw_response`, `sim_ready` | `ATClient` |
| **cek_nik** | `port`, `timeout` | `raw_response`, `has_payload`, `ussd_code` | `USSDRuntime` |
| **cek_kk** | `port`, `timeout` | `raw_response`, `has_payload`, `ussd_code` | `USSDRuntime` |
| **inject_reaktivasi** | `port`, `ussd_code`, `timeout` | `raw_response`, `injected`, `ussd_code` | `USSDRuntime` |
| **verify_grace** | `port`, `timeout` | `raw_response`, `card_status`, `grace_date` | `USSDRuntime` |
| **restart_hardware** | `port`, `wait_seconds`, `timeout` | `restart_sent`, `modem_online` | `ATClient` |
| **reset_hardware** | `port`, `wait_seconds` | `modem_online`, `cpin_state`, `ready` | `SerialAdapter`, `ATClient` |

---

## 4. Architecture — Skill vs Workflow

```
┌─────────────────────────────────────────────┐
│              Workflow Engine (Sprint 7)      │
│   Orchestrates skills into multi-step flows │
│   Manages state, retries, branching         │
├─────────────────────────────────────────────┤
│                Skill Layer                   │
│   Each skill = one atomic business op       │
│   Uniform execute() interface               │
│   Dependency-injected via __init__          │
├─────────────────────────────────────────────┤
│             Transport Layer                 │
│   ATClient · USSDRuntime · SerialAdapter    │
│   Low-level modem/serial communication      │
└─────────────────────────────────────────────┘
```

**Key separation:**
- **Skills** know *what* to do (verify NIK, restart modem)
- **Workflows** know *when* and *in what order* to do it
- **Transport** knows *how* to talk to hardware

Skills never call other skills. Workflows compose them.

---

## 5. Design Decisions

1. **No inter-skill dependencies.** Each skill is fully self-contained. Composition is the workflow engine's job.
2. **Uniform interface.** Every skill implements `execute(port, **kwargs) -> SkillResult`. No exceptions.
3. **Dependency injection.** Skills receive `ATClient`, `USSDRuntime`, etc. through `__init__`. Tests inject mocks.
4. **Unified result type.** `SkillResult` carries `success`, `data`, and `error`. No skill invents its own return shape.
5. **Workflow-ready.** Skills are designed to be wired into a DAG-based workflow engine without modification.

---

## 6. Test Results

| Sprint | Total Tests | Status |
|--------|-------------|--------|
| Sprint 5 | 571 | ✅ All passing |
| Sprint 6 | 655+ | ✅ All passing |
| **Delta** | **+84** | |

All 84 new tests cover success paths, failure paths, timeout handling, and edge cases for every skill.

---

## 7. What's NOT Done

- **Workflow Engine** — no orchestrator yet; skills are called manually
- **Persistent state store** — skills are stateless; workflow-level state is not implemented
- **Retry/backoff logic** — individual skills don't retry; that belongs in workflows
- **Skill registry/discovery** — no dynamic skill lookup; skills are imported directly
- **CLI integration** — no `sak skill cek-nomor` command yet

---

## 8. Next Steps — Sprint 7: Workflow Engine

Sprint 7 will build the **Workflow Engine** on top of this skill layer:

1. Define a workflow DSL or YAML schema
2. Implement a DAG-based executor that calls skills in sequence/parallel
3. Add workflow-level state management and error recovery
4. Wire workflows to the existing CLI and future API
5. Migrate existing hardcoded logic (NIK check flow, reactivation flow) into workflows
6. Add workflow versioning and rollback support
