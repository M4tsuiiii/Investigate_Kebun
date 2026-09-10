# GOOD vs SAIKI Delta Matrix

Side-by-side comparison of every lifecycle behavior.

---

## 1. ATE0 Handling

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Command | `ATE0\r\n` | `ATE0\r\n` | Same |
| Timeout | Fire-and-forget | 2.0s read | **SAIKI reads response** |
| Delay | 0.1s | None | **GOOD has 100ms delay** |
| Error handling | None (continues) | Logged, continues | Same behavior |
| Flush | `reset_input_buffer()` | None | **GOOD flushes, SAIKI doesn't** |

**Assessment**: SAIKI is slightly better (reads response for logging). GOOD's flush may prevent stale data.

---

## 2. Serial Timeout

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Default timeout | 2.0s | 1.0s | **GOOD waits 2x longer** |
| Location | monolith:1305 | serial/adapter.py:15 | — |

**Impact**: SAIKI may timeout on slow modems that GOOD handles fine.

---

## 3. Baud Rate Detection

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Rates | [9600, 19200, 115200] | [9600, 19200, 115200] | Same |
| Retries | 2 per rate | 2 per rate | Same |
| Timeout | 1.0s read | 2.0s probe | **SAIKI 2x slower per probe** |
| Delay after AT | 0.2s | 0.05s poll | **GOOD 4x longer delay** |
| Total worst case | ~7.2s | ~12.0s | **SAIKI 67% slower** |
| Sleep on failure | 4s | None | **GOOD sleeps 4s on failure** |

**Impact**: SAIKI is slower at baud detection. GOOD's 4s sleep on failure is wasteful but safe.

---

## 4. CPIN Polling Architecture

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Threading | Inline (worker thread) | Dedicated daemon thread | **Different architecture** |
| AT command | Raw serial write | ATClient.send_command() | **SAIKI uses abstraction** |
| Read window | 3.0s | 3.0s timeout | Same |
| Poll interval | 0.1s (fixed) | 0.5-3.0s (adaptive) | **GOOD 10x faster** |
| Sleep between cycles | None (immediate loop) | 0.5-3.0s | **GOOD has no inter-cycle sleep** |
| Buffer flush | `reset_input_buffer()` before each poll | None | **GOOD flushes, SAIKI doesn't** |

**Impact**: GOOD detects CPIN changes 10x faster. SAIKI is more conservative.

---

## 5. Stabilization Logic

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| UNKNOWN_THRESHOLD | 3 | 3 | Same |
| CHECKING_THRESHOLD | 2 | 2 | Same |
| MAX_REMOVAL_CONFIRM | 2 | 2 | Same |
| UNKNOWN flip target | NOT_READY | NOT_READY | Same |
| CHECKING behavior | UI overlay only (no state flip) | Keeps READY (no flip) | Same |
| Confirmation poll | YES (explicit AT+CPIN? with 3s timeout) | NO (count-based) | **GOOD has confirmation poll** |
| READY→UNKNOWN flip | After 3 UNKNOWN + confirmation poll | After 3 UNKNOWN (no poll) | **GOOD more conservative** |
| Counter reset | On any stable state | On READY or non-READY stable | Same |

**Key difference**: GOOD sends a confirmation AT+CPIN? poll before flipping state. SAIKI relies on counts alone.

---

## 6. Worker Lifecycle

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Thread model | One thread per port (stays alive) | One thread per port (stays alive) | Same |
| Error recovery | Reconnect in-place (4s sleep) | Destroy + recreate on next scan | **Different recovery model** |
| Scan frequency | Per-port (inline) | 3.0s global scan | **SAIKI has global scan interval** |
| State preservation | Thread keeps state | Worker destroyed, state lost | **GOOD preserves state** |
| Modem offline handling | Set flag, continue thread | Destroy worker entirely | **SAIKI destroys, GOOD continues** |
| Reconnection | Inline (same thread) | Next scan cycle (3s+ delay) | **GOOD faster reconnection** |

**Impact**: GOOD's in-place reconnection is faster and preserves state. SAIKI's destroy/recreate loses state and adds scan delay.

---

## 7. Status Guard

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Implementation | `worker/status_guard.py` | None | **GOOD has status guard** |
| Blocked transitions | READY→CHECKING, NOT_INSERTED→CHECKING, PIN_REQUIRED→CHECKING | None | **SAIKI has no guard** |
| CHECKING behavior | Overlay only (never stored) | Mapped in GUI (never stored) | Same behavior, different mechanism |

**Impact**: GOOD explicitly prevents CHECKING from overwriting confirmed states. SAIKI relies on GUI mapping.

---

