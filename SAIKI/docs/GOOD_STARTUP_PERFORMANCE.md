# GOOD Startup Performance Forensics

Analysis of why GOOD starts faster than SAIKI.

---

## Startup Comparison

### GOOD Startup Sequence

```
T0.000  Scan COM ports
T0.001  Sort COM (numeric)
T0.002  Spawn PortWorker per port (thread starts)
T0.003  PortWorker: Detect baud [9600, 19200, 115200]
        ├─ Try 9600: AT\r\n → wait 0.2s → read 1.0s → OK/FAIL
        ├─ Try 9600 again: AT\r\n → wait 0.2s → read 1.0s → OK/FAIL
        ├─ Try 19200: AT\r\n → wait 0.2s → read 1.0s → OK/FAIL
        ├─ Try 19200 again: AT\r\n → wait 0.2s → read 1.0s → OK/FAIL
        ├─ Try 115200: AT\r\n → wait 0.2s → read 1.0s → OK/FAIL
        └─ Try 115200 again: AT\r\n → wait 0.2s → read 1.0s → OK/FAIL
        Worst case: 6 × 1.2s = 7.2s
T7.202  Open serial (timeout=2)
T7.203  Send ATE0 (0.1s delay, fire-and-forget)
T7.303  Enter main loop
T7.304  CPIN poll (3.0s window, 0.1s poll)
T10.304 First CPIN response
T10.305 State transition + UI update
```

**Total: ~10.3s per port (worst case)**

### SAIKI Startup Sequence

```
T0.000  Scan COM ports (serial.tools.list_ports.comports())
T0.001  Sort COM (numeric)
T0.002  Initial scan complete
T0.003  Start background scan loop (3.0s interval)
T3.003  First scan cycle
T3.004  Validate modem (per port)
        ├─ Try 9600: AT\r\n → wait 0.05s poll → read 2.0s → OK/FAIL
        ├─ Try 9600 again: AT\r\n → wait 0.05s poll → read 2.0s → OK/FAIL
        ├─ Try 19200: AT\r\n → wait 0.05s poll → read 2.0s → OK/FAIL
        ├─ Try 19200 again: AT\r\n → wait 0.05s poll → read 2.0s → OK/FAIL
        ├─ Try 115200: AT\r\n → wait 0.05s poll → read 2.0s → OK/FAIL
        └─ Try 115200 again: AT\r\n → wait 0.05s poll → read 2.0s → OK/FAIL
        Worst case: 6 × 2.05s = 12.3s
T15.304 Create worker + inject dependencies
T15.305 Connect (ATE0 + CpinRuntime start)
T15.306 ATE0 sent (timeout=2.0)
T17.306 CpinRuntime starts polling
T18.306 First CPIN response (1.0s base interval)
T18.307 State transition + UI update
```

**Total: ~18.3s per port (worst case)**

---

## Performance Breakdown

### Phase 1: Baud Rate Detection

| Metric | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Timeout per probe | 1.0s | 2.0s | SAIKI 2x slower |
| Delay after AT | 0.2s | 0.05s | GOOD 4x slower |
| Poll interval | None | 0.05s | SAIKI has extra polling |
| Retries per rate | 2 | 2 | Same |
| Total per rate | 1.2s | 2.05s | SAIKI 71% slower |
| Total worst case | 7.2s | 12.3s | SAIKI 71% slower |

