# Known Limitations

**Date**: 2026-08-29
**Workspace**: SAIKI
**Sprint**: 4 — Hardening & Future Ready

---

## 1. Hardware Limitations

### 1.1 No Real Serial Communication

**Limitation**: All modem interaction uses `Any` type. No PySerial adapter exists.

**Impact**: Cannot communicate with real GSM modems. All AT commands, USSD dials, and SIM detection are placeholders.

**Workaround**: None — requires implementation of `app/infrastructure/serial/`.

**Files affected**:
- `worker/port_worker.py` — `set_modem()` takes `Any`
- `worker/cleanup.py` — `StepExecutor` calls `modem.send_at/send_ussd` on `Any`
- `worker/hardware_restart.py` — calls `modem.send_at` on `Any`
- `worker/modem_monitor.py` — `check_modem_online/send_at` on `Any`

### 1.2 No Baud Rate Detection

**Limitation**: `PortWorkerState.set_current_baud()` exists but baud detection logic is not implemented.

**Impact**: Cannot auto-detect modem baud rate. Must be configured manually.

**Workaround**: Hardcode baud rate in configuration.

### 1.3 No Multi-Baud Scanning

**Limitation**: `DEFAULT_BAUD_RATES = [115200, 9600, 57600, 38400, 19200, 4800]` defined but not used.

**Impact**: Port scanner only detects COM ports, not their baud rates.

---

## 2. Business Rule Limitations

### 2.1 BR-003: NIK Lookup Not Wired

**Limitation**: NIK lookup flow (cache → USSD) is defined in `reactivation_retry.py` but not wired to `PortWorker._execute_step()`.

**Impact**: NIK is never actually fetched from the modem during auto-run.

**Workaround**: NIK must be pre-populated in the database.

### 2.2 BR-004: KK Source Resolution Incomplete

**Limitation**: `resolve_kk_source()` not implemented. KK lookup has three tiers (NIK=KK, local DB, Telegram) but only local DB works.

**Impact**: If NIK is not in NIK&NIK mode and not in local DB, KK lookup fails.

**Workaround**: Ensure all cards are pre-populated in the database.

### 2.3 BR-009: Grace Date Change Detection Missing

**Limitation**: No code compares grace dates before/after injection to determine success.

**Impact**: Reactivation success cannot be automatically determined.

**Workaround**: Manual verification required.

### 2.4 BR-027: Status Guard Not Enforced

**Limitation**: `StatusGuard` pattern exists in GOOD but not wired in SAIKI controller.

**Impact**: Invalid status transitions may occur (e.g., READY → SUKSES without going through BUSY).

### 2.5 HR-009: Removal Confirmation Not Enforced

**Limitation**: `_removal_confirmation_count` tracked but never incremented. `CPIN_MAX_REMOVAL_CONFIRM` not checked.

**Impact**: SIM removal confirmation flow is not properly gated.

### 2.6 HR-014: Grace Date Parsing Limited

**Limitation**: Only 2 date formats supported (ISO `YYYY-MM-DD` and local `DD-MM-YYYY`). Monolith supports 4.

**Impact**: Some carrier responses may use unsupported date formats.

### 2.7 HR-015: Injection Concurrency Not Limited

**Limitation**: `MAX_CONCURRENT_INJECTIONS = 2` defined but never enforced.

**Impact**: More than 2 concurrent injections may overwhelm the modem.

---

## 3. Architecture Limitations

### 3.1 No Integration Tests

**Limitation**: All tests are unit tests. No integration tests verify component interaction.

**Impact**: Bugs in component wiring may go undetected.

**Workaround**: Manual testing required.

### 3.2 No Hardware Tests

**Limitation**: No tests with real serial ports or modems.

**Impact**: Hardware-specific issues (timing, response parsing) cannot be caught in CI.

### 3.3 Duplicate Port Scanning

**Limitation**: Both `ModemMonitor._check_ports()` and `WorkerManager._scan_and_update()` scan COM ports independently.

**Impact**: Two competing scanners may create race conditions or duplicate workers.

