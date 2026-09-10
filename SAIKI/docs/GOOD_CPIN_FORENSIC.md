# GOOD CPIN Stability Forensics

Deep analysis of why GOOD feels more stable than SAIKI.

---

## Root Cause #1: Confirmation Poll Before State Flip

### GOOD Behavior (monolith:1360-1413)

```
READY → UNKNOWN (1st time)
  unknown_failure_count = 1
  → No action, keep READY

READY → UNKNOWN (2nd time)
  unknown_failure_count = 2
  → No action, keep READY

READY → UNKNOWN (3rd time)
  unknown_failure_count = 3 (threshold reached)
  → Send confirmation AT+CPIN? with 3s timeout
  → If response is READY: keep READY (conservative)
  → If response is NOT_READY: keep READY (conservative)
  → If response is NOT_INSERTED: flip to NOT_INSERTED
  → If response is UNKNOWN: flip to NOT_READY
```

### SAIKI Behavior (cpin_runtime.py:145-165)

```
READY → UNKNOWN (1st time)
  unknown_count = 1, checking_count = 1
  → Keep READY

READY → UNKNOWN (2nd time)
  unknown_count = 2, checking_count = 2
  → Keep READY (CHECKING_THRESHOLD=2, show CHECKING)

READY → UNKNOWN (3rd time)
  unknown_count = 3 (threshold reached)
  → Flip to NOT_READY (NO confirmation poll)
```

### Impact

GOOD sends a **confirmation AT+CPIN?** before flipping. This catches:
- Transient communication errors (3rd UNKNOWN was noise)
- Modem recovery (3rd UNKNOWN happened during reboot)
- False positives (line noise, USB disconnect)

SAIKI flips immediately after 3 UNKNOWN. No confirmation. This is faster but less safe.

**Verdict**: GOOD is more stable because it confirms before flipping. SAIKI may flip on transient errors.

---

## Root Cause #2: Buffer Flush Before Each Poll

### GOOD Behavior (monolith:1333-1335)

```python
ser.reset_input_buffer()  # Flush stale data
ser.write(b"AT+CPIN?\r\n")
# ... read response
```

### SAIKI Behavior (cpin_runtime.py:84-133)

```python
response = self._at_client.send_command("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
# No buffer flush
```

### Impact

Buffer flush prevents:
- Stale data from previous poll affecting current response
- Partial responses being parsed as complete
- Cross-talk between AT commands

Without flush, SAIKI may read stale data from previous poll. This can cause:
- False UNKNOWN responses (partial data)
- False READY responses (stale READY from previous poll)
- Intermittent parse failures

**Verdict**: GOOD's flush prevents stale data issues. SAIKI lacks this.

---

## Root Cause #3: Faster Poll Interval

### GOOD Behavior (monolith:1341)

```python
time.sleep(0.1)  # 100ms between polls
```

### SAIKI Behavior (cpin_runtime.py:84)

```python
time.sleep(self._poll_interval)  # 0.5-3.0s (adaptive)
```

### Impact

GOOD polls 10x faster (0.1s vs 1.0s base). This means:
- Faster detection of CPIN changes
- Faster response to SIM insertion/removal
- More data points for stabilization (3 UNKNOWN in 0.3s vs 3.0s)

SAIKI's adaptive intervals (0.5-3.0s) are slower but use fewer resources.

**Verdict**: GOOD is faster at detecting changes. SAIKI is more resource-efficient.

---

## Root Cause #4: No Inter-Cycle Sleep

### GOOD Behavior (monolith:1310-1471)

```python
while self.is_running:
    # ... priority checks
    # ... CPIN poll
    # ... state transition
    # Loop back immediately (NO sleep)
```

### SAIKI Behavior (cpin_runtime.py:84-133)

```python
while self._running.is_set():
    self._poll_once()
    time.sleep(self._poll_interval)  # Sleep between polls
```

### Impact

GOOD has no sleep between poll cycles. This means:
- Continuous monitoring (no gaps)
- Faster response to state changes
- Higher CPU usage

SAIKI's sleep between cycles means:
- Gaps in monitoring (0.5-3.0s)
- Lower CPU usage
- May miss rapid state changes

**Verdict**: GOOD is more responsive. SAIKI is more efficient.

---

## Root Cause #5: Status Guard Prevents CHECKING Overwrite

### GOOD Behavior (status_guard.py)

```python
ILLEGAL_TRANSITIONS = {
    ("READY", "CHECKING"),
    ("NOT_INSERTED", "CHECKING"),
    ("PIN_REQUIRED", "CHECKING"),
}
```

### SAIKI Behavior

No status guard. CHECKING is mapped in GUI but never stored.

### Impact

GOOD explicitly prevents CHECKING from overwriting confirmed states. This means:
- READY remains READY even during CHECKING overlay
- NOT_INSERTED remains NOT_INSERTED during CHECKING
- CHECKING is purely visual, never affects state

SAIKI's GUI mapping achieves the same effect but less explicitly.

**Verdict**: Same behavior, different mechanisms. GOOD is more explicit.

---

## Root Cause #6: Worker Thread Stays Alive

