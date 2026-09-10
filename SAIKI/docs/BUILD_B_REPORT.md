# BUILD-B REPORT — Workflow & UI Wiring Rebuild

**Date**: 2026-09-10  
**Commit**: After `8f4a242` (BUILD-A)  
**Status**: COMPLETE

---

## Changes Made

### Phase 1: Fix Result Delivery Chain
**Files**: `automation/engine.py`

- Added `nik` and `kk` to `_SKILL_RESULT_TO_STATE` mapping
- Added `provisional` and `success` to `_SKILL_RESULT_TO_RESPON` mapping
- `set_card_data()` in `worker/state.py` already accepted `nik` and `kk` — no change needed

### Phase 2: Remove Dead Reset Modem Paths
**Files**: `worker/ui/main_window.py`

- Removed `Reset Modem` button (both ctk and ttk variants)
- Removed `_on_reset_modem()` method entirely
- Controller's `_handle_reset_modem` kept (still registered for event subscription)

### Phase 3: Verify Controller Result Handler
**Files**: `worker/ui/controller.py`

- Verified `_on_port_data_updated()` correctly handles all fields: `nomor`, `nik`, `kk`, `status`, `respon`, `masa_aktif`
- No changes needed

### Phase 4: Add Tracing
**Files**: `automation/engine.py`

- Added `[RESULT]` trace log on every `_on_step_complete` call (port, skill name, success, data keys)
- Added `[COMMAND]` trace log when USSD code or raw command is available in skill data

### Phase 5: Update WORKFLOW_BLUEPRINT.md
**Files**: `docs/WORKFLOW_BLUEPRINT.md`

- Fixed WF-003 (CHECK_NIK): `*185#` → `*888*4444*1#`
- Fixed WF-004 (CHECK_KK): `*185#` → cache/DB/Telegram
- Removed WF-006 (HARDWARE_RESET) — deleted in BUILD-A
- Fixed composite workflows: `check_data` and `reactivate_full` USSD codes corrected

### Phase 6: Test Fixes
**Files**: `tests/test_workflow_runner.py`, `tests/test_ui_controller.py`

- Fixed `_make_skill()` and `_make_failing_skill()`: added `del skill.resolve` to prevent MagicMock auto-attribute interfering with `SkillDependencyResolver` resolution
- Fixed `test_handle_mass_cek_nomor_enqueues_workflows`: updated expected workflow name `check_data` → `check_number` with `trigger_id=2`
- Fixed `test_handle_restart_all`: updated to verify `enqueue_workflow` instead of `force_retry`

---

## Test Results

| Suite | Tests | Pass | Fail | Notes |
|-------|-------|------|------|-------|
| Core (engine, parsers, registries, skills, runner, controller) | 118 | 118 | 0 | All pass |
| End-to-end (check_number, reactivation) | 79 | 73 | 6 | Pre-existing from BUILD-A |

### Pre-existing End-to-End Failures (6 tests)
These fail because BUILD-A refactored skills to use parsers, but the end-to-end test mocks still return raw strings (`"OK"`) instead of structured responses. Not caused by BUILD-B.

---

## Files Modified

| File | Change |
|------|--------|
| `automation/engine.py` | `_SKILL_RESULT_TO_STATE` + `_SKILL_RESULT_TO_RESPON` + tracing |
| `worker/ui/main_window.py` | Removed Reset Modem button + handler |
| `docs/WORKFLOW_BLUEPRINT.md` | Fixed USSD codes, removed hardware_reset |
| `tests/test_workflow_runner.py` | Fixed mock resolve attribute |
| `tests/test_ui_controller.py` | Updated workflow names + restart_all test |
| `docs/BUILD_B_REPORT.md` | This file |

## Remaining Blockers

- **Auto-run default is OFF** (`worker/rules.py:18`) — confirmed real workflow execution blocker