**Workaround**: Only one scanner should be active. Currently both run.

### 3.4 No UI Widgets

**Limitation**: Event-driven UI architecture exists but no Tkinter widgets are implemented.

**Impact**: No graphical user interface.

### 3.5 `main.py` Not Wired

**Limitation**: Entry point is a skeleton with TODO comments.

**Impact**: Application cannot be started.

---

## 4. Recovery Limitations

### 4.1 No Worker Watchdog

**Limitation**: If a worker thread dies, no one detects or restarts it.

**Impact**: Dead workers remain in the registry as zombie entries.

**Workaround**: Manual restart via UI (which doesn't exist yet).

### 4.2 No Auto-Run Re-Queue

**Limitation**: If auto-run is interrupted (modem offline), `pending_auto_run` is already consumed. No re-queue happens.

**Impact**: Auto-run stops permanently until external re-trigger.

**Workaround**: User must manually re-trigger auto-run.

### 4.3 No DB Reconnection

**Limitation**: `DbLookup` creates a single connection. If it drops, all lookups silently fail forever.

**Impact**: Permanent database failure after first error.

**Workaround**: Restart the application.

### 4.4 No Port Validity Check

**Limitation**: After COM port disappears, the serial port object may become stale. No validity check before operations.

**Impact**: Operations on stale port may raise exceptions.

**Workaround**: Exception handling catches the error, but the port reference is not cleaned up.

---

## 5. Telegram Gateway Limitations

### 5.1 Not Implemented

**Limitation**: Telegram gateway is a stub. `_telegram_query()` returns hardcoded "DATA_TIDAK_DITEMUKAN".

**Impact**: KK lookup via Telegram never works.

**Workaround**: Use NIK=KK mode or local database.

### 5.2 Two Competing Interfaces

**Limitation**: `domain.ports.TelegramPort` (4 methods) and `worker.reactivation.ports.TelegramPort` (2 methods) define different interfaces.

**Impact**: Confusion about which interface to implement.

### 5.3 Credentials Not Persisted

**Limitation**: Telegram API credentials are in-memory only. Lost on restart.

**Impact**: Must re-enter credentials after every restart.

---

## 6. Deployment Limitations

### 6.1 No Packaging

**Limitation**: No `setup.py`, `pyproject.toml`, or installer.

**Impact**: Cannot be installed as a package.

### 6.2 No Configuration Migration

**Limitation**: `configs/default.ini` exists but no migration logic for version upgrades.

**Impact**: Configuration may break on upgrades.

### 6.3 No Logging Rotation

**Limitation**: `max_entries_per_port = 100` defined but no rotating file logger implemented.

**Impact**: Logs may grow unbounded in production.

---

## 7. Testing Limitations

### 7.1 No Thread Safety Tests for Some Components

**Limitation**: `CleanupManager`, `UIController`, `HardwareRestart` lack thread safety tests.

**Impact**: Race conditions in these components may go undetected.

### 7.2 No Edge Case Tests

**Limitation**: Several edge cases untested:
- WorkerManager `scan_once` with `ImportError`
- PortWorker fallback paths when components are `None`
- DB lookup with corrupt database
- Mass action with worker=None

### 7.3 No End-to-End Tests

**Limitation**: No test exercises the full flow from UI command to worker execution to EventBus update.

**Impact**: Integration bugs may go undetected.

---

## 8. Summary

| Category | Limitations | Severity |
|----------|-------------|----------|
| Hardware | 3 | CRITICAL |
| Business Rules | 7 | HIGH |
| Architecture | 5 | HIGH |
| Recovery | 4 | MEDIUM |
| Telegram | 3 | LOW |
| Deployment | 3 | MEDIUM |
| Testing | 3 | MEDIUM |
| **Total** | **28** | |

**Top 5 Must-Fix**:
1. Serial port adapter (CRITICAL)
2. USSD engine integration (CRITICAL)
3. BR-009 grace date detection (HIGH)
4. HR-015 injection concurrency limit (HIGH)
5. Worker watchdog (HIGH)
