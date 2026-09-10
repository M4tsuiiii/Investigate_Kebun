# SAIKI — Architecture Document

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────┐
│                    GUI (main_window.py)              │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │Port Table│  │Log Viewer│  │Settings Dialog    │  │
│  │(8 cols)  │  │          │  │(Modem/Workflow/DB)│  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
│         ↑ EventBus (thread-safe pub/sub)            │
├─────────┼───────────────────────────────────────────┤
│         ↓                                           │
│  ┌──────────────────────────────────────────────┐   │
│  │            UIController                       │   │
│  │  - Command routing (COMMAND_ROUTES table)     │   │
│  │  - Eligibility checks                         │   │
│  │  - Event→Workflow mapping                     │   │
│  └──────────┬────────────────────┬───────────────┘   │
│             ↓                    ↓                   │
│  ┌──────────────────┐  ┌────────────────────────┐   │
│  │  WorkerManager    │  │  AutomationEngine      │   │
│  │  - Port lifecycle │  │  - Workflow queue      │   │
│  │  - Scanning       │  │  - Scheduler           │   │
│  │  - Validation     │  │  - Policy              │   │
│  └───────┬──────────┘  └──────────┬─────────────┘   │
│          ↓                        ↓                  │
│  ┌───────────────┐  ┌───────────────────────────┐   │
│  │  PortWorker    │  │  WorkflowRunner           │   │
│  │  (per port)    │  │  - Skill resolution       │   │
│  │  - AT client   │  │  - Step execution         │   │
│  │  - CPIN runtime│  │  - Cleanup between steps  │   │
│  │  - USSD runtime│  └────────────┬──────────────┘   │
│  └───────┬────────┘               ↓                  │
│          ↓                ┌─────────────────────┐    │
│  ┌───────────────┐        │  Skills (8 total)    │    │
│  │  SerialAdapter │        │  cek_nomor           │    │
│  │  - AT client   │        │  cek_status          │    │
│  │  - Send/recv   │        │  cek_nik             │    │
│  └───────┬────────┘        │  cek_kk              │    │
│          ↓                 │  inject_reaktivasi   │    │
│  ┌───────────────┐        │  verify_grace        │    │
│  │  USB Modem     │        │  restart_hardware    │    │
│  │  (Quectel M26) │        │  reset_hardware      │    │
│  └───────────────┘        └─────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

---

## 2. Layer Descriptions

### 2.1 GUI Layer

| Component | File | Responsibility |
|-----------|------|----------------|
| `MainWindow` | `main_window.py` | Root window, tab bar, event drain loop |
| `PortStatusTable` | `port_table.py` | 8-column Treeview with numeric sorting |
| `LogViewer` | `log_viewer.py` | Per-port log display |
| `WorkerMonitor` | `worker_monitor.py` | Thread status display |
| `SettingsDialog` | `settings_dialog.py` | Configuration management |
| `PortContextMenu` | `context_menu.py` | Right-click menu per port |
| `UIHeartbeat` | `ui_heartbeat.py` | UI responsiveness watchdog |

### 2.2 Controller Layer

| Component | File | Responsibility |
|-----------|------|----------------|
| `UIController` | `controller.py` | Bridges GUI events to backend actions |

**Key data structures:**
- `COMMAND_ROUTES` — 21-entry routing table mapping events → workflows
- `PER_PORT_COMMAND_MAP` — event → workflow name mapping
- `_command_map` — command_id → {port, workflow, command} for result wiring

### 2.3 Automation Layer

| Component | File | Responsibility |
|-----------|------|----------------|
| `AutomationEngine` | `engine.py` | Workflow queue processing, trigger handling |
| `AutomationScheduler` | `scheduler.py` | Per-port state machine (IDLE/RUNNING/STANDBY/QUEUED) |
| `AutomationPolicy` | `policy.py` | Mode → workflow mapping |
| `WorkflowQueue` | `queue.py` | Priority queue with max_concurrent=2 |
| `ReactivateRetryPolicy` | `retry.py` | Max 1 retry for reactivation |
| `Trigger` | `triggers.py` | Event enum (MODEM_ONLINE, SIM_INSERTED, etc.) |

### 2.4 Workflow Layer

| Component | File | Responsibility |
|-----------|------|----------------|
| `WorkflowRunner` | `runner.py` | Executes workflows, resolves skills |
| `WorkflowRegistry` | `registry.py` | Stores workflow definitions |
| `WorkflowDefinition` | `definitions.py` | name + steps list |
| `SkillDependencyResolver` | `dependency_resolver.py` | Per-port dependency injection |

### 2.5 Skill Layer

| Skill | File | AT/USSD Commands |
|-------|------|------------------|
| `CekNomorSkill` | `cek_nomor.py` | `AT+CNUM`, USSD fallback |
| `CekStatusSkill` | `cek_status.py` | `AT+CPIN?` |
| `CekNikSkill` | `cek_nik.py` | USSD `*185#` |
| `CekKkSkill` | `cek_kk.py` | USSD `*185#` |
| `InjectReaktivasiSkill` | `inject_reaktivasi.py` | USSD `*185#` |
| `VerifyGraceSkill` | `verify_grace.py` | USSD `*185#` |
| `RestartHardwareSkill` | `restart_hardware.py` | `ATZ` |
| `ResetHardwareSkill` | `reset_hardware.py` | Serial close/reopen + `AT+CPIN?` |

### 2.6 Worker Layer

| Component | File | Responsibility |
|-----------|------|----------------|
| `PortWorker` | `port_worker.py` | Per-port runtime engine |
| `WorkerManager` | `worker_manager.py` | Port lifecycle, scanning, validation |
| `CpinRuntime` | `cpin_runtime.py` | SIM status polling with confirmation |
| `UssdRuntime` | `ussd_runtime.py` | USSD dial + cooldown |
| `HardwareRestart` | `hardware_restart.py` | ATZ restart + wait |
| `CleanupManager` | `cleanup.py` | Buffer flush, session close |
| `PortWorkerState` | `state.py` | Thread-safe mutable state |

