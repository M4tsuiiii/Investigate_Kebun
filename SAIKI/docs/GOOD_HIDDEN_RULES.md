# GOOD Hidden Rules — Reverse-Engineered Control Logic

Extracted from monolith (`kebun_reaktivasi(rev).py`) + `worker/` modules.
All line references below point to the GOOD workspace.

---

## HR-001: Priority Queue Ordering

**Source**: `worker/autorun.py:50-56`, monolith:1311-1330
**Mechanism**: `_pending_actions` dict, processed by priority

```
Priority ORDER (highest to lowest):
  1. reset_requested        (monolith:1311)
  2. single_action          (monolith:1318)
  3. force_retry            (monolith:1323)
  4. pending_auto_run       (monolith:1326)
  5. cpin_poll              (monolith:1328)
```

**Impact**: Reset always wins. Auto-run queued while force_retry pending will not execute until force_retry completes. This prevents conflicting operations on the same port.

**SAIKI equivalent**: `automation/queue.py` — `Priority` enum (RESET=10, SINGLE_ACTION=20, FORCE_RETRY=30, AUTO_RUN=40, CPIN_POLL=50). Same ordering.

---

## HR-002: Force Retry Bypasses Normal Gate

**Source**: `worker/autorun.py:98-111`, monolith:1323-1324
**Mechanism**: `force_retry = True` overrides `awaiting_card_cycle` and `pending_auto_run` checks

```python
# autorun.py line 98-99
if state.force_retry:
    return AutoRunGateResult(allowed=True, reason="force_retry bypass")
```

**Impact**: Force retry can trigger on ports that are in intermediate states (awaiting card cycle, pending auto-run). This is intentional — force retry is a user override.

**SAIKI equivalent**: `worker/port_worker.py:101+` — `force_retry()` method directly calls `_run_automation()`, bypassing all gate checks.

---

## HR-003: Force Retry Clears All Pending Flags

**Source**: `worker/autorun.py:143-157`, monolith:1324-1325
**Mechanism**: When force_retry executes, it clears `force_retry`, `pending_auto_run`, `awaiting_card_cycle`, and `pending_removal_confirmation`

```python
# autorun.py line 143-148
def _execute_force_retry(self, port_name):
    state = self._get_port_state(port_name)
    state.force_retry = False
    state.pending_auto_run = False
    state.awaiting_card_cycle = False
    state.pending_removal_confirmation = False
    self._run_automation(port_name)
```

**Impact**: Force retry is a clean slate — no stale state left behind.

**SAIKI equivalent**: `worker/port_worker.py:101+` — `force_retry()` calls `_run_automation()` but does NOT clear any flags. **Missing rule.**

---

## HR-004: Awaiting Card Cycle Gate

**Source**: `worker/autorun.py:86-88`, `worker/card_cycle.py`
**Mechanism**: `awaiting_card_cycle` flag set during CPIN transition READY→NOT_READY/UNKNOWN. Blocks auto-run until card cycle completes.

```python
# autorun.py line 86-88
if state.awaiting_card_cycle:
    result.reason = "awaiting_card_cycle is True"
    return result  # blocked
```

**Card cycle detection** (`card_cycle.py`):
- Set when CPIN transitions from READY to non-READY
- Cleared when CPIN returns to READY or NOT_INSERTED
- Purpose: Prevents auto-run during SIM removal/reinsertion

**Impact**: Without this gate, auto-run could fire during card removal, causing wasted workflow attempts.

**SAIKI equivalent**: Not present. SAIKI lacks `awaiting_card_cycle` flag entirely.

---

## HR-005: Pending Auto-Run Flag

**Source**: `worker/autorun.py:101-102`, monolith:1147-1150
**Mechanism**: `pending_auto_run = True` set when CPIN transitions to READY. Gate checks this flag to prevent duplicate auto-runs.

```python
# autorun.py line 101-102
if state.pending_auto_run:
    result.reason = "pending_auto_run is True"
    return result  # blocked
```

