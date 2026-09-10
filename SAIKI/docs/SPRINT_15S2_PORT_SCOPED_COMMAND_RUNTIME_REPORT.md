# Sprint 15S.2 — Port-Scoped Command Runtime & USSD Cek Nomor

**Status**: COMPLETE  
**Date**: 2026-09-08  
**Tests**: 40 unit tests + 48 (15S) + 17 (15S.1) = 105 total  

## Summary

Eliminated the global skill-map overwrite bug, implemented per-port dependency resolution via factory pattern, rewrote CekNomorSkill for real AT+CNUM → USSD fallback, added configurable USSD code, propagated command_id through the full path, and split COMMAND ACCEPTED vs COMMAND RESULT traces.

## Changes

### 1. Per-Port Factory Pattern (system_bootstrap.py)
- Created `SkillDependencyResolver` class (`worker/skills/dependency_resolver.py`)
- Created 8 factory classes: `_CekNomorSkillFactory`, `_CekStatusSkillFactory`, etc.
- `_wire_skills_for_worker()` now registers `_SkillFactoryBase` subclasses instead of overwriting shared `_skill_map`
- Stores `_port_workers: dict` for per-port worker references

### 2. WorkflowRunner Factory Support (workflow/runner.py)
- Added `_port_workers` attribute and `set_port_workers()` method
- `run()` resolves factories via `factory.resolve(resolver)` for each step
- Injects `skill_resolver` and `command_id=trigger_id` into skill execute kwargs

### 3. CekNomorSkill Rewrite (worker/skills/cek_nomor.py)
- Step 1: AT+CNUM → parse MSISDN from +CNUM response
- Step 2: Configured USSD fallback if CNUM returns no number
- Supports `skill_resolver` kwarg for per-port ATClient/UssdRuntime
- Full trace logging: `[CEK NOMOR START]`, `[CEK NOMOR CNUM]`, `[CEK NOMOR USSD FALLBACK]`, `[CEK NOMOR RESULT]`

### 4. Configurable USSD Code (settings_dialog.py)
- Added `number_ussd_code` to workflow config defaults and `_collect_settings()`
- Settings dialog now shows "Number-check USSD Code" text entry field
- CekNomorSkill reads from `settings["workflow"]["number_ussd_code"]`

### 5. command_id Propagation (controller.py → engine.py → runner.py → skill)
- `enqueue_workflow()` now accepts `trigger_id` parameter
- Controller passes `command_id` as `trigger_id` to engine
- Engine passes `trigger_id` to `runner.run()`
- Runner passes `command_id=trigger_id` to skill's `execute()` kwargs

### 6. COMMAND ACCEPTED vs COMMAND RESULT Split
- Per-port commands now emit `[COMMAND ACCEPTED]` on enqueue (not `[COMMAND RESULT]`)
- `[COMMAND RESULT]` only fires at workflow completion (success/failed/skipped)
- Mass commands also emit `[COMMAND ACCEPTED]` on enqueue

### 7. Event Subscriptions Fixed
- Added `CEK_STATUS = "cmd.cek_status"` to CommandEvent
- Added `RESTART_PORT = "cmd.restart_port"` to CommandEvent
- Added `cmd.cek_status`, `cmd.restart_port` to PER_PORT_COMMAND_MAP and ROUTE_BY_EVENT
- Context menu: "Cek Status SIM" → CEK_STATUS, "Restart Port" → RESTART_PORT

## Files Modified
- `worker/system_bootstrap.py` — Factory classes, _wire_skills_for_worker rewrite
- `workflow/runner.py` — Factory resolution, skill_resolver + command_id kwargs
- `worker/skills/cek_nomor.py` — Full rewrite: AT+CNUM → USSD fallback
- `worker/skills/dependency_resolver.py` — NEW: per-port dependency resolver
- `worker/ui/controller.py` — trigger_id propagation, ACCEPTED/RESULT split, new event subscriptions
- `worker/ui/events.py` — CEK_STATUS, RESTART_PORT events
- `worker/ui/context_menu.py` — Cek Status SIM, Restart Port menu items
- `worker/ui/settings_dialog.py` — number_ussd_code config
- `automation/engine.py` — trigger_id parameter on enqueue_workflow
- `tests/test_sprint15s2_port_scoped.py` — NEW: 40 end-to-end tests

## Test Results
- Sprint 15S unit tests: 48 pass
- Sprint 15S.1 integration tests: 17 pass
- Sprint 15S.2 port-scoped tests: 40 pass
- **Total: 105 pass, 0 fail**
