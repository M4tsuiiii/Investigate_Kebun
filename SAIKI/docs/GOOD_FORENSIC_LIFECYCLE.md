# GOOD Forensic Lifecycle — Complete Reverse Engineering

## Startup Timeline

### GOOD (Monolith — kebun_reaktivasi(rev).py)

```
T0  Scan COM         serial.tools.list_ports.comports()
    File: kebun_reaktivasi(rev).py (implicit in PortWorker spawn)
    Delay: 0ms
    Note: Workers spawned per-port, each does own scan

T1  Detect Baud      for baud in [9600, 19200, 115200]
    File: kebun_reaktivasi(rev).py:1282-1294
    Delay: 0.2s after AT write
    Timeout: 1s read (serial.Serial timeout=1)
    Retry: continues to next baud on failure
    Sleep on total failure: 4s (line 1301)

T2  Open Serial      serial.Serial(port, baud, timeout=2)
    File: kebun_reaktivasi(rev).py:1305
    Timeout: 2s read
    Note: timeout=2 (longer than SAIKI's 1)

T3  Send ATE0        ser.write(b"ATE0\r\n")
    File: kebun_reaktivasi(rev).py:1306-1308
    Delay: 0.1s (100ms)
    Flush: ser.reset_input_buffer()
    Response: NOT read (fire-and-forget)
    Error handling: none (assumed accepted)

T4  Enter Inner Loop while self.is_running:
    File: kebun_reaktivasi(rev).py:1310
    Priority checks: reset > single_action > force_retry > pending_auto_run

T5  CPIN Poll        ser.write(b"AT+CPIN?\r\n")
    File: kebun_reaktivasi(rev).py:1333-1341
    Read window: 3.0s (end_time = time.time() + 3.0)
    Poll interval: 0.1s (time.sleep(0.1))
    Read method: ser.read(ser.in_waiting)
    Decode: utf-8, errors="ignore"

T6  Parse Response   _extract_cpin_state(raw)
    File: kebun_reaktivasi(rev).py:1131-1144
    States: READY, NOT_READY, PIN_REQUIRED, NOT_INSERTED, UNKNOWN
    Method: regex matching

T7  Apply Rules      Inline decision tree (lines 1346-1471)
    See: Hidden Rules section below

T8  State Transition _handle_cpin_transition(old, new, ser)
    File: kebun_reaktivasi(rev).py:1263-1267
    Updates: cpin_state, port_registry, emits event

T9  Loop Back        → T5 (immediate, no sleep between polls)
```

### SAIKI (Modular — worker/ + automation/)

```
T0  Scan COM         serial.tools.list_ports.comports()
    File: worker_manager.py:173-182
    Delay: 0ms
    Interval: 3.0s between scans

T1  Sort COM         sorted(raw, key=lambda x: int(re.search(r'\d+', x).group()))
    File: worker_manager.py:171
    Method: Numeric sort (COM3, COM4, COM104)

T2  Validate Modem   ModemValidator.validate(port_id, serial_factory)
    File: modem_validator.py
    Baud rates: [9600, 19200, 115200] (slowest first)
    Timeout: 2.0s per baud probe
    Retries: 2 per baud rate
    AT command: AT\r\n, check for "OK"
    Worst case: 3 × 2 × 2.0s = 12.0s

T3  Create Worker    PortWorker(port_id, event_bus, auto_run_config)
    File: worker_manager.py:307
    Note: Worker object created before hardware injection

T4  Inject Deps      SerialAdapter + ATClient
    File: worker_manager.py:325-354
    Serial: SerialAdapter(port_id, baud_rate, timeout=1)
    AT: ATClient(serial_adapter)

T5  Connect          worker.connect(serial_adapter, at_client)
    File: port_worker.py:102+
    Creates: CleanupManager, CpinRuntime, UssdRuntime
    Sends: ATE0 (timeout=2.0, non-blocking)
    Starts: CpinRuntime.start() (daemon thread)

T6  CPIN Poll        CpinRuntime._poll_once()
    File: cpin_runtime.py:84-133
    AT command: AT+CPIN? via at_client.send_command()
    Timeout: CPIN_POLL_TIMEOUT = 3.0s
    Base interval: CPIN_POLL_INTERVAL = 1.0s
    Adaptive: READY→3.0s, NOT_READY→0.5s, other→1.0s
    Thread: Dedicated daemon thread per port

T7  Stabilize        _apply_stabilization(previous, raw_state)
    File: cpin_runtime.py:135-216
    Rules: 6 cases (see Stabilization section)

T8  Publish          event_bus.publish("cpin.transition", {...})
    File: cpin_runtime.py:125-129
    Trigger: Only on actual state change

T9  Workflow         AutomationEngine.handle_trigger()
    File: engine.py:99+
    Gating: auto_run, port_excluded, scheduler
```

## AT Command Inventory

### GOOD

| Command | Where | Timeout | Delay | Response |
|---------|-------|---------|-------|----------|
| `AT\r\n` | monolith:1286 | 1s read | 0.2s | Check for "OK" |
| `ATE0\r\n` | monolith:1306 | none | 0.1s | Not read |
| `AT+CPIN?\r\n` | monolith:1334 | 3s window | 0.1s poll | Parsed |
| `ATZ` | monolith:1091 | 0.2s | - | Not validated |
| `AT+CFUN=1,1` | monolith:1095 | 1.0s | - | Not validated |