### 2.7 Hardware Layer

| Component | File | Responsibility |
|-----------|------|----------------|
| `SerialAdapter` | (serial_adapter.py) | Serial port read/write |
| `ATClient` | (at_client.py) | AT command protocol |
| `ModemDiscovery` | `modem_discovery.py` | COM port enumeration, candidate filtering, probing |
| `ModemValidator` | `modem_validator.py` | Baud detection, AT validation |

### 2.8 Domain Layer

| Component | File | Responsibility |
|-----------|------|----------------|
| Enums | `enums.py` | CpinState, PortState, CardStatus, etc. |
| Constants | `constants.py` | Timing thresholds, baud rates, limits |
| Classifier | `classifier.py` | parse_cpin_response() |
| DbLookup | `db_lookup.py` | SQLite card data queries |

---

## 3. Data Flow

### 3.1 Port Discovery → Worker Creation

```
ModemDiscovery.enumerate_ports()
  → filter_candidates() [HWID/VID priority]
  → filter_active_workers() [skip existing]
  → probe_concurrent() [AT\r\n at 115200]
  → VerifiedPort list
    → WorkerManager.create_worker()
      → SerialAdapter(port, baud)
      → ATClient(serial)
      → PortWorker.connect(serial, at_client)
        → ATE0 (disable echo)
        → CpinRuntime.start() [polling begins]
```

### 3.2 GUI Button → Workflow Execution

```
User clicks "Cek Nomor Massal"
  → main_window publishes "cmd.mass.cek_nomor"
  → UIController._handle_mass_cek_nomor()
    → set_mode("CHECK_DATA")
    → _get_mass_targets() [eligibility check]
    → For each eligible port:
      → engine.enqueue_workflow(port, "check_number", trigger_id=cmd_id)
        → WorkflowQueue.enqueue(QueueItem)
          → _worker_loop() dequeues
            → _execute_workflow(item)
              → runner.run(workflow, port, trigger_id)
                → resolve skill (factory pattern)
                → skill.execute(port, skill_resolver, command_id)
                  → at_client.send_command("AT+CNUM")
                  → parse response
                  → return SkillResult
```

### 3.3 SIM Event → Auto-Run

```
CpinRuntime detects READY
  → publishes "cpin.transition" {port, new_state}
  → PortWorker._on_cpin_changed()
    → set single_action or queue_auto_run
  → PortWorker._tick()
    → should_block_auto_run() → False
    → _execute_auto_run()
      → step: cek_nomor → cek_status → cek_nik → cek_kk → reaktivasi
```

---

## 4. Ownership Boundaries

| Owner | Owns | Does NOT Own |
|-------|------|--------------|
| GUI | Display, user input | Business logic |
| Controller | Command routing, eligibility | Modem communication |
| AutomationEngine | Queue, scheduling, policy | Skill execution |
| WorkflowRunner | Step execution, skill resolution | Modem communication |
| Skills | AT/USSD protocol | State management |
| PortWorker | Per-port lifecycle, serial ownership | Other ports |
| WorkerManager | Port creation/destruction, scanning | Individual port logic |
| CpinRuntime | SIM status polling | Workflow execution |

---

## 5. Thread Model

| Thread | Owner | Purpose |
|--------|-------|---------|
| Main (tkinter) | GUI | Event drain, UI updates |
| `WorkerManager._scan_thread` | WorkerManager | Background port scanning |
| `PortWorker._thread` (per port) | PortWorker | Per-port tick loop |
| `CpinRuntime._thread` (per port) | CpinRuntime | SIM status polling |
| `AutomationEngine._worker_thread` | AutomationEngine | Queue processing |
| `MassDispatch-*` (temporary) | Controller | Mass command dispatch |
| `Workflow-*` (temporary) | AutomationEngine | Per-workflow execution |

---

## 6. Event Bus

All inter-component communication uses `EventBus` (thread-safe pub/sub).

| Event | Direction | Publisher | Subscriber |
|-------|-----------|-----------|------------|
| `cmd.cek_nomor` | GUI→Backend | Context menu | Controller |
| `cmd.cek_status` | GUI→Backend | Context menu | Controller |
| `cmd.mass.cek_nomor` | GUI→Backend | Action bar | Controller |
| `cmd.mass.reaktivasi` | GUI→Backend | Action bar | Controller |
| `cmd.reset_modem` | GUI→Backend | Action bar | Controller |
| `cmd.restart_all` | GUI→Backend | Action bar | Controller |
| `cmd.auto_run.toggle` | GUI→Backend | Action bar | Controller |
| `cmd.save_config` | GUI→Backend | Settings | Controller |
| `ui.port.update` | Backend→GUI | Worker/Controller | MainWindow |
| `ui.port.discovered` | Backend→GUI | WorkerManager | MainWindow |
| `ui.port.removed` | Backend→GUI | WorkerManager | MainWindow |
| `ui.log.append` | Backend→GUI | Worker | LogViewer |
| `ui.mass.progress` | Backend→GUI | Controller | MainWindow |
| `modem.online` | Worker→Engine | PortWorker | WorkerManager |
| `modem.offline` | Worker→Engine | PortWorker | WorkerManager |
| `cpin.transition` | Worker→Engine | CpinRuntime | PortWorker |
| `automation.started` | Engine→GUI | AutomationEngine | Controller |
| `automation.completed` | Engine→GUI | AutomationEngine | Controller |
| `automation.failed` | Engine→GUI | AutomationEngine | Controller |
