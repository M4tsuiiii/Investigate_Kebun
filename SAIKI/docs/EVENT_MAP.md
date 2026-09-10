# EVENT_MAP.md — SAIKI Sprint 9

> Complete mapping of all events in the SAIKI system.
> Publisher: who emits the event. Subscriber: who listens to it.

---

## 1. Event Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         EventBus (central hub)                     │
└──────────┬──────────────────┬──────────────────┬───────────────────┘
           │                  │                  │
     ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
     │   UI      │     │  Worker   │     │ Automation│
     │Controller │     │  Layer    │     │  Engine   │
     └─────┬─────┘     └─────┬─────┘     └─────┬─────┘
           │                  │                  │
  ┌────────▼────────┐  ┌─────▼──────┐  ┌───────▼───────┐
  │ UIEvents (out)  │  │ UIEvents   │  │automation.*   │
  │ CmdEvents (in)  │  │ CmdEvents  │  │               │
  └────────┬────────┘  └─────┬──────┘  └───────┬───────┘
           │                  │                  │
     ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
     │ ModemMon  │     │PortWorker │     │ CpinRuntime│
     └─────┬─────┘     └───────────┘     └─────┬─────┘
           │                                    │
     ┌─────▼─────┐                       ┌─────▼─────┐
     │modem.*    │                       │cpin.*     │
     └───────────┘                       └───────────┘

     ┌───────────┐
     │UssdRuntime│
     └─────┬─────┘
           │
     ┌─────▼─────┐
     │ ussd.*    │
     └───────────┘
