# Sprint 15P — Engine Entrypoint & Mass UI Freeze Fix

## Summary

Resolved UI freeze during mass commands and CPIN log flood. Engine entrypoint now has full boundary traces. Mass commands dispatch asynchronously to background threads. CPIN repetitive traces demoted to DEBUG level.

## Findings & Fixes

### Task 1: Engine Entrypoint Boundary Traces
**Problem**: After `[ENGINE] TRIGGER_IN`, no further logs appeared. Dead zone.
**Fix**: Added `[ENGINE ENTER]`, `[ENGINE EXIT]`, `[ENGINE LOCK]`, `[ENGINE AUTORUN GATE BEGIN/END]`, `[ENGINE WORKFLOW SELECT BEGIN/END]`, `[ENGINE ENQUEUE BEGIN/ENQUEUED]` traces with thread names.
**Files**: `automation/engine.py`

### Task 2: Mass Button UI Freeze
**Problem**: `_handle_mass_cek_nomor` ran synchronously on UI thread, blocking it for all 44 ports.
**Fix**: Handler now dispatches to background thread via `_threading.Thread(target=_dispatch, daemon=True).start()`. Returns immediately.
**Files**: `worker/ui/controller.py`

### Task 3: Eligible Mass Targets
**Problem**: Mass commands tried to enqueue on ports with NOT_INSERTED SIM, NOT_READY, or UNKNOWN CPIN state.
**Fix**: `_get_eligible_mass_targets()` filters by: worker alive, modem online, CPIN state READY/PIN_REQUIRED. Skipped ports logged with reason.
**Files**: `worker/ui/controller.py`

### Task 4: UI Heartbeat + Thread Dump
**Problem**: No way to detect or diagnose UI freeze.
**Fix**: `UIHeartbeat` class monitors `_drain_events` tick freshness. If >5s since last tick, logs `[UI FREEZE DETECTED]` with full thread stack dump via `sys._current_frames()`.
**Files**: `worker/ui/ui_heartbeat.py` (new), `worker/ui/main_window.py`

### Task 5: CPIN Log Flood Reduction
**Problem**: ~879 log lines/sec from 44 active ports. Repetitive traces flooded INFO channel.
**Fix**: Demoted per-poll traces to DEBUG level:
- `[PORT OWNERSHIP] ROLE=CPIN_RUNTIME ... ACTION=poll` → DEBUG
- `[BUFFER FLUSH]` → DEBUG
- `[CPIN TRACE]` / `[CPIN PARSE]` → DEBUG
- `[CPIN STATE] PREVIOUS/CURRENT` → DEBUG (only `CHANGED: YES` stays INFO)
- `[CPIN STABILIZE]` per-case traces → DEBUG
- `[SERIAL WRITE]` / `[SERIAL WRITE RESULT]` → DEBUG
- `[PORT OWNERSHIP] ROLE=SERIAL_ADAPTER read/readline/write` → DEBUG
- `[PORT OWNERSHIP] ROLE=AT_CLIENT send_command/send_ussd` → DEBUG
- `[RESET CLEANUP]` → DEBUG
- `[CPIN] poll_interval` → DEBUG
- `[CONFIRMATION POLL]` remains INFO (rare, important)
- `[CPIN STATE] CHANGED: YES` remains INFO (state transitions)
**Files**: `worker/cpin_runtime.py`, `app/infrastructure/serial/serial_adapter.py`, `app/infrastructure/serial/at_client.py`

## Test Results

| Metric | Count |
|--------|-------|
| Total tests | 1455 |
| Passed | 1453 |
| Errors (pre-existing) | 2 |
| New Sprint 15P tests | 20 |

### Pre-existing errors (unchanged)
- `test_cpin_runtime.test_start_creates_thread` — thread.join() on None
- `test_cpin_runtime.test_stop_clears_running` — thread.join() on None

### Tests fixed from earlier sprints
- `test_sprint15e` — assertLogs level INFO→DEBUG for CPIN TRACE
- `test_sprint15f` — TRIGGER_IN→ENGINE ENTER
- `test_sprint15g` — TRIGGER_IN→ENGINE ENTER (inspect source)
- `test_sprint15h` — TRIGGER_IN→ENGINE ENTER (2 places)
- `test_sprint15k` — BUFFER FLUSH / RESET CLEANUP assertLogs level→DEBUG
- `test_sprint15l` — SERIAL WRITE assertLogs level→DEBUG
- `test_sprint15n` — PORT OWNERSHIP assertLogs level→DEBUG
- `test_sprint11a` — mass handler worker mock attributes
- `test_end_to_end` — mass handler worker mock attributes

## Files Changed

| File | Change |
|------|--------|
| `automation/engine.py` | Boundary traces (ENTER/EXIT/LOCK/AUTORUN GATE/WORKFLOW SELECT/ENQUEUE) |
| `worker/ui/controller.py` | Async mass dispatch, `_get_eligible_mass_targets()`, [MASS CLICK/DISPATCH] traces |
| `worker/ui/main_window.py` | UIHeartbeat import/wire/start, [MASS CLICK] on buttons |
| `worker/ui/ui_heartbeat.py` | **NEW** — UIHeartbeat class with freeze detection + thread dump |
| `worker/cpin_runtime.py` | Repetitive traces → DEBUG, [CPIN PAUSE/STOPPED/STARTED] traces |
| `app/infrastructure/serial/serial_adapter.py` | WRITE/READ/READLINE traces → DEBUG |
| `app/infrastructure/serial/at_client.py` | send_command/send_ussd PORT OWNERSHIP → DEBUG |
| `tests/test_sprint15p_engine_mass_fix.py` | **NEW** — 20 tests for all Sprint 15P fixes |

## Remaining Work

- **Auto-run default OFF** — `worker/rules.py:18` — confirmed remaining blocker
- **Real hardware beta validation** — `python beta_test.py --port COMx --duration 18000`
- **Commit all changes** — single commit e7581fe still uncommitted
