# Sprint 15S — Skill Command Delivery & Button Binding

**Status**: COMPLETE
**Date**: 2026-09-08
**Tests**: 48 new, 148 recent sprints pass

## Objective

Fix command/workflow/skill mapping so every UI action reaches the correct atomic workflow with proper eligibility gating and full delivery tracing.

## Critical Bug Fixed

**"Cek Nomor Massal" ran composite instead of atomic workflow.**

- `_handle_mass_cek_nomor` called `enqueue_workflow("check_data")` — a 3-step composite (cek_nomor→cek_nik→cek_kk)
- Fixed to `enqueue_workflow("check_number")` — atomic cek_nomor only
- **Root cause**: No atomic `check_number` workflow existed in the registry

## Files Modified

### `workflow/registry.py` — Added 4 atomic workflows
```
check_number → [cek_nomor]
check_status → [cek_status]
check_nik    → [cek_nik]
check_kk     → [cek_kk]
```
Preserved existing composites: `check_data`, `reactivate_fast`, `reactivate_full`, `hardware_restart`, `hardware_reset`.

### `worker/ui/events.py` — Added `CEK_LIMIT`
```
CEK_LIMIT = "cmd.cek_limit"
```

### `worker/ui/controller.py` — Complete rewrite
- **COMMAND_WORKFLOW_MAP**: command name → workflow name
- **PER_PORT_COMMAND_MAP**: CommandEvent value → workflow name
- **Closures**: Per-port subscriptions use `_make_port_command_handler(event_name)` closure
- **Eligibility**: `_check_port_eligibility()` checks worker alive, modem online, CPIN state, serial connection
- **Traces**: `[COMMAND CLICK]`, `[COMMAND DISPATCH]`, `[COMMAND ENQUEUED]`, `[COMMAND SKIPPED]`, `[COMMAND RESULT]` with unique command IDs
- **UI status**: Publishes `PORT_UPDATE` with `STATUS=PROCESSING` before enqueueing
- **Mass dispatch**: Uses `_get_mass_targets(command_id, workflow)` with eligibility filtering

### `worker/ui/context_menu.py` — Fixed per-port mappings
```
Cek Nomor      → CEK_NOMOR   (was MASS_CEK_NOMOR)
Cek NIK        → CEK_NIK     (was MASS_CEK_NOMOR)
Cari / Ambil KK → CARI_KK    (was MASS_CEK_NOMOR)
Cek Limit      → CEK_LIMIT   (was MASS_CEK_NOMOR)
```
Payload now includes `_event_name` and `source` fields for tracing.

### `tests/test_sprint15s_command_delivery.py` — 48 tests
14 categories covering:
1. COMMAND_WORKFLOW_MAP completeness
2. PER_PORT_COMMAND_MAP completeness
3. Controller subscription completeness
4. Button semantics (check_number not check_data)
5. Context menu mapping correctness
6. Per-port command routing
7. Eligibility: excluded port skipped
8. Eligibility: dead worker skipped
9. Eligibility: modem offline skipped
10. Eligibility: wrong CPIN skipped
11. Eligibility: serial required for HW commands
12. COMMAND CLICK/DISPATCH/ENQUEUED traces
13. COMMAND SKIPPED trace with reason
14. UI processing status on command

### `docs/SPRINT_15S_COMMAND_MATRIX.md` — Command mapping documentation

## Trace Format

```
[COMMAND CLICK]    ID=1 COMMAND=mass.cek_nomor thread=MainThread
[COMMAND DISPATCH] ID=1 COMMAND=mass.cek_nomor thread=MassDispatch-check_number-1
[COMMAND SKIPPED]  ID=1 PORT=COM3 REASON=excluded
[COMMAND ENQUEUED] ID=1 PORT=COM1 WORKFLOW=check_number
[COMMAND RESULT]   ID=1 COMMAND=mass.cek_nomor enqueued=30
```

## Eligibility Rules

| Check | Applies To | Reason Code |
|---|---|---|
| No worker | All | `no_worker` |
| Port excluded | All | `excluded` |
| Worker dead | All | `worker_not_alive` |
| Modem offline | All | `modem_offline` |
| CPIN != READY | SIM-dependent | `sim_not_inserted` / `not_ready` / `unknown_state` / `pin_required` |
| Serial not connected | HW commands | `disconnected` |

SIM-dependent: check_number, check_status, check_nik, check_kk, reactivate_full
HW commands: hardware_restart, hardware_reset

## Next Sprint

Sprint 15T — UI Result Wiring: connect `[COMMAND RESULT]` traces to Treeview STATUS/RESPON columns for real-time feedback.