**Impact**: Prevents multiple auto-runs from queuing on the same port.

**SAIKI equivalent**: Not present. SAIKI uses scheduler enqueue/dequeue, which provides equivalent deduplication via queue state.

---

## HR-006: Prompt Recovery Clears Auto-Run

**Source**: `worker/retry.py:45-60`, monolith:1416-1420
**Mechanism**: When CPIN check fails to return READY (timeout or not_ready), `pending_auto_run` is cleared. Prompt must be re-issued by user.

```python
# retry.py line 45-50
def _handle_prompt_failure(self, port_name):
    state = self._get_port_state(port_name)
    state.pending_auto_run = False
    state.force_retry = False
    state.awaiting_card_cycle = False
    self._log(f"{port_name}: Prompt failure — auto-run cleared")
```

**Impact**: Prevents endless retry loops when SIM is stuck or unresponsive. User must manually re-trigger.

**SAIKI equivalent**: `worker/port_worker.py` — On modem offline event, `_stop_cpin_runtime()` is called, which does NOT clear any flags. **Missing rule.**

---

## HR-007: Status Guard — Block Illegal Transitions

**Source**: `worker/status_guard.py:1-80`
**Mechanism**: `StatusGuard` prevents status transitions that don't make sense

```python
# status_guard.py line 30-45
ILLEGAL_TRANSITIONS = {
    ("READY", "CHECKING"),      # READY should never become CHECKING
    ("NOT_INSERTED", "CHECKING"),  # NOT_INSERTED should never become CHECKING
    ("PIN_REQUIRED", "CHECKING"),  # PIN_REQUIRED should never become CHECKING
}

def is_transition_allowed(self, old_status, new_status):
    if (old_status, new_status) in ILLEGAL_TRANSITIONS:
        return False
    return True
```

**Impact**: CHECKING is a temporary overlay, not a real status. Prevents CHECKING from overwriting a confirmed status.

**SAIKI equivalent**: Not present. SAIKI has no status guard.

---

## HR-008: Reset Flow — Clear + Queue Auto-Run

**Source**: `worker/reset.py:1-60`, monolith:1091-1100
**Mechanism**: Reset clears all pending state AND queues auto-run

```python
# reset.py line 20-35
def _execute_reset(self, port_name):
    state = self._get_port_state(port_name)
    state.force_retry = False
    state.pending_auto_run = False
    state.awaiting_card_cycle = False
    state.pending_removal_confirmation = False
    state.unknown_failure_count = 0
    state.cpin_failure_count = 0
    # Queue auto-run after reset completes
    self._queue_auto_run(port_name)
```

**Impact**: Reset is a clean slate + fresh start. All counters cleared, auto-run queued.

**SAIKI equivalent**: `worker/port_worker.py:101+` — `force_retry()` clears nothing, queues nothing. **Missing rule.**

---

## HR-009: CPIN Transition Guard — No Self-Transition

**Source**: monolith:1263-1267
**Mechanism**: `_handle_cpin_transition` only fires when `old != new`

```python
# monolith line 1263-1264
def _handle_cpin_transition(self, old_state, new_state, ser):
    if old_state == new_state:
        return  # no-op
```

**Impact**: Prevents redundant state updates and event publishing.

**SAIKI equivalent**: `cpin_runtime.py:125` — `event_bus.publish("cpin.transition", ...)` only called when `reported_state != self._previous_state`. Same guard.

---

## HR-010: Reset Sends ATZ + CFUN

**Source**: `worker/reset.py:30-40`, monolith:1091-1100
**Mechanism**: Reset sends ATZ (0.2s wait) then AT+CFUN=1,1 (1.0s wait)

```python
# reset.py line 30-40
def _execute_reset(self, port_name):
    ser = self._get_serial(port_name)
    ser.write(b"ATZ\r\n")
    time.sleep(0.2)
    ser.read(ser.in_waiting)
    ser.write(b"AT+CFUN=1,1\r\n")
    time.sleep(1.0)
    ser.read(ser.in_waiting)
```

