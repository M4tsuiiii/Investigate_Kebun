# Migration Notes

## Purpose

This document tracks the migration from the GOOD monolith to the SAIKI modular architecture.

## Migration Strategy

1. **GOOD is read-only** — Never modify files in GOOD/
2. **SAIKI is write-only** — All new code goes here
3. **Reference via docs** — BUSINESS_RULES_INDEX.md points to GOOD sources
4. **Incremental** — Fix one layer at a time per REBUILD_PLAN.md

## What Changed

### Architecture

| Aspect | GOOD Monolith | SAIKI Modular |
|--------|---------------|---------------|
| Structure | Single 2907-line file | 30+ modules |
| UI Logic | Mixed with business | Pure presentation |
| Business Rules | Inline | Consolidated in domain |
| Thread Safety | Global state + Queue | Locked state + Event Bus |
| Testing | 0 tests | 752+ tests |

### Enums

| GOOD | SAIKI | Notes |
|------|-------|-------|
| Multiple `CPinState` definitions | Single `app/domain/enums.py` | Eliminates cross-layer comparison failures |
| `"SUKSES"` vs `"SUCCESS"` | Decide one value | Currently mismatched |

### Constants

| GOOD | SAIKI | Notes |
|------|-------|-------|
| Magic numbers inline | Named constants in `WorkerConfig` | 13+ magic values eliminated |
| 3 regex duplicates | Single definition in `classifier.py` | `MSISDN_RE`, `NIK_RE` |

### Auto-Run Gate

| GOOD | SAIKI | Notes |
|------|-------|-------|
| 4 copies of same logic | Single `rules.py:should_block_auto_run()` | Maintenance nightmare eliminated |

### State Machines

| GOOD | SAIKI | Notes |
|------|-------|-------|
| `threading.Lock` | `threading.RLock` | Prevents deadlock from re-entrant callbacks |

### UI

| GOOD | SAIKI | Notes |
|------|-------|-------|
| Direct Tkinter calls from workers | Event Bus + Update Queue | Thread-safe |
| `global_settings` dict | Event-driven settings | Decoupled |

## Pending Migration Items

See `REBUILD_PLAN.md` for full checklist.

### Phase 1 (Domain)
- [ ] Consolidate enums
- [ ] Consolidate regex
- [ ] Fix state machine locks

### Phase 2 (Worker)
- [ ] Add locking to `PortWorkerState`
- [ ] Consolidate auto-run gate
- [ ] Wire CPIN monitor to worker loop

### Phase 3 (Integration)
- [ ] Create `PortWorker` in controller
- [ ] Add port scan scheduler
- [ ] Wire all event handlers

### Phase 4 (USSD/Reactivation)
- [ ] Fix identified bugs
- [ ] Implement missing logic

### Phase 5 (UI)
- [ ] License gate
- [ ] Telegram popup
- [ ] CSV import/export

## Breaking Changes

None expected — SAIKI is a clean rewrite, not a modification of GOOD.

## Rollback Plan

If SAIKI fails, GOOD remains untouched as reference. The modular code in SAIKI can be discarded without affecting GOOD.