### GOOD Behavior (monolith:1269-1471)

```
PortWorker.run() [single thread]
  └─ while is_running:
       ├─ Try to connect (if not connected)
       ├─ Priority checks
       ├─ CPIN poll
       ├─ State transition
       └─ Loop back (thread stays alive)
```

### SAIKI Behavior (worker_manager.py:356-369)

```
destroy_worker(port_id)
  └─ worker.disconnect()
  └─ worker.stop()
  └─ Remove from _workers dict
  └─ Publish "ui.port.removed"
```

### Impact

GOOD's thread stays alive and reconnects in-place. This means:
- State preserved (counters, flags, history)
- Faster reconnection (no scan delay)
- No worker recreation overhead

SAIKI destroys and recreates workers. This means:
- State lost (all counters reset)
- Slower reconnection (scan delay + validation)
- Worker recreation overhead

**Verdict**: GOOD's in-place reconnection is faster and preserves state.

---

## Root Cause #7: CPIN Parser Returns UNKNOWN for Unrecognized

### GOOD Behavior (monolith:1131-1144)

```python
def _extract_cpin_state(self, response):
    if "READY" in response:
        return "READY"
    elif "NOT INSERTED" in response:
        return "NOT_INSERTED"
    elif "PIN" in response:
        return "PIN_REQUIRED"
    elif "NOT READY" in response:
        return "NOT_READY"
    else:
        return "UNKNOWN"  # Unrecognized → UNKNOWN
```

### SAIKI Behavior (app/domain/classifier.py)

```python
def parse_cpin_response(response: str) -> CpinState:
    if response is None:
        return CpinState.UNKNOWN
    if "READY" in response:
        return CpinState.READY
    elif "NOT INSERTED" in response:
        return CpinState.NOT_INSERTED
    elif "PIN" in response:
        return CpinState.PIN_REQUIRED
    elif "NOT READY" in response:
        return CpinState.NOT_READY
    else:
        return CpinState.NOT_READY  # Unrecognized → NOT_READY
```

### Impact

GOOD returns UNKNOWN for unrecognized responses. This triggers:
- UNKNOWN_THRESHOLD counting (3 flips to NOT_READY)
- Confirmation poll before flip
- Conservative behavior

SAIKI returns NOT_READY for unrecognized responses. This triggers:
- Immediate NOT_READY state
- No UNKNOWN counting
- Less conservative

**Verdict**: GOOD's UNKNOWN default is more conservative. SAIKI's NOT_READY default is less safe.

---

## Root Cause #8: RESET Clears All State

### GOOD Behavior (worker/reset.py:20-35)

```python
def _execute_reset(self, port_name):
    state = self._get_port_state(port_name)
    state.force_retry = False
    state.pending_auto_run = False
    state.awaiting_card_cycle = False
    state.pending_removal_confirmation = False
    state.unknown_failure_count = 0
    state.cpin_failure_count = 0
    self._queue_auto_run(port_name)
```

### SAIKI Behavior (worker/port_worker.py:101+)

```python
def force_retry(self):
    self._run_automation()  # No state cleanup
```

### Impact

GOOD reset clears ALL state and queues auto-run. This means:
- Clean slate after reset
- No stale flags affecting next operation
- Fresh start with auto-run

SAIKI reset (force_retry) does NOT clear state. This means:
- Stale flags may affect next operation
- No auto-run queued
- State may be inconsistent

**Verdict**: GOOD's reset is a true clean slate. SAIKI's is incomplete.

---

## Summary: Why GOOD Feels More Stable

| Factor | GOOD Advantage | SAIKI Disadvantage |
|--------|---------------|-------------------|
| Confirmation poll | Confirms before flipping | Flips immediately |
| Buffer flush | Prevents stale data | May read stale data |
| Faster poll interval | 10x faster detection | Slower detection |
| No inter-cycle sleep | Continuous monitoring | Gaps in monitoring |
| Status guard | Explicit CHECKING prevention | Implicit GUI mapping |
| Worker thread stays alive | Preserves state | Loses state on destroy |
| UNKNOWN default | More conservative | Less conservative |
| Reset clears all state | Clean slate | Incomplete cleanup |

**Net result**: GOOD is more conservative, more responsive, and preserves state better. SAIKI is more efficient but less stable.

---

## Recommended Transplants for SAIKI

### Priority 1 (Critical)
1. **Confirmation poll** — Add explicit AT+CPIN? before flipping state
2. **Buffer flush** — Add `reset_input_buffer()` before CPIN poll
3. **Reset cleanup** — Clear all state + queue auto-run on reset

### Priority 2 (Important)
4. **Awaiting card cycle** — Gate auto-run during card cycle
5. **Prompt recovery** — Clear auto-run on prompt failure
6. **UNKNOWN default** — Return UNKNOWN for unrecognized responses

### Priority 3 (Nice to Have)
7. **Faster poll interval** — Reduce base interval from 1.0s to 0.5s
8. **No inter-cycle sleep** — Remove sleep between polls (or reduce to 0.1s)
9. **Status guard** — Add explicit CHECKING transition prevention