**Impact**: ATZ resets modem to defaults. CFUN=1,1 resets radio. Combined, this forces a fresh SIM registration.

**SAIKI equivalent**: `worker/hardware_restart.py:48-60` — Same sequence, but uses ATClient (not raw serial).

---

## HR-011: Single Action Override

**Source**: `worker/autorun.py:113-126`, monolith:1318-1320
**Mechanism**: Manual trigger (single_action) bypasses auto-run gate

```python
# autorun.py line 113-118
def queue_single_action(self, port_name, action):
    task = AutoRunTask(
        port_name=port_name,
        priority=Priority.SINGLE_ACTION,  # 20 (higher than auto-run 40)
        action=action,
    )
```

**Impact**: User-triggered actions always execute, regardless of auto-run state.

**SAIKI equivalent**: `worker/port_worker.py:101+` — `force_retry()` serves as single action.

---

## HR-012: CHECKING Overlay — 2-Threshold Model

**Source**: monolith:1463-1467
**Mechanism**: Two separate counters for UNKNOWN and CHECKING

```python
# monolith line 1463-1467
if detected_state == "UNKNOWN" and self.cpin_state == "READY":
    cpin_failure_count += 1
    if cpin_failure_count >= 2:  # CPIN_CHECKING_THRESHOLD
        ui_callback("CHECKING")
    # Note: unknown_failure_count is separate (line 1362)
```

**Thresholds**:
- `CPIN_UNKNOWN_THRESHOLD = 3` → flips state to NOT_READY
- `CPIN_CHECKING_THRESHOLD = 2` → shows CHECKING overlay

**Impact**: CHECKING appears BEFORE the state actually flips. This is a visual warning, not a status change.

**SAIKI equivalent**: `cpin_runtime.py:135-216` — Uses same thresholds but different logic. UNKNOWN_THRESHOLD=3 flips state, CHECKING_THRESHOLD=2 keeps READY. **Different behavior.**

---

## HR-013: READY→UNKNOWN Conservative Preservation

**Source**: monolith:1360-1413
**Mechanism**: When READY transitions to UNKNOWN, the system is conservative — keeps READY until threshold exceeded

```python
# monolith line 1380-1390
if unknown_failure_count >= 3:
    # Send final confirmation AT+CPIN? with 3s timeout
    # If response is NOT_INSERTED → confirmed removal
    # If response is READY → keep READY (conservative)
    # If response is NOT_READY → keep READY (conservative)
    # Only if response is UNKNOWN → flip to NOT_READY
```

**Impact**: 3 consecutive UNKNOWN responses required before flipping state. This prevents false positives from transient communication errors.

**SAIKI equivalent**: `cpin_runtime.py:145-165` — After 3 UNKNOWN, returns NOT_READY. No confirmation poll. **Missing confirmation step.**

---

## HR-014: Removal Confirmation — 2-Step Verification

**Source**: monolith:1416-1445
**Mechanism**: Removal requires 2 consecutive confirmation polls

```python
# monolith line 1416-1425
if pending_removal_confirmation and self.cpin_state == "READY":
    # Send retry AT+CPIN? with 3s timeout
    # If response is READY → cancel removal (false alarm)
    # If response is NOT_INSERTED → confirmed
    # If response is NOT_READY → increment count, continue
    # If count >= 2 → confirmed
```

**Impact**: SIM removal requires 2 confirmations. Prevents false removal from transient errors.

**SAIKI equivalent**: `cpin_runtime.py:160-180` — Uses `removal_confirm_count` with MAX_REMOVAL_CONFIRM=2. Same logic but no explicit confirmation poll. **Missing confirmation step.**

---

## HR-015: CHECKING Overlay Never Overwrites READY

**Source**: monolith:1463-1467, status_guard.py
**Mechanism**: CHECKING is only shown in UI, never stored as actual status