**Root cause**: SAIKI uses 2.0s timeout (vs GOOD's 1.0s) + 0.05s poll interval.

### Phase 2: Serial Connection

| Metric | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Serial timeout | 2.0s | 1.0s | GOOD 2x longer |
| Connection time | ~0.1s | ~0.1s | Same |

**Root cause**: GOOD's longer timeout (2.0s) is more tolerant but doesn't affect startup time.

### Phase 3: ATE0

| Metric | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| Delay | 0.1s | None | GOOD 100ms slower |
| Response read | No | Yes (2.0s timeout) | SAIKI 2.0s slower |
| Total | 0.1s | 2.0s | SAIKI 19x slower |

**Root cause**: SAIKI reads ATE0 response (2.0s timeout). GOOD is fire-and-forget.

### Phase 4: CPIN First Response

| Metric | GOOD | SAIKI | Delta |
|--------|------|-------|-------|
| First poll delay | 0s (immediate) | 1.0s (base interval) | SAIKI 1.0s slower |
| Read window | 3.0s | 3.0s timeout | Same |
| Total | 3.0s | 4.0s | SAIKI 33% slower |

**Root cause**: SAIKI's CpinRuntime has 1.0s base interval before first poll. GOOD polls immediately.

---

## Total Startup Time Comparison

| Scenario | GOOD | SAIKI | Delta |
|----------|------|-------|-------|
| Best case (1 port, fast modem) | ~3.3s | ~5.3s | SAIKI 61% slower |
| Worst case (1 port, slow modem) | ~10.3s | ~18.3s | SAIKI 78% slower |
| 10 ports (parallel) | ~10.3s | ~18.3s | SAIKI 78% slower |

**Note**: Both GOOD and SAIKI process ports in parallel (one thread per port). The difference is per-port startup time.

---

## Why GOOD Feels Faster

### 1. No Global Scan Interval

GOOD spawns workers immediately during initial scan. SAIKI waits for background scan loop (3.0s interval).

```
GOOD: Scan → Spawn workers → Done
SAIKI: Scan → Wait 3s → Scan again → Validate → Spawn workers
```

### 2. Fire-and-Forget ATE0

GOOD sends ATE0 and moves on. SAIKI reads response (2.0s timeout).

```
GOOD: ATE0 → 0.1s → Continue
SAIKI: ATE0 → Wait 2.0s → Continue
```

### 3. Immediate CPIN Poll

GOOD polls CPIN immediately after ATE0. SAIKI waits for CpinRuntime thread to start (1.0s base interval).

```
GOOD: ATE0 → CPIN poll (immediate) → 3.0s window → Done
SAIKI: ATE0 → CpinRuntime start → Wait 1.0s → CPIN poll → 3.0s timeout → Done
```

### 4. No Worker Recreation Overhead

GOOD keeps threads alive and reconnects in-place. SAIKI destroys and recreates workers.

```
GOOD: Thread stays alive → Reconnect (4s sleep) → Continue
SAIKI: Destroy worker → Wait for scan → Validate → Create new worker → Start
```

---

## SAIKI Optimization Opportunities

### Quick Wins (< 1 hour)

1. **Reduce ATE0 timeout** — Change from 2.0s to 0.5s (saves 1.5s)
2. **Reduce CpinRuntime initial delay** — Start polling immediately (saves 1.0s)
3. **Reduce serial timeout** — Change from 1.0s to 0.5s (saves 0.5s per baud probe)

**Total savings: ~3.0s**

### Medium Effort (1-4 hours)

4. **Add buffer flush** — `reset_input_buffer()` before CPIN poll (prevents stale data)
5. **Add confirmation poll** — Explicit AT+CPIN? before state flip (more conservative)
6. **Add worker state preservation** — Keep state on worker destroy/recreate

### Significant Effort (4+ hours)

7. **In-place reconnection** — Keep thread alive, reconnect on error (like GOOD)
8. **Inline CPIN polling** — Move CPIN poll back to worker thread (like GOOD)
9. **Priority queue** — Add GOOD's priority ordering for pending actions

---

## Startup Bottleneck Analysis

```
GOOD bottlenecks:
├─ Baud detection: 7.2s (67% of startup)
├─ CPIN first response: 3.0s (28% of startup)
└─ ATE0: 0.1s (5% of startup)

SAIKI bottlenecks:
├─ Baud detection: 12.3s (67% of startup)
├─ ATE0 response: 2.0s (11% of startup)
├─ CPIN first response: 4.0s (22% of startup)
└─ Scan interval: 3.0s (16% of startup, if applicable)
```

**Key insight**: Baud detection is the #1 bottleneck for both. SAIKI's 2.0s timeout (vs GOOD's 1.0s) makes it 71% slower.

---

## Recommendation

### Immediate (Sprint 16)
1. Reduce ATE0 timeout from 2.0s to 0.5s
2. Reduce CpinRuntime initial delay to 0s (start immediately)
3. Reduce serial timeout from 1.0s to 0.5s

### Short-term (Sprint 17)
4. Add buffer flush before CPIN poll
5. Add confirmation poll before state flip
6. Add worker state preservation

### Long-term (Sprint 18+)
7. Consider in-place reconnection (like GOOD)
8. Consider inline CPIN polling (like GOOD)
9. Consider priority queue (like GOOD)
