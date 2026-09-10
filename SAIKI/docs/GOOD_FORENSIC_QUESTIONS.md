# GOOD vs SAIKI — 6 Forensic Questions Answered

Answers to the final forensic questions from Sprint GOOD-FORENSIC-01.

---

## Q1: Why does GOOD feel faster?

**Answer**: 3 architectural differences + 1 timing difference.

1. **No global scan interval** — GOOD spawns workers immediately during initial scan. SAIKI waits for background scan loop (3.0s interval). Savings: ~3.0s.

2. **Fire-and-forget ATE0** — GOOD sends ATE0 and moves on (0.1s). SAIKI reads response (2.0s timeout). Savings: ~1.9s.

3. **Immediate CPIN poll** — GOOD polls CPIN immediately after ATE0. SAIKI waits for CpinRuntime thread to start (1.0s base interval). Savings: ~1.0s.

4. **Faster baud detection** — GOOD uses 1.0s timeout per probe. SAIKI uses 2.0s. Savings: ~5.1s per port.

**Total savings**: ~11.0s per port (worst case).

**Net result**: GOOD starts in ~10.3s. SAIKI starts in ~18.3s. GOOD is 78% faster.

---

## Q2: Why doesn't GOOD flap?

**Answer**: 4 conservative mechanisms prevent flapping.

1. **Confirmation poll** — GOOD sends explicit AT+CPIN? before flipping state. This catches transient errors. SAIKI flips immediately after threshold.

2. **UNKNOWN default** — GOOD returns UNKNOWN for unrecognized responses. This triggers UNKNOWN_THRESHOLD counting (3 flips to NOT_READY). SAIKI returns NOT_READY immediately.

3. **Buffer flush** — GOOD flushes serial buffer before each CPIN poll. This prevents stale data from causing false transitions. SAIKI lacks this.

4. **Status guard** — GOOD explicitly prevents CHECKING from overwriting confirmed states. SAIKI relies on GUI mapping (less explicit).

**Net result**: GOOD is more conservative. SAIKI is more aggressive. GOOD flaps less.

---

## Q3: What rules does SAIKI lack?

**Answer**: 6 critical rules missing in SAIKI.

| Rule | Description | Impact |
|------|-------------|--------|
| **HR-003** | Force retry clears all pending flags | Stale state may affect next operation |
| **HR-004** | Awaiting card cycle gates auto-run | Auto-run may fire during card removal |
| **HR-006** | Prompt recovery clears auto-run | May infinite-loop on prompt failures |
| **HR-008** | Reset clears all state + queues auto-run | Reset is incomplete clean slate |
| **Confirmation poll** | Explicit AT+CPIN? before state flip | May flip on transient errors |
| **Buffer flush** | `reset_input_buffer()` before CPIN poll | May read stale data |

**Recommendation**: Transplant these rules into SAIKI (Priority 1).

---

## Q4: What rules does GOOD lack?

**Answer**: 6 features missing in GOOD.

| Feature | Description | Impact |
|---------|-------------|--------|
| **Trigger ID tracking** | Atomic counter for deduplication | May process duplicate triggers |
| **Duplicate trigger detection** | 5s window dedup | May waste resources on duplicates |
| **Runtime audit reports** | TRIGGER OWNERSHIP + WORKFLOW RUNTIME | No visibility into trigger flow |
| **Workflow step trace** | `[STEP TRACE]` for every step | No step-level debugging |
| **Worker cancellation logging** | 5 cancel reasons tracked | No cancel reason visibility |
| **Adaptive CPIN polling** | Interval varies by state | Fixed interval (0.1s) wastes resources |

**Recommendation**: Keep these SAIKI features. They provide better observability.

---

## Q5: Is partial transplant sufficient?

**Answer**: Yes, but with caveats.

**Recommended transplants** (Priority 1):
1. Confirmation poll — Add explicit AT+CPIN? before flipping state
2. Buffer flush — Add `reset_input_buffer()` before CPIN poll
3. Reset cleanup — Clear all state + queue auto-run on reset

**Optional transplants** (Priority 2):
4. Awaiting card cycle — Gate auto-run during card cycle
5. Prompt recovery — Clear auto-run on prompt failure
6. UNKNOWN default — Return UNKNOWN for unrecognized responses

**NOT recommended**:
7. In-place reconnection — SAIKI's destroy/recreate model is cleaner (separation of concerns)
8. Inline CPIN polling — SAIKI's dedicated thread is more maintainable
9. Priority queue — SAIKI's scheduler provides equivalent functionality

**Net result**: Partial transplant (3-6 rules) is sufficient. Full transplant would regress SAIKI's architecture.

---

## Q6: Should we enable auto-run?

**Answer**: Not yet. Fix stability first.

**Current state**:
- Auto-run default is OFF (`worker/rules.py:18`)
- Sprint 15H-VERIFY proved all other steps work
- Missing stability rules (confirmation poll, buffer flush, reset cleanup) may cause issues

**Recommended sequence**:
1. Transplant Priority 1 rules (confirmation poll, buffer flush, reset cleanup)
2. Run 1000+ test iterations to verify stability
3. Enable auto-run ON by default
4. Monitor for flapping issues

**Risk**: Enabling auto-run without stability rules may cause:
- False state transitions (flapping)
- Infinite retry loops
- Stale state affecting workflows

**Net result**: Wait for stability rules, then enable auto-run.

---

## Summary: Sprint GOOD-FORENSIC-01 Findings

### Root Causes (Why GOOD Feels More Stable)

1. **Confirmation poll** — Confirms before flipping (SAIKI lacks)
2. **Buffer flush** — Prevents stale data (SAIKI lacks)
3. **UNKNOWN default** — More conservative (SAIKI uses NOT_READY)
4. **Status guard** — Explicit CHECKING prevention (SAIKI lacks)
5. **Worker thread stays alive** — Preserves state (SAIKI destroys/recreates)
6. **Reset clears all state** — Clean slate (SAIKI incomplete)

### Recommended Actions

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| **P1** | Add confirmation poll | 2h | High |
| **P1** | Add buffer flush | 1h | High |
| **P1** | Add reset cleanup | 2h | High |
| **P2** | Add awaiting card cycle | 3h | Medium |
| **P2** | Add prompt recovery | 2h | Medium |
| **P2** | Change UNKNOWN default | 1h | Medium |
| **P3** | Reduce ATE0 timeout | 0.5h | Low |
| **P3** | Reduce CpinRuntime initial delay | 0.5h | Low |
| **P3** | Reduce serial timeout | 0.5h | Low |

### Next Steps

1. Implement P1 rules (5h total)
2. Run stability tests (1000+ iterations)
3. Enable auto-run ON by default
4. Monitor for flapping issues
5. Implement P2 rules if needed
6. Implement P3 rules for performance

---

## Files Created

| File | Description |
|------|-------------|
| `docs/GOOD_FORENSIC_LIFECYCLE.md` | Complete lifecycle map + AT command inventory |
| `docs/GOOD_HIDDEN_RULES.md` | 20 hidden rules extracted from GOOD |
| `docs/GOOD_SAIKI_DELTA_MATRIX.md` | Side-by-side comparison of every behavior |
| `docs/GOOD_CPIN_FORENSIC.md` | Why GOOD feels more stable (8 root causes) |
| `docs/GOOD_STARTUP_PERFORMANCE.md` | Why GOOD starts faster (bottleneck analysis) |
| `docs/GOOD_FORENSIC_QUESTIONS.md` | Answers to 6 forensic questions |
