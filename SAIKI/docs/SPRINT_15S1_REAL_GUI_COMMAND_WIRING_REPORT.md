# Sprint 15S.1 — Real GUI Command Wiring & End-to-End Delivery

**Status**: COMPLETE
**Date**: 2026-09-08
**Tests**: 17 integration + 48 unit + 11 smoke = 76 new tests
**Regression**: 165 recent-sprint tests pass (0 failures)

## Objective

Prove every user-visible command feature is wired and functional from the actual GUI callback to its final workflow/skill result, with complete CLICK → DISPATCH → ENQUEUED → RESULT trace chain.

## Bugs Fixed

### 1. Reset Modem button silently did nothing
- **Before**: `_on_reset_modem` published `RESET_MODEM` with empty payload `{}`
- **Controller**: `payload.get("port")` returned None → handler returned silently
- **After**: Button reads `port_table.get_selection()`, includes port in payload. If no port selected, shows `[COMMAND RESULT] OUTCOME=skipped MESSAGE=no_port_selected` and publishes user-facing instruction via `MASS_PROGRESS`.

### 2. No `[COMMAND CLICK]` traces from GUI
- **Before**: GUI callbacks didn't log command traces
- **After**: Every callback logs `[COMMAND CLICK]` with COMMAND, PORT, SOURCE, THREAD

### 3. No `[COMMAND ROUTER READY]` at startup
- **After**: Controller logs one concise report per subscribed event at init

### 4. No `[COMMAND DELIVERY FAILED]` for unhandled events
- **After**: EventBus logs `[COMMAND DELIVERY FAILED]` when a `cmd.*` event has no subscribers or a handler raises

### 5. No `[COMMAND RESULT]` after enqueue
- **Before**: RESULT only logged on async workflow completion
- **After**: Controller logs `[COMMAND RESULT] OUTCOME=enqueued` immediately after successful enqueue, plus async completion/failure RESULT traces

### 6. No centralized routing table
- **Before**: Competing route tables (`COMMAND_WORKFLOW_MAP`, `PER_PORT_COMMAND_MAP`)
- **After**: Single `COMMAND_ROUTES` table defining event→workflow→eligibility→scope for all commands

## Files Modified

### `worker/ui/controller.py` — Complete rewrite
- `COMMAND_ROUTES`: Centralized routing table (19 routes)
- `ROUTE_BY_EVENT`: Dict lookup by event name
- `PER_PORT_COMMAND_MAP`: Per-port command → workflow
- `_log_router_ready()`: Logs all routes at startup
- `_subscribe_completion()`: Subscribes to `automation.completed`/`automation.failed`
- `_on_workflow_completed()`/`_on_workflow_failed()`: Emit `[COMMAND RESULT]`
- `_handle_reset_modem()`: Now reads selected port, shows feedback if none
- `_handle_auto_run_toggle()`: Now logs `[COMMAND CLICK]` and `[COMMAND RESULT]`

### `worker/ui/main_window.py` — Fixed GUI callbacks
- `_on_auto_run_toggle()`: Logs `[COMMAND CLICK]`
- `_on_mass_cek_nomor()`: Logs `[COMMAND CLICK]`, includes `source` in payload
- `_on_mass_reaktivasi()`: Logs `[COMMAND CLICK]`, includes `source` in payload
- `_on_restart_all()`: Logs `[COMMAND CLICK]`, includes `source` in payload
- `_on_reset_modem()`: Reads `port_table.get_selection()`, logs `[COMMAND CLICK]`, shows feedback if no port

### `worker/ui/event_bus.py` — Delivery failure logging
- `publish()`: Logs `[COMMAND DELIVERY FAILED]` for `cmd.*` events with no subscribers
- `publish()`: Logs `[COMMAND DELIVERY FAILED]` when handler raises exception
- `has_subscribers()`: New method

### `worker/ui/context_menu.py` — [COMMAND CLICK] traces
- `_on_menu_click()`: Logs `[COMMAND CLICK]` with COMMAND, PORT, SOURCE, THREAD

### `tests/test_sprint15s_command_delivery.py` — Updated for new controller
- Tests now reference `COMMAND_ROUTES`/`ROUTE_BY_EVENT` instead of `COMMAND_WORKFLOW_MAP`
- Fixed force_retry test (now None, not "hardware_restart")
- Fixed UI processing test (uses `status` key, not `value`)

