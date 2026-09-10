# Sprint 15R.1 — Workspace Table Order & Idle Display Finalization

**Date**: 2026-09-08
**Status**: COMPLETE
**Tests**: 32 new (15R.1) + 28 existing (15R) + 40 existing (15Q) = 100; 539 full regression pass

---

## Summary

Fixed the Workspace port table to always display numeric COM ordering and unified neutral states to IDLE with RESPON = "-". No scanner/discovery/probe code was changed.

## Root Cause of Prior Unsorted Display

Sprint 15R added `sort_com_ports()` to discovery, but the visible Treeview remained unordered because:

1. Parallel discovery/UI events arrive in arbitrary order
2. New rows use `tree.insert("", tk.END)` — appends at end
3. `update_cell()` inserts missing rows at `END`
4. `_render_home()` iterates `_port_data.items()` — dict insertion order is arbitrary
5. `_drain_events()` applies updates in arrival order
6. No reordering step after any of these operations

## Changes

### Task 1: Final Treeview Numeric Sort

**File**: `worker/ui/port_table.py`

Added `_reorder_treeview()` method:
- Sorts all Treeview items by numeric COM port number
- Uses `tree.move(item, "", index)` — non-destructive reorder
- Preserves row values, tags, selection, scroll position
- Called after every mutation: `insert_row()`, `update_cell()` (when inserting missing row), `restore_from_cache()`

### Task 2: Sort Cache Render Path

**File**: `worker/ui/main_window.py`

Replaced `for port, data in self._port_data.items():` with `for port in sorted(self._port_data.keys(), key=_num_key):`. Workspace tab now sorts numerically before any rows are inserted.

### Task 3: Neutral UI State = IDLE

**File**: `worker/ui/port_table.py`

Added `_normalize_status()` and `_normalize_respon()` static methods. Added `_NEUTRAL_STATUSES` frozenset:
```python
_NEUTRAL_STATUSES = frozenset({
    "IDLE", "STANDBY", "NOT_INSERTED", "NOT_READY",
    "UNKNOWN", "CHECKING", "OFF",
})
```

All neutral/non-operational states → display as `IDLE`. READY, PROCESSING, SUCCESS, FAILED, and connection errors retain their existing presentation.

**File**: `gui.py`

Updated `_on_cpin_transition()` to use `_NEUTRAL_CPIN` set:
- READY → `port_status = "READY"`, `display_text = "SIM Inserted"`
- All other CPIN states → `port_status = "IDLE"`, `display_text = "-"`

### Task 4: Default RESPON = -

**File**: `worker/ui/port_table.py`

`DEFAULT_ROW` changed from `["...", "STANDBY", "Idle/Standby", ...]` to `["...", "IDLE", "-", ...]`. All neutral states return `"-"` for RESPON via `_normalize_respon()`.

**File**: `worker/ui/main_window.py`

`_render_home()` uses `_normalize_respon()` to set RESPON = "-" for neutral states.

### Task 5: No Scanner Regression

Verified unchanged:
- `worker/modem_discovery.py` — no changes
- `worker/worker_manager.py` — no changes
- `app/domain/constants.py` — no changes
- 40 Sprint 15Q tests pass
- 28 Sprint 15R tests pass

### Task 6: Tests

**File**: `tests/test_sprint15r1_table_finalization.py` — 32 tests

| Category | Tests |
|----------|-------|
| COM numeric order | 4 |
| Arbitrary insertion order | 2 |
| Parallel update order | 2 |
| update_cell missing row | 2 |
| Workspace tab rebuild | 2 |
| Delete row | 2 |
| Filter preserves order | 1 |
| Selection + LOG identity | 2 |
| Neutral state mapping | 7 |
| READY/workflow display | 5 |
| Domain eligibility | 3 |

### Regression Fixes

**File**: `tests/test_sprint15g_single_source_audit.py`
- `test_gui_on_cpin_transition_writes_checking` → `test_gui_on_cpin_transition_writes_idle`
- `test_ready_written_by_cpin_transition_handler` — updated to check for both `"READY"` and `"IDLE"`
- `test_root_cause_b_status_hardcoded_fixed` — updated to check `port_status = "READY"` and `"IDLE"`
- `test_not_inserted_maps_to_standby` → `test_not_inserted_maps_to_idle`
- `test_pin_required_maps_to_checking` → `test_pin_required_maps_to_idle`

**File**: `tests/test_sprint15r_scan_stability.py`
- `test_port_table_default_row_is_standby` → `test_port_table_default_row_is_idle`
- `test_port_table_standby_color_matches_idle` → `test_port_table_default_respon_is_dash`
- `TestStandbyUI` → `TestNeutralUI` with updated assertions

## UI State Mapping Table

| CPIN State | STATUS (display) | RESPON (display) | Visual Tag |
|------------|-----------------|-----------------|------------|
| READY | READY | SIM Inserted | proces (blue) |
| NOT_INSERTED | IDLE | - | idle (gray) |
| NOT_READY | IDLE | - | idle (gray) |
| UNKNOWN | IDLE | - | idle (gray) |
| PIN_REQUIRED | IDLE | - | idle (gray) |
| STANDBY | IDLE | - | idle (gray) |
| IDLE | IDLE | - | idle (gray) |
| OFF | IDLE | - | idle (gray) |

## Visual Acceptance

Expected Workspace table order:
```
COM101
COM102
COM103
...
COM132
...
COM149
...
COM164
```

Expected neutral rows:
```
STATUS = IDLE
RESPON = -
```

No `STANDBY`, `Idle/Standby`, `SIM Not Ready`, or `SIM Not Inserted` text appears in the Workspace table.

## Scan/Discovery Unchanged

The following files were NOT modified in Sprint 15R.1:
- `worker/modem_discovery.py`
- `worker/worker_manager.py`
- `app/domain/constants.py`
- `worker/port_worker.py`
- `worker/cpin_runtime.py`
- `worker/system_bootstrap.py`