```

**Flow Summary:**
- UIController publishes `cmd.*` → consumed by WorkerManager, AutomationEngine, DbLookup.
- PortWorker, WorkerManager, ModemMonitor publish `ui.*` → consumed by UIController.
- AutomationEngine publishes `automation.*` → consumed by UIController.
- CpinRuntime publishes `cpin.*` → consumed by PortWorker.
- UssdRuntime publishes `ussd.*` → consumed by PortWorker / AutomationEngine.

---

## 2. Complete Event Table

### UIEvent (Worker → UI)

| Event | Publisher | Subscriber | Direction |
|---|---|---|---|
| `ui.port.discovered` | WorkerManager (`create_worker`) | UIController | Worker → UI |
| `ui.port.update` | PortWorker (`_publish_status`) | UIController | Worker → UI |
| `ui.port.removed` | WorkerManager (`destroy_worker`) | UIController | Worker → UI |
| `ui.worker.started` | PortWorker | UIController | Worker → UI |
| `ui.worker.stopped` | PortWorker | UIController | Worker → UI |
| `ui.log.append` | PortWorker | UIController | Worker → UI |
| `ui.footer.update` | PortWorker | UIController | Worker → UI |
| `ui.settings.changed` | UIController (`_handle_save_config`) | UIController (self) | UI → UI |
| `ui.scan.complete` | WorkerManager (`_scan_and_update`) | UIController | Worker → UI |
| `ui.modem.online` | ModemMonitor | UIController | Modem → UI |
| `ui.modem.offline` | ModemMonitor | UIController | Modem → UI |
| `ui.auto_run.changed` | UIController (`_handle_auto_run_toggle`) | UIController (self) | UI → UI |
| `ui.mass.progress` | UIController (mass actions) | UIController (self) | UI → UI |
| `ui.mass.complete` | MassAction | UIController | Worker → UI |
| `ui.db.lookup.result` | UIController (DB lookups) | UIController (self) | DB → UI |
| `ui.task` | EventBus | UIController | System → UI |

### CommandEvent (UI → Worker)

| Event | Publisher | Subscriber | Direction |
|---|---|---|---|
| `cmd.port.on` | UIController | WorkerManager | UI → Worker |
| `cmd.port.off` | UIController | WorkerManager | UI → Worker |
| `cmd.cek_nomor` | UIController | PortWorker | UI → Worker |
| `cmd.cek_nik` | UIController | PortWorker | UI → Worker |
| `cmd.cari_kk` | UIController | PortWorker | UI → Worker |
| `cmd.reaktivasi` | UIController | AutomationEngine | UI → Automation |
| `cmd.restart_all` | UIController | All workers | UI → Worker |
| `cmd.stop_all` | UIController | All workers + AutomationEngine | UI → Worker+Auto |
| `cmd.reset_modem` | UIController | AutomationEngine | UI → Automation |
| `cmd.force_retry` | UIController | PortWorker | UI → Worker |
| `cmd.save_config` | UIController | ConfigManager | UI → Config |
| `cmd.auto_run.toggle` | UIController | AutoRunConfig | UI → Config |
| `cmd.db.lookup_nik` | UIController | DbLookup | UI → DB |
| `cmd.db.lookup_kk` | UIController | DbLookup | UI → DB |
| `cmd.mass.reaktivasi` | UIController | AutomationEngine | UI → Automation |
| `cmd.mass.cek_nomor` | UIController | AutomationEngine | UI → Automation |
| `cmd.reactivate` | UIController | AutomationEngine | UI → Automation |

### Automation Events

| Event | Publisher | Subscriber | Direction |
|---|---|---|---|
| `automation.started` | AutomationEngine (`_execute_workflow`) | UIController | Automation → UI |
| `automation.completed` | AutomationEngine (`_execute_workflow`) | UIController | Automation → UI |
| `automation.failed` | AutomationEngine (`_execute_workflow`) | UIController | Automation → UI |
| `automation.skipped` | AutomationEngine (`handle_trigger`) | UIController | Automation → UI |
| `automation.retry` | AutomationEngine (`_execute_workflow`) | UIController | Automation → UI |
| `automation.queue_changed` | AutomationEngine (`_enqueue`) | UIController | Automation → UI |

### Worker Events

| Event | Publisher | Subscriber | Direction |
|---|---|---|---|
| `ui.port.update` | PortWorker (`_publish_status`) | UIController | Worker → UI |

### ModemMonitor Events

| Event | Publisher | Subscriber | Direction |
|---|---|---|---|
| `modem.online` | ModemMonitor | UIController | Modem → UI |
| `modem.offline` | ModemMonitor | UIController | Modem → UI |
| `modem.appeared` | ModemMonitor | WorkerManager | Modem → Worker |
| `modem.disappeared` | ModemMonitor | WorkerManager | Modem → Worker |

### CpinRuntime Events

| Event | Publisher | Subscriber | Direction |
|---|---|---|---|
| `cpin.transition` | CpinRuntime | PortWorker | Cpin → Worker |

### USSD Events

| Event | Publisher | Subscriber | Direction |
|---|---|---|---|
| `ussd.response` | UssdRuntime | PortWorker / AutomationEngine | USSD → Worker |

---

## 3. Event Categories

### UI Events (status & feedback)
```
ui.port.discovered    ui.port.update       ui.port.removed
ui.worker.started     ui.worker.stopped    ui.log.append
ui.footer.update      ui.settings.changed  ui.scan.complete
ui.modem.online       ui.modem.offline     ui.auto_run.changed
ui.mass.progress      ui.mass.complete     ui.db.lookup.result
ui.task
```
**Purpose:** Push status updates, log messages, and state changes from workers/monitors back to the UI layer.

### Modem Events (hardware detection)
```
modem.online          modem.offline
modem.appeared        modem.disappeared
```
**Purpose:** Track modem hardware lifecycle. `online/offline` feed UI; `appeared/disappeared` feed WorkerManager for port management.

### Automation Events (workflow lifecycle)
```
automation.started     automation.completed  automation.failed
automation.skipped     automation.retry      automation.queue_changed
```
**Purpose:** Report automation workflow progress. All consumed by UIController for display/logging.

### Worker Events (device interaction)
```
cpin.transition        ussd.response
```
**Purpose:** Low-level device communication results. `cpin.transition` drives SIM state machine in PortWorker. `ussd.response` returns USSD dial results.

---

## 4. Dead Event Check

> Events that are **published** but have **no registered subscriber**.

| Event | Publisher | Status |
|---|---|---|
| `ui.task` | EventBus | **⚠️ Potential dead event** — verify UIController subscribes |

All other events have at least one subscriber registered via the EventBus.

---

## 5. Orphan Check

> Subscribers that listen for events **no publisher emits**.

| Subscriber | Listens For | Status |
|---|---|---|
| ConfigManager | `cmd.save_config` | ✅ Published by UIController |
| AutoRunConfig | `cmd.auto_run.toggle` | ✅ Published by UIController |
| DbLookup | `cmd.db.lookup_nik`, `cmd.db.lookup_kk` | ✅ Published by UIController |

**Result:** No orphan subscribers found. All subscribed events have a corresponding publisher.

---

## 6. Cross-Reference: Source Files

| File | Events Published |
|---|---|
| `worker/ui/events.py` | EventBus definitions |
| `worker/port_worker.py` | `ui.port.update`, `ui.worker.*`, `ui.log.append` |
| `worker/worker_manager.py` | `ui.port.discovered`, `ui.port.removed`, `ui.scan.complete` |
| `worker/modem_monitor.py` | `modem.online`, `modem.offline`, `modem.appeared`, `modem.disappeared` |
| `worker/cpin_runtime.py` | `cpin.transition` |
| `worker/ussd_runtime.py` | `ussd.response` |
| `automation/engine.py` | `automation.*` |
| `ui/controller.py` | `cmd.*`, `ui.mass.*`, `ui.settings.changed` |
| `ui/mass_action.py` | `ui.mass.complete` |
