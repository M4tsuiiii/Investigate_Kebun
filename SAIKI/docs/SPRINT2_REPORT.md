# Sprint 2 Report — Automation Stability

**Date**: 2026-08-29
**Status**: COMPLETE
**Tests**: 137 new (334 total across Sprint 1 + 2)

---

## Files Created

### New Modules

| File | Lines | Purpose |
|------|-------|---------|
| `worker/rules.py` | 112 | AutoRunConfig (DD-014) + should_block_auto_run gate |
| `worker/cleanup.py` | 130 | CleanupManager + StepExecutor (DD-015, DD-019) |
| `worker/hardware_restart.py` | 140 | HardwareRestart flow (DD-013) |

### Modified Files

| File | Change |
|------|--------|
| `worker/port_worker.py` | Rewritten: modem monitoring, step execution, hardware restart integration |
| `worker/worker_manager.py` | Updated: accepts AutoRunConfig, passes to PortWorker |
| `worker/modem_monitor.py` | Rewritten: AT-based modem/SIM detection, register/unregister |
| `worker/ui/events.py` | Added: AUTO_RUN_CHANGED (UIEvent), AUTO_RUN_TOGGLE (CommandEvent) |
| `worker/ui/controller.py` | Rewritten: AutoRunConfig integration, modem event routing |

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_rules.py` | 22 | AutoRunConfig, gate logic, all block conditions |
| `tests/test_cleanup.py` | 19 | Session cleanup, step execution, cooldown |
| `tests/test_hardware_restart.py` | 20 | Restart flow, SIM detection, evaluation |
| `tests/test_port_worker_sprint2.py` | 25 | Modem integration, tick branches, step execution |
| `tests/test_modem_monitor_sprint2.py` | 28 | AT detection, SIM tracking, online/offline |
| `tests/test_controller_sprint2.py` | 23 | Auto-run toggle, modem events, routing |
| **TOTAL NEW** | **137** | |

---

## Design Decisions Implemented

| Decision | Implementation | File |
|----------|---------------|------|
| DD-013 Single Hardware Restart | `HardwareRestart.execute_full_restart()` → restart → wait online → detect SIM → evaluate | `hardware_restart.py` |
| DD-014 Global Auto Run Toggle | `AutoRunConfig` with thread-safe toggle, `should_block_auto_run()` gate | `rules.py` |
| DD-015 Step-Based Automation | `StepExecutor.execute()` → send → receive → cleanup → cooldown → next | `cleanup.py` |
| DD-018 Modem Monitoring | `ModemMonitor` AT-based detection, `PortWorker.set_modem_online()` | `modem_monitor.py`, `port_worker.py` |
| DD-019 Cooldown Discipline | `CleanupManager.full_cleanup()` after every step | `cleanup.py` |

---

## Architecture Changes

### PortWorker Tick Priority (HR-002)

```
_tick()
  │
  ├── Modem offline? → sleep, return
  │
  ├── 1. Reset? → HardwareRestart.execute_full_restart()
  │                → wait online → detect SIM
  │                → evaluate: automation or standby
  │
  ├── 2. Single action? → StepExecutor.execute()
  │
  ├── 3. Force retry? → StepExecutor.execute("cek_nomor")
  │
  └── 4. Auto-run? → should_block_auto_run() gate
                      → if not blocked: execute_auto_run()
                      → step-by-step with cleanup
```

### Hardware Restart Flow (DD-013)

```
restart_modem()
  │
  ├── send ATZ
  ├── wait STABILIZATION_SECONDS (15s)
  │
  ▼
wait_online()
  │
  ├── poll AT every 1s
  ├── timeout: 30s
  │
  ▼
detect_sim()
  │
  ├── send AT+CPIN?
  ├── parse response → CpinState
  │
  ▼
evaluate_post_restart()
  │
  ├── offline → "standby"
  ├── NOT_INSERTED → "standby"
  ├── PIN_REQUIRED → "standby"
  ├── READY + auto_run OFF → "standby"
  └── READY + auto_run ON → "automation"
```

### Cleanup Discipline (DD-015)

```
execute(command)
  │
  ├── 1. Send command (AT or USSD)
  ├── 2. Receive response
  ├── 3. Close session (AT+CUSD=2)
  ├── 4. Clear buffer (reset_input/output_buffer)
  ├── 5. Cooldown (DIAL_COOLDOWN_SECONDS = 4.0s)
  │
  ▼
  return response
```

### Modem Monitoring Integration (DD-018)

```
ModemMonitor (background thread, 5s interval)
  │
  ├── check_ports() → COM appear/disappear events
  ├── check_modem_online() → AT command → True/False
  ├── check_sim_state() → AT+CPIN? → CpinState
  │
  ├── online changed? → mark_online/mark_offline
  │                      → EventBus "modem.online"/"modem.offline"
  │                      → PortWorker.set_modem_online()
  │
  └── SIM changed? → EventBus "modem.sim_changed"
```

---

## Auto-Run Gate Logic

`should_block_auto_run(snapshot, config)` checks in order:

| Check | Block If | Reason |
|-------|----------|--------|
| 1. Global toggle | `config.auto_run_enabled == False` | DD-014 |
| 2. Modem offline | `snapshot["modem_online"] == False` | DD-018 |
| 3. SIM not inserted | `cpin_state == NOT_INSERTED` | — |
| 4. SIM needs PIN | `cpin_state == PIN_REQUIRED` | — |
| 5. Card cycle pending | `awaiting_card_cycle == True` | HR-004 |
| 6. Unknown threshold | `unknown_failure_count >= 3` | HR-019 |

If none block → auto-run proceeds.

---

## Thread Safety

| Component | Lock Type | Protects |
|-----------|-----------|----------|
| AutoRunConfig | `threading.Lock` | `_auto_run_enabled` toggle |
| PortWorkerState | `threading.RLock` | All state fields |
| ModemMonitor | `threading.RLock` | `_known_ports`, `_online_ports`, `_sim_states` |
| WorkerManager | `threading.RLock` | `_workers` registry |
| EventBus | `threading.Lock` | `_subscribers` dict |

**Deadlock prevention**: EventBus never called while holding PortWorkerState lock (§10.2).

---

## Unresolved Issues

| Issue | Priority | Reason |
|-------|----------|--------|
| Real serial port adapter | HIGH | `app/infrastructure/serial/` not implemented — needs real hardware |
| USSD engine integration | HIGH | `StepExecutor.execute()` uses placeholder — needs USSD classification |
| Database adapter | MEDIUM | `app/infrastructure/database/` not implemented |
| main.py wiring | HIGH | Still skeleton — needs full initialization |
| UI widgets | MEDIUM | No Tkinter widgets yet — needs Phase 4 |

---

## What Works Now

1. **Global auto-run toggle** — Single toggle, thread-safe, affects all ports
2. **Step-based automation** — send → receive → cleanup → cooldown → next
3. **Modem monitoring** — AT-based online/offline detection, SIM state tracking
4. **Hardware restart** — restart → wait online → detect SIM → evaluate → automation/standby
5. **Cleanup discipline** — Every command: close session → clear buffer → cooldown
6. **Worker state** — RLock on all mutations, atomic consume_* methods
7. **Event-driven** — All UI communication via EventBus
8. **137 new tests** — All passing

---

## Next Sprint (Sprint 3)

### Goals
- Implement infrastructure adapters (serial, database)
- Wire PortWorker to real modem communication
- Implement USSD engine (classification, session fence, cooldown)
- Implement reactivation flow
- Complete main.py wiring
