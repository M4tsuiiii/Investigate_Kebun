# Rebuild Plan

## Phase 0: Foundation (Current)

- [x] Create workspace structure
- [x] Documentation index
- [x] Architecture design

## Phase 1: Domain Layer

Priority: CRITICAL — eliminates duplicate enums and consolidates rules.

### 1.1 Consolidate Enums
- [ ] Single `CPinState` in `app/domain/enums.py`
- [ ] Single `CardStatus` in `app/domain/enums.py`
- [ ] Single `BusinessOutcome` — decide `"SUKSES"` vs `"SUCCESS"`
- [ ] Single `FailureCode` in `app/domain/enums.py`
- [ ] Remove duplicates from `worker/config.py`

### 1.2 Consolidate Constants
- [ ] Single `MSISDN_RE` in `app/domain/classifier.py`
- [ ] Single `NIK_RE` in `app/domain/classifier.py`
- [ ] Remove duplicates from `rules.py`, `models.py`
- [ ] Move magic numbers to named constants

### 1.3 Fix State Machines
- [ ] Change `threading.Lock` → `threading.RLock` in all state machines
- [ ] Copy listener list before invoking callbacks
- [ ] Add `snapshot()` implementations if needed

### 1.4 Fix Rules
- [ ] `resolve_kk_source()` — return `LOCAL_DB`/`TELEGRAM` when appropriate
- [ ] `should_skip_injection()` — respect `bypass_aktif`/`bypass_tenggang` params
- [ ] `evaluate_business_outcome()` — add `"TENGGANG"` to exclusion set

## Phase 2: Worker Layer

Priority: HIGH — fixes thread safety and integrates components.

### 2.1 Fix PortWorkerState
- [ ] Add `threading.Lock` to all `consume_*()` methods
- [ ] Make `increment_unknown()` atomic
- [ ] Fix TOCTOU in `consume_auto_run()`, `consume_single_action()`, etc.

### 2.2 Consolidate Auto-Run Gate
- [ ] Keep only `rules.py:should_block_auto_run()`
- [ ] Remove duplicates from `cpin_sm.py`, `cpin.py`, `autorun.py`
- [ ] Wire `AutoRunQueue.check_gate()` to use `rules.py`

### 2.3 Wire Components
- [ ] `CPINMonitor.process_cpin_response()` called from worker loop
- [ ] `ResetManager.execute_reset()` wired to serial port
- [ ] `RetryManager.handle_prompt_recovery()` integrated
- [ ] `StatusGuard.should_accept_update()` used by controller

## Phase 3: Integration Layer

Priority: HIGH — connects UI to workers.

### 3.1 PortWorker Creation
- [ ] `_apply_scan_results()` creates `PortWorker` instances
- [ ] Worker starts with `threading.Thread(daemon=True)`
- [ ] Worker receives `update_callback` for UI updates

### 3.2 Port Scan Scheduler
- [ ] `after(3000, _port_monitor_tick)` in `MainWindow.create()`
- [ ] Background thread enumerates COM ports
- [ ] Results published via `SCAN_COMPLETE` event

### 3.3 Tab-Switch Restore
- [ ] `restore_port_table()` called on tab switch
- [ ] Draws from `_port_registry` cache

### 3.4 Controller Integration
- [ ] `_handle_scan_complete()` creates workers
- [ ] `_handle_restart_all()` sets `force_retry` on real workers
- [ ] `_handle_reset_modem()` calls `request_modem_reset()` on real workers

## Phase 4: USSD/Reactivation Fixes

Priority: MEDIUM — fixes bugs in existing modules.

### 4.1 Fix Bugs
- [ ] `reader.py:209` — `.ussd_class.name` instead of `.classification.name`
- [ ] `full_flow.py:292` — None check before `.provisional.is_waiting`
- [ ] `full_flow.py:186` — enum comparison instead of string
- [ ] `session.py:148` — remove dead `quiet_start` variable
- [ ] `is_ussd_payload_complete` — use full `PROMPT_KEYWORDS` list

### 4.2 Fix Incomplete Logic
- [ ] `full_flow.py` — implement `require_card_cycle()` call
- [ ] `full_flow.py:196` — use 4-format date parser (from `verification.py`)
- [ ] Remove late import at `full_flow.py:184`

## Phase 5: UI Polish

Priority: LOW — completes feature parity.

### 5.1 Missing Features
- [ ] License verification gate
- [ ] Telegram credentials popup
- [ ] CSV import/export
- [ ] Per-port rotating file loggers
- [ ] 100-entry log cap

### 5.2 Cleanup
- [ ] Remove 42 dead code items (see AUDIT_REPORT.md Part 4)
- [ ] Remove unused event names from `events.py`
- [ ] Remove unused methods from worker modules

## Phase 6: Testing

Priority: HIGH — validates all fixes.

### 6.1 Unit Tests
- [ ] Domain layer tests (enums, models, rules, state machines)
- [ ] Worker layer tests (config, cpin, autorun, retry, reset)
- [ ] USSD engine tests (classification, cooldown, session, reader)
- [ ] Reactivation engine tests (classifier, outcome, flows)
- [ ] UI layer tests (event bus, update queue, controller)

### 6.2 Integration Tests
- [ ] Worker lifecycle (start/stop/reset)
- [ ] CPIN state machine transitions
- [ ] Auto-run queue processing
- [ ] Full reactivation flow

### 6.3 Hardware Tests
- [ ] Serial port communication
- [ ] USSD dialing and response parsing
- [ ] Multi-port concurrent operation

## Success Criteria

| Criterion | Target |
|-----------|--------|
| All BR rules implemented | 26/26 |
| All HR rules implemented | 21/21 |
| Thread safety issues | 0 critical |
| Deadlock risk | 0 |
| Duplicate code | 0 |
| Test coverage | >80% |
| Functional parity with monolith | 100% |
