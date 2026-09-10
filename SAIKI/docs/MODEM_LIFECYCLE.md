# SAIKI — Modem Lifecycle Specification

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## 1. Lifecycle States

```
                    ┌──────────────┐
                    │  NOT_PRESENT │
                    └──────┬───────┘
                           │ USB plugged in
                           ↓
                    ┌──────────────┐
                    │  DISCOVERED  │ ← ModemDiscovery.enumerate_ports()
                    └──────┬───────┘
                           │ candidate filter
                           ↓
                    ┌──────────────┐
                    │  PROBING     │ ← probe_port() sends AT\r\n
                    └──────┬───────┘
                           │ OK response
                           ↓
                    ┌──────────────┐
                    │ VALID_MODEM  │ ← baud rate detected
                    └──────┬───────┘
                           │ create_worker()
                           ↓
┌─────────────────────────────────────────────────────────┐
│                     ACTIVE                              │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  IDLE    │───→│ RUNNING  │───→│ STANDBY  │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│       ↑                               │                │
│       └───────────────────────────────┘                │
│                                                         │
│  PortWorker: owns serial, AT client, CPIN, USSD        │
│  CpinRuntime: polls AT+CPIN? every 1-3s                │
└─────────────┬───────────────────────────┬───────────────┘
              │                           │
              │ USB unplugged             │ User excludes
              ↓                           ↓
       ┌──────────┐               ┌──────────┐
       │ OFFLINE  │               │ EXCLUDED │
       └──────────┘               └──────────┘
              │                           │
              │ revalidation              │ User includes
              ↓                           ↓
       ┌──────────┐               ┌──────────┐
       │DISCOVERED│               │  ACTIVE  │
       └──────────┘               └──────────┘
```

---

## 2. Discovery Phase

### 2.1 Port Enumeration
- `ModemDiscovery.enumerate_ports()` calls `serial.tools.list_ports.comports()`
- Collects: port_name, description, manufacturer, vid, pid, hwid
- Returns unsorted list

### 2.2 Candidate Filtering (Priority-Based)
1. **Priority 1**: HWID/VID match for known hardware (`VID_04E2&PID_1414`, `VID:PID=04E2:1414`)
2. **Priority 2**: High-priority keywords: `XR21V1414`, `Quectel`, `AT Port`
3. **Priority 3**: Generic keywords — but "USB Serial" rejected without HWID/VID match

### 2.3 Active Worker Filtering
- Skip ports already in `active_ports`
- Skip ports in `failed_ports` within 30s cooldown (`DISCOVERY_RETRY_COOLDOWN`)

### 2.4 Probing
- Opens serial at 115200 baud (`DISCOVERY_BAUD_RATE`)
- Sends `AT\r\n`
- Waits up to 2s (`DISCOVERY_PROBE_TIMEOUT`)
- Requires explicit "OK" in response
- Max 4 concurrent probes (`DISCOVERY_MAX_CONCURRENT`)

### 2.5 Handoff
- Verified ports passed to `WorkerManager.create_worker()`
- Baud rate cached for future reconnections

---

## 3. Registration Phase

### 3.1 Worker Creation
```
WorkerManager.create_worker(port_id)
  → SerialAdapter(port_id, baud_rate)
  → ATClient(serial)
  → PortWorker(port_id, event_bus, auto_run_config, baud_rate)
  → worker.connect(serial, at_client)
    → ATE0 (disable echo)
    → CpinRuntime.start() [polling begins]
  → worker.start()
  → port_states[port_id] = ACTIVE
```

### 3.2 Initial State
- CPIN state: UNKNOWN
- Modem online: True (just validated)
- Auto-run: pending (if enabled)

---

## 4. Validation Phase

### 4.1 AT Validation
- `ATE0` sent during `connect()` to disable echo
- If ATE0 fails → port may not be a real modem

### 4.2 CPIN Validation
- CpinRuntime polls `AT+CPIN?` every 1-3s
- First poll determines initial SIM state
- Confirmation polls prevent false transitions

### 4.3 Baud Rate Detection
- Primary: 115200 (Quectel M26 default)
- Fallback: 9600, 19200 (if `fallback_baud_enabled`)
- Detected baud cached per port

---

## 5. Monitoring Phase

### 5.1 CpinRuntime Polling
- Normal interval: 1.0s
- Stable (READY): 3.0s
- Transitional (NOT_READY): 0.5s
- Buffer flush before every query
- Confirmation polls for state transitions

### 5.2 Port Worker Tick
- Checks modem_online flag
- Consumes pending actions (reset, single_action, force_retry, auto_run)
- Checks `should_block_auto_run()` before auto-run

### 5.3 Modem Offline Detection
- Exception in tick loop → `modem.offline` event
- WorkerManager destroys worker
- Port goes back to discovery scan

---

## 6. Workflow Execution Phase

### 6.1 Trigger Sources
| Source | Trigger | Action |
|--------|---------|--------|
| CpinRuntime | CPIN_READY | Auto-run (if enabled) |
| CpinRuntime | SIM_INSERTED | Enqueue workflow |
| User button | USER_MASS_CHECK_NUMBER | Enqueue check_data |
| User button | USER_MASS_REACTIVATION | Enqueue reactivate_full |
| User context menu | Per-port command | Enqueue specific workflow |
| User button | RESTART_ALL | hardware_restart on all |
| User button | RESET_MODEM | hardware_reset on selected |

### 6.2 Scheduler Evaluation
- MODEM_ONLINE → enqueue
- MODEM_OFFLINE → cancel
- SIM_INSERTED → enqueue (if idle/standby)
- CPIN_READY → enqueue (if idle/standby)
- WORKFLOW_SUCCESS → standby
- WORKFLOW_FAILED → no action

### 6.3 Queue Processing
- Max 2 concurrent workflows
- Priority: user commands (5) > auto-run (10) > retry (5)
- Duplicate detection: same port+trigger within 5s

---

## 7. Reset Phase

### 7.1 Hardware Reset Sequence
1. Stop CpinRuntime (pause polling)
2. Close serial connection
3. Wait 15s (`STABILIZATION_SECONDS`)
4. Reopen serial connection
5. Start CpinRuntime (resume polling)
6. Check modem (AT)
7. Detect SIM (AT+CPIN?)

### 7.2 State Recovery
- After reset, CpinRuntime detects new SIM state
- If READY + auto-run enabled → auto-run queued
- If NOT_READY → standby

---

## 8. Removal Phase

### 8.1 USB Unplug
- Exception in tick → `modem.offline` event
- WorkerManager destroys worker
- Port removed from active list
- Port re-enters discovery scan

### 8.2 User Exclusion
- `exclude_port()` → ACTIVE → EXCLUDED
- Queued workflows cancelled
- Automation skipped

### 8.3 User Inclusion
- `include_port()` → EXCLUDED → ACTIVE
- Port rejoins automation
