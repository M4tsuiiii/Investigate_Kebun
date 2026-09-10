# Sprint 15R — Scan Stability, Numeric Port Order & Standby UI

**Date**: 2026-09-08
**Status**: COMPLETE
**Tests**: 30 new (15R) + 40 existing (15Q) = 70; 659 full regression pass

---

## Summary

Fixed scan stability, numeric COM port ordering, active-worker re-probe prevention, candidate filter priority, and unified STANDBY UI presentation. The system now handles 65+ COM ports without PermissionError floods, scan overlap, or UI confusion.

## Changes

### Task 1: Absolute Numeric COM Order

**File**: `worker/modem_discovery.py`

Added `sort_com_ports()` utility that sorts COM port names numerically:
- COM9 before COM10, COM101 before COM122
- Works on strings, PortMetadata objects, or VerifiedPort objects
- Applied consistently in discovery pipeline, scan_once(), and port_table restore

**File**: `worker/worker_manager.py`
- `scan_once()` now uses `sort_com_ports()` instead of ad-hoc regex sort
- `_scan_with_validator()` uses `sort_com_ports()` for detected list

**File**: `worker/ui/port_table.py`
- `restore_from_cache()` now sorts ports numerically instead of alphabetically

### Task 2: Single-Flight Scan Control

**File**: `worker/worker_manager.py`

Added coalescing scan mechanism:
- `_scan_active: threading.Lock` — only one scan at a time
- `_rescan_pending: threading.Event` — pending rescan coalesced during active scan
- `[SCAN START] ID=N` — scan begins with scan ID
- `[SCAN ALREADY RUNNING]` — second scan attempt coalesced
- `[SCAN COMPLETE] ID=N DURATION=Xs WORKERS=M` — scan completes with metrics

### Task 3: Don't Re-Probe Active Workers

**File**: `worker/modem_discovery.py`

Added `filter_active_workers()`:
- Removes ports with active workers from candidate list
- `[DISCOVERY SKIPPED] PORT=COM5 REASON=already_active_worker`

**File**: `worker/worker_manager.py`
- `_scan_with_discovery()` passes `active_ports` set to `filter_active_workers()`
- Tracks `_failed_ports: Dict[str, float]` for retry cooldown

### Task 4: Candidate Filter Priority

**File**: `worker/modem_discovery.py`

Rewrote `_check_candidate()` with priority-ordered metadata matching:
1. **Priority 1**: HWID/VID:PID match for known hardware (XR21V1414/Exar/Quectel)
2. **Priority 2**: High-priority keywords (XR21V1414, Quectel)
3. **Priority 3**: Generic keywords — but "USB Serial" rejected without HWID/VID match

**File**: `app/domain/constants.py`

Added Sprint 15R constants:
- `DISCOVERY_RETRY_COOLDOWN = 30.0` — seconds before retrying a failed port
- `DISCOVERY_CANDIDATE_KEYWORDS_HIGH_PRIORITY = ["XR21V1414", "Quectel", "AT Port"]`
- `DISCOVERY_KNOWN_HWIDS = ["VID_04E2&PID_1414", "VID:PID=04E2:1414"]`
- `DISCOVERY_KNOWN_VIDS = ["04E2", "2C7C"]`

### Task 5: Preserve Fast Bounded Probing

Bounded concurrency preserved via `ThreadPoolExecutor(max_workers=4)`. Sort is applied to input (numerically sorted candidates) and output (verified ports in same order).

### Task 6: Unified STANDBY UI

**File**: `gui.py`

Changed `_on_cpin_transition()`:
- `NOT_INSERTED` → status `"STANDBY"`, display `"STANDBY"`
- `IDLE` / `STANDBY` → same visual presentation
- Internal domain state unchanged — only UI presentation

**File**: `worker/ui/port_table.py`
- Added `"standby"` status tag with same color as `"idle"` (`#F5F5F5` / `#666666`)
- Default row status changed from `"IDLE"` to `"STANDBY"`
- `_apply_row_tag()` maps both "standby" and "idle" to the same visual tag

### Task 7: Tests

**File**: `tests/test_sprint15r_scan_stability.py` — 30 tests

| Category | Tests |
|----------|-------|
| Numeric COM sort | 5 |
| Single-flight scan | 3 |
| Active-worker skip | 4 |
| Candidate filter priority | 7 |
| STANDBY UI mapping | 5 |
| Failed-ports cleanup | 2 |
| ModemDiscovery integration | 4 |

### Regression Fixes

**File**: `tests/test_sprint15g_single_source_audit.py`
- `test_not_inserted_maps_to_off` → `test_not_inserted_maps_to_standby` (checks `"NOT_INSERTED": "STANDBY"`)

**File**: `tests/test_sprint15d_cpin_recovery.py`
- `test_scan_complete_event_preserves_order` — patches `_scan_ports_raw` instead of removed `scan_once` mock target

**File**: `tests/test_sprint13_modem_compat.py`
- 4 tests updated to patch `_scan_ports_raw` instead of `scan_once` (which `_scan_with_validator` no longer calls)

**File**: `tests/test_sprint15q_discovery.py`
- `test_usb_serial_accepted` → `test_usb_serial_rejected_without_hardware_identity` (matches new filter behavior)
- Added `discover_all()` convenience method to `ModemDiscovery` for pipeline integration

## Scan Flow (After Sprint 15R)

```
_background_thread
  → _scan_active.acquire()  [single-flight]
  → _scan_with_discovery()
    → enumerate_ports()           # Windows OS enumeration
    → sort_com_ports()            # Numeric sort
    → filter_candidates()         # Priority-aware metadata filter
    → filter_active_workers()     # Skip active + retry cooldown
    → probe_concurrent()          # Bounded 4-worker AT probe
    → create_worker()             # Verified ports only
  → _scan_active.release()
  → check _rescan_pending         # Coalesced rescan if needed
```

## Remaining Issues

- Auto-run default is OFF (`worker/rules.py:18`)
- 2 pre-existing CpinRuntime thread join errors (inherited from before Sprint 15R)