### `tests/test_sprint15s1_integration.py` — 17 integration tests
- Category 1: Cek Nomor Massal → check_number (not check_data)
- Category 2: Reaktivasi Massal → reactivate_full
- Category 3: Restart All → hardware_restart
- Category 4: Reset Modem with port → hardware_reset
- Category 5: All per-port context-menu commands
- Category 6: Reset Modem no selection → visible feedback
- Category 7: Non-eligible ports → COMMAND SKIPPED
- Category 8: Unhandled event → COMMAND DELIVERY FAILED
- Category 9: Workflow completion → COMMAND RESULT
- Category 10: No blocking GUI thread

### `tests/smoke_command_wiring.py` — 11-route smoke test
```
[COMMAND WIRING SMOKE TEST]
Command                        CLICK    DISPATCH   ENQUEUED   RESULT
------------------------------------------------------------------
Auto Run Toggle                YES      YES        YES        YES      [OK]
Cek Nomor Massal               YES      YES        YES        YES      [OK]
Reaktivasi Massal              YES      YES        YES        YES      [OK]
Restart All                    YES      YES        YES        YES      [OK]
Reset Modem (selected)         YES      YES        YES        YES      [OK]
Reset Modem (no port)          YES      YES        YES        YES      [OK]
Cek Nomor (port)               YES      YES        YES        YES      [OK]
Cek NIK (port)                 YES      YES        YES        YES      [OK]
Cari KK (port)                 YES      YES        YES        YES      [OK]
Cek Limit (port)               YES      YES        YES        YES      [OK]
Reaktivasi (port)              YES      YES        YES        YES      [OK]
------------------------------------------------------------------
Total: 11  Passed: 11  Warnings: 0
```

## Manual Test Instructions

1. Run `python gui.py`
2. **Cek Nomor Massal**: Click button → terminal shows `[COMMAND CLICK] COMMAND=mass.cek_nomor PORT=MASS` → `[COMMAND DISPATCH]` → eligible ports show `[COMMAND ENQUEUED]` → `[COMMAND RESULT] OUTCOME=enqueued`
3. **Reaktivasi Massal**: Click button → `[COMMAND CLICK] COMMAND=mass.reaktivasi` → `[COMMAND DISPATCH]` → `[COMMAND ENQUEUED]` → `[COMMAND RESULT]`
4. **Restart All**: Click button → `[COMMAND CLICK] COMMAND=restart_all` → `[COMMAND DISPATCH]` → per-port `[COMMAND ENQUEUED]` → `[COMMAND RESULT]`
5. **Reset Modem (with selection)**: Click a port row → click "Reset Modem" → `[COMMAND CLICK] COMMAND=reset_modem PORT=COMx` → `[COMMAND DISPATCH]` → `[COMMAND ENQUEUED]` → `[COMMAND RESULT]`
6. **Reset Modem (no selection)**: Don't click any port → click "Reset Modem" → `[COMMAND CLICK] COMMAND=reset_modem PORT=NONE` → `[COMMAND RESULT] OUTCOME=skipped MESSAGE=no_port_selected` → UI toast "Pilih port terlebih dahulu"
7. **Right-click Cek Nomor**: Right-click READY port → "Cek Nomor" → `[COMMAND CLICK] COMMAND=cmd.cek_nomor PORT=COMx SOURCE=context_menu` → `[COMMAND DISPATCH]` → `[COMMAND ENQUEUED]` → `[COMMAND RESULT]`
8. **Right-click on excluded port**: Right-click excluded port → "Cek Nomor" → `[COMMAND SKIPPED] REASON=excluded` → `[COMMAND RESULT] OUTCOME=skipped`
9. **Startup**: Terminal shows `[COMMAND ROUTER READY] EVENT=cmd.cek_nomor HANDLER=cek_nomor WORKFLOW=check_number SCOPE=per_port` for every route
10. **Unhandled event**: Any `cmd.*` event with no subscriber → `[COMMAND DELIVERY FAILED] STAGE=event_subscription REASON=no_subscribers`

## Trace Format Reference

```
[COMMAND ROUTER READY]   EVENT=... HANDLER=... WORKFLOW=... SCOPE=...
[COMMAND CLICK]          COMMAND_ID=N COMMAND=... PORT=... SOURCE=... THREAD=...
[COMMAND DISPATCH]       COMMAND_ID=N COMMAND=... PORT=... WORKFLOW=... SOURCE=...
[COMMAND SKIPPED]        COMMAND_ID=N PORT=... COMMAND=... REASON=...
[COMMAND ENQUEUED]       COMMAND_ID=N PORT=... WORKFLOW=...
[COMMAND RESULT]         COMMAND_ID=N PORT=... WORKFLOW=... OUTCOME=... MESSAGE=...
[COMMAND DELIVERY FAILED] EVENT=... STAGE=... REASON=...
```