```python
# monolith line 1463-1467
if detected_state == "UNKNOWN" and self.cpin_state == "READY":
    cpin_failure_count += 1
    if cpin_failure_count >= 2:
        ui_callback("CHECKING")  # UI only
    # Actual status remains READY
```

**Impact**: READY is preserved until explicit flip. CHECKING is a visual warning only.

**SAIKI equivalent**: `gui.py:350-370` — `_on_cpin_transition` maps states to UI strings. CHECKING is shown but not stored. Same behavior.

---

## HR-016: Counter Reset on Stable State

**Source**: monolith:1448-1453
**Mechanism**: All counters reset when CPIN returns to any stable state

```python
# monolith line 1448-1453
if detected_state in ("READY", "NOT_INSERTED", "PIN_REQUIRED"):
    cpin_failure_count = 0
    unknown_failure_count = 0
    pending_removal_confirmation = False
    removal_confirmation_count = 0
```

**Impact**: Any stable state clears all intermediate tracking. Clean slate for next transition.

**SAIKI equivalent**: `cpin_runtime.py:190-216` — Reset on READY or non-READY stable. Same behavior.

---

## HR-017: AT Command Response Reading

**Source**: monolith:1306-1308
**Mechanism**: ATE0 response NOT read (fire-and-forget)

```python
# monolith line 1306-1308
ser.write(b"ATE0\r\n")
time.sleep(0.1)
ser.reset_input_buffer()
# No ser.read() — response ignored
```

**Impact**: ATE0 may not be accepted by all modems. Continuing without confirmation is risky but faster.

**SAIKI equivalent**: `port_worker.py:108-115` — ATE0 sent, response read (timeout=2.0), logged but not validated. Continues on failure. Same behavior.

---

## HR-018: Baud Rate Detection — 2 Retries

**Source**: `worker/config.py:15-20`, monolith:1282-1294
**Mechanism**: Each baud rate tried with 2 retries

```python
# config.py line 15-20
BAUD_RATES = [9600, 19200, 115200]
BAUD_DETECT_RETRIES = 2
BAUD_DETECT_DELAY = 0.2  # seconds after AT write
BAUD_READ_TIMEOUT = 1.0  # seconds to wait for response
```

**Impact**: 3 rates × 2 retries = 6 attempts. Each takes ~1.2s. Total worst case: ~7.2s.

**SAIKI equivalent**: `modem_validator.py` — 3 rates, 2 retries, 2.0s timeout. Total worst case: ~12.0s. **SAIKI is 67% slower.**

---

## HR-019: Serial Timeout Difference

**Source**: monolith:1305 vs SAIKI worker_manager.py:336
**Mechanism**: GOOD uses timeout=2, SAIKI uses timeout=1

```python
# GOOD monolith line 1305
ser = serial.Serial(self.port_name, baud, timeout=2)

# SAIKI worker_manager.py line 336
serial_adapter = self._serial_factory(port_id, baud_rate)  # timeout=1
```

**Impact**: GOOD waits 2s for each read, SAIKI waits 1s. GOOD is more tolerant of slow modems.

**SAIKI equivalent**: `serial/adapter.py:15` — `DEFAULT_TIMEOUT = 1.0`. **1s shorter than GOOD.**

---

## HR-020: CPIN Poll Interval Difference

**Source**: monolith:1341 vs SAIKI cpin_runtime.py:84
**Mechanism**: GOOD polls every 0.1s, SAIKI polls every 1.0s (base)

```python
# GOOD monolith line 1341
time.sleep(0.1)  # 100ms between polls

# SAIKI cpin_runtime.py line 84
time.sleep(self._poll_interval)  # 1.0s base (adaptive: 0.5-3.0s)
```

**Impact**: GOOD is 10x faster at detecting CPIN changes. SAIKI is more conservative (less spam).

**SAIKI equivalent**: Adaptive intervals: READY→3.0s, NOT_READY→0.5s, other→1.0s.