### SAIKI

| Command | Where | Timeout | Delay | Response |
|---------|-------|---------|-------|----------|
| `AT\r\n` | modem_validator | 2.0s | 0.05s poll | Check for "OK" |
| `ATE0\r\n` | port_worker.py | 2.0s | none | Logged, continues on fail |
| `AT+CPIN?\r\n` | cpin_runtime.py | 3.0s | 1.0s interval | Parsed + stabilized |
| `ATZ` | hardware_restart.py | 5.0s | 15.0s wait | Checked after wait |
| `AT+CFUN=1,1` | hardware_restart.py | 1.0s | - | Not validated |

## CPIN Polling Architecture

### GOOD: Inline Polling

```
PortWorker.run() [single thread per port]
  └─ while is_running:
       ├─ Priority checks (reset, single, force, auto)
       ├─ ser.reset_input_buffer()
       ├─ ser.write(b"AT+CPIN?\r\n")
       ├─ Read loop: 3.0s window, 0.1s poll
       ├─ Parse response
       ├─ Apply decision tree (lines 1346-1471)
       ├─ State transition (if changed)
       └─ Loop back immediately (NO sleep between polls)
```

**Key characteristics:**
- No dedicated thread for CPIN (shares worker thread)
- 3.0s read window per poll
- 0.1s poll interval within window
- **No sleep between poll cycles** (immediate loop back)
- Decision tree is inline (not separated)

### SAIKI: Dedicated Thread Polling

```
PortWorker._tick() [worker thread]
  └─ while running:
       ├─ Check modem_online
       ├─ Priority checks
       └─ Idle sleep 0.1s

CpinRuntime._poll_loop() [separate daemon thread]
  └─ while running:
       ├─ _poll_once()
       │   ├─ at_client.send_command("AT+CPIN?", timeout=3.0)
       │   ├─ parse_cpin_response()
       │   └─ _apply_stabilization()
       └─ time.sleep(self._poll_interval)  # 0.5s - 3.0s
```

**Key characteristics:**
- Dedicated daemon thread for CPIN
- AT command via ATClient (not raw serial)
- 3.0s timeout per command
- Sleep between polls (0.5s - 3.0s adaptive)
- Stabilization layer separates raw from reported state

## State Transition Rules

### GOOD Decision Tree (monolith lines 1346-1471)

```python
# Line 1346-1349: READY→READY — reset all counters
if old == "READY" and new == "READY":
    unknown_failure_count = 0
    pending_removal_confirmation = False
    removal_confirmation_count = 0

# Line 1352-1357: READY→NOT_READY — start removal confirmation
if old == "READY" and new == "NOT_READY":
    if not pending_removal_confirmation:
        pending_removal_confirmation = True
        removal_confirmation_count = 0
        clear_card_fields()

# Line 1360-1413: READY→UNKNOWN — threshold-based
if old == "READY" and new == "UNKNOWN":
    unknown_failure_count += 1
    if unknown_failure_count >= 3:  # CPIN_UNKNOWN_THRESHOLD
        # Send final confirmation AT+CPIN? with 3s timeout
        # Decision: NOT_INSERTED/READY/keep READY (conservative)

# Line 1416-1445: Pending removal confirmation
if pending_removal_confirmation and old == "READY":
    # Send retry AT+CPIN? with 3s timeout
    # READY → cancel removal
    # NOT_INSERTED → confirmed
    # NOT_READY → increment count, continue

# Line 1448-1453: Normalize counters
if detected_state in ("READY", "NOT_INSERTED", "PIN_REQUIRED"):
    cpin_failure_count = 0
    unknown_failure_count = 0
    pending_removal_confirmation = False
    removal_confirmation_count = 0

# Line 1463-1467: UNKNOWN from READY — CHECKING overlay
if detected_state == "UNKNOWN" and old == "READY":
    cpin_failure_count += 1
    if cpin_failure_count >= 2:  # CPIN_CHECKING_THRESHOLD
        ui_callback("CHECKING")
```

### SAIKI Stabilization Rules (cpin_runtime.py lines 135-216)

```python
# Case 1: READY→UNKNOWN
if previous == READY and raw == UNKNOWN:
    unknown_count += 1
    checking_count += 1
    if unknown_count >= 3:  # UNKNOWN_THRESHOLD
        return NOT_READY  # Flip state
    elif checking_count >= 2:  # CHECKING_THRESHOLD
        return previous  # Keep READY (no flip)
    else:
        return previous  # Keep READY (below threshold)

# Case 2: READY→NOT_INSERTED
if previous == READY and raw == NOT_INSERTED:
    removal_confirm_count += 1
    if removal_confirm_count >= 2:  # MAX_REMOVAL_CONFIRM
        return NOT_INSERTED  # Confirmed
    else:
        return previous  # Keep READY

# Case 3: Any→READY
if raw == READY and previous != READY:
    reset all counters
    return READY  # Accept immediately

# Case 4: UNKNOWN/NOT_READY→stable
if raw in (READY, NOT_INSERTED, PIN_REQUIRED):
    if previous in (UNKNOWN, NOT_READY):
        reset all counters
        return raw

# Case 5: Same state
if raw == previous:
    return raw

# Case 6: Other transitions
reset all counters
return raw
```