## 8. Prompt Recovery

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Implementation | `worker/retry.py:45-60` | None | **GOOD has prompt recovery** |
| Clears on failure | pending_auto_run, force_retry, awaiting_card_cycle | Nothing | **SAIKI lacks cleanup** |
| Max retries | 3 (PROMPT_MAX_RETRIES) | None | **SAIKI has no retry limit** |
| Retry delay | 2.0s | None | **SAIKI has no retry delay** |

**Impact**: SAIKI may infinite-loop on prompt failures. GOOD stops after 3 retries.

---

## 9. Reset Flow

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Clears force_retry | YES | NO | **GOOD clears, SAIKI doesn't** |
| Clears pending_auto_run | YES | NO | **GOOD clears, SAIKI doesn't** |
| Clears awaiting_card_cycle | YES | NO | **GOOD clears, SAIKI doesn't** |
| Clears counters | YES (all counters) | NO | **GOOD clears, SAIKI doesn't** |
| Queues auto-run | YES | NO | **GOOD queues, SAIKI doesn't** |
| Sends ATZ + CFUN | YES | YES | Same |

**Impact**: GOOD reset is a clean slate + fresh start. SAIKI reset sends commands but leaves stale state.

---

## 10. CPIN Parser

| Aspect | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| READY detection | `"READY"` in response | Same | Same |
| NOT_INSERTED | `"NOT INSERTED"` in response | Same | Same |
| PIN_REQUIRED | `"PIN"` in response | Same | Same |
| NOT_READY | `"NOT READY"` in response | Same | Same |
| UNKNOWN | `"ERROR"` or unrecognized | Returns `NOT_READY` for non-None | **Different default** |
| None response | Returns `UNKNOWN` | Returns `UNKNOWN` | Same |

**Impact**: GOOD's parser is more explicit about UNKNOWN. SAIKI treats unrecognized responses as NOT_READY.

---

## 11. AT Command Differences

| Command | GOOD Timeout | SAIKI Timeout | Delta |
|---------|-------------|---------------|-------|
| `AT\r\n` | 1.0s | 2.0s | **SAIKI 2x longer** |
| `ATE0\r\n` | None (fire-and-forget) | 2.0s | **SAIKI reads response** |
| `AT+CPIN?` | 3.0s window | 3.0s timeout | Same |
| `ATZ` | 0.2s | 5.0s | **SAIKI 25x longer** |
| `AT+CFUN=1,1` | 1.0s | 1.0s | Same |

---

## 12. Timing Constants

| Constant | GOOD | SAIKI | Delta |
|----------|------|-------|-------|
| BAUD_DETECT_DELAY | 0.2s | 0.05s | **GOOD 4x longer** |
| BAUD_READ_TIMEOUT | 1.0s | 2.0s | **SAIKI 2x longer** |
| CPIN_POLL_INTERVAL | 0.1s | 1.0s | **GOOD 10x faster** |
| CPIN_POLL_TIMEOUT | 3.0s | 3.0s | Same |
| SERIAL_TIMEOUT | 2.0s | 1.0s | **GOOD 2x longer** |
| STABILIZATION_DELAY | 0.5s | STABILIZATION_SECONDS | Varies |
| RESET_ATZ_WAIT | 0.2s | 5.0s | **SAIKI 25x longer** |
| RESET_CFUN_WAIT | 1.0s | 1.0s | Same |
| PROMPT_RETRY_DELAY | 2.0s | None | **GOOD has retry delay** |

---

## Summary: Rules Missing in Each Direction

### GOOD has, SAIKI lacks:
1. **Status Guard** (HR-007) — Blocks illegal CHECKING transitions
2. **Prompt Recovery** (HR-006) — Clears auto-run on prompt failure
3. **Reset Flow** (HR-008) — Clears all state + queues auto-run
4. **Force Retry Cleanup** (HR-003) — Clears all pending flags
5. **Awaiting Card Cycle** (HR-004) — Gates auto-run during card cycle
6. **Confirmation Poll** — Explicit AT+CPIN? before flipping state
7. **Buffer Flush** — `reset_input_buffer()` before CPIN poll
8. **Faster CPIN Poll** — 0.1s vs 1.0s interval
9. **No Inter-Cycle Sleep** — Immediate loop back
10. **Longer Serial Timeout** — 2.0s vs 1.0s

### SAIKI has, GOOD lacks:
1. **Trigger ID Tracking** — Atomic counter for deduplication
2. **Duplicate Trigger Detection** — 5s window dedup
3. **Runtime Audit Reports** — TRIGGER OWNERSHIP + WORKFLOW RUNTIME
4. **Workflow Step Trace** — `[STEP TRACE]` for every step
5. **Worker Cancellation Logging** — 5 cancel reasons tracked
6. **Adaptive CPIN Polling** — Interval varies by state
7. **Modem Validator** — Dedicated validation with retry
8. **Event-Based Architecture** — Decoupled via EventBus
9. **Clean Separation** — Engine, Queue, Policy, Scheduler, Runner
10. **JSON Config Persistence** — Settings saved to disk
