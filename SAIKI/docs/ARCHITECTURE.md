# SAIKI Architecture

## 1. System Overview

SAIKI is the active rebuild of GOOD Kebun Reaktivasi — a monolithic GSM reactivation system rebuilt into a modular, event-driven architecture with strict dependency inversion.

### 1.1 Design Goals

| Goal | Strategy | Addresses |
|------|----------|-----------|
| Thread safety | RLock state machines, atomic operations | M-01, M-02, M-03, M-13 |
| Single source of truth | One enum set in `app/domain/enums.py` | I-03, I-04, I-05, I-06 |
| Dependency inversion | Domain ABCs, infrastructure adapters | D-01, D-05 |
| Event-driven UI | EventBus pub/sub, no direct widget access | D-04, D-06 |
| Testable | Every module unit-testable in isolation | All |

### 1.2 Non-Goals

- No rewrite from scratch — incremental migration from GOOD
- No new features — feature parity only
- No database schema changes — SQLite preserved
- No UI framework change — Tkinter preserved

---

## 2. Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  UI Layer (worker/ui/)                                      │
│  Pure Tkinter presentation. Zero business logic.            │
│  Communicates via Event Bus only.                           │
├─────────────────────────────────────────────────────────────┤
│  Integration Layer (worker/integration/)                    │
│  Port lifecycle, scan scheduler, worker factory.            │
│  Bridges UI events to worker actions.                       │
├─────────────────────────────────────────────────────────────┤
│  Worker Layer (worker/)                                     │
│  Per-port state machine, auto-run queue, retry/reset.       │
│  One thread per COM port.                                   │
├─────────────────────────────────────────────────────────────┤
│  USSD Engine (worker/ussd/)                                 │
│  Classification, session fence, cooldown, grace read.       │
│  Stateless — receives modem stream, returns parsed data.    │
├─────────────────────────────────────────────────────────────┤
│  Reactivation Engine (worker/reactivation/)                 │
│  Card classification, NIK/KK flows, injection,              │
│  verification, outcome evaluation.                          │
├─────────────────────────────────────────────────────────────┤
│  Domain Layer (app/domain/)                                 │
│  Enums, models, rules, state machines.                      │
│  Zero framework dependencies.                               │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer (app/infrastructure/)                 │
│  Serial port, database, Telegram, logging adapters.         │
│  Implements domain ABC ports.                               │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Import Rules

| From | To | Allowed |
|------|----|---------|
| UI → Domain | No | Indirect via EventBus |
| UI → Infrastructure | No | Indirect via Event |
| Worker → Domain | Yes | Business logic |
| Worker → Infrastructure | Yes | Ports |
| USSD → Domain | Yes | Models, enums |
| Reactivation → Domain | Yes | Models, rules |
| Infrastructure → Domain | No | Only ABC imports |

---

## 3. Event Flow

### 3.1 Outbound (Worker → UI)

```
Worker Thread                Event Bus                UI Controller
     │                          │                          │
     ├──publish(STATUS_UPDATE)──┤                          │
     │   {port, msisdn, status, │                          │
     │    card, balance, ...}   │                          │
     │                          ├──STATUS_UPDATE──────────→│
     │                          │                          ├──UpdateQueue.put()
     │                          │                          │
     │                          │                          │  [Main Thread]
     │                          │                          │  Treeview.insert()
```

### 3.2 Inbound (UI → Worker)

```
UI Controller               Event Bus               Integration Layer
     │                         │                          │
     ├──publish(CMD_RESTART)───┤                          │
     │   {port_id: "COM3"}     │                          │
     │                         ├──CMD_RESTART─────────────→│
     │                         │                          ├──PortWorker.force_retry()
     │                         │                          │
     ├──publish(CMD_RUN_ALL)───┤                          │
     │                         ├──CMD_RUN_ALL─────────────→│
     │                         │                          ├──AutoRunQueue.enqueue_all()
```

### 3.3 Event Types

| Event | Direction | Payload | Audit Fix |
|-------|-----------|---------|-----------|
| `STATUS_UPDATE` | Worker → UI | `{port, msisdn, status, card, balance, online, read_ts, failure}` | — |
| `SCAN_COMPLETE` | Scanner → UI | `{ports: [{id, msisdn, online}]}` | — |
| `CMD_RUN_ALL` | UI → Worker | `{}` (global) | — |
| `CMD_STOP_ALL` | UI → Worker | `{}` (global) | — |
| `CMD_RESTART` | UI → Worker | `{port_id}` | — |
| `CMD_FORCE_RETRY` | UI → Worker | `{port_id}` | — |
| `CMD_RESET_MODEM` | UI → Worker | `{port_id}` | — |
| `CMD_SINGLE_ACTION` | UI → Worker | `{port_id}` | — |

---

## 4. Worker Lifecycle

### 4.1 PortWorker States

```
┌──────────┐   scan发现    ┌──────────┐  start   ┌──────────┐
│  ABSENT  │─────────────→│  IDLE    │─────────→│  READY   │
└──────────┘              └──────────┘          └──────────┘
                              │                    │
                         stop│               force_retry│
                              ▼                    ▼
                         ┌──────────┐       ┌──────────┐
                         │ STOPPED  │       │ RUNNING  │
                         └──────────┘       └──────────┘
                                               │
                                          finish│
                                               ▼
                                          ┌──────────┐
                                          │  READY   │
                                          └──────────┘
```

### 4.2 PortWorker Implementation (Fixes M-01)

```python
class PortWorker:
    def __init__(self, port_id: str, config: Config, event_bus: EventBus):
        self._state = PortWorkerState()  # RLock-protected
        self._event_bus = event_bus
        self._modem = ModemPortAdapter(port_id, config)  # Infrastructure
        self._cpin_monitor = CPINMonitor(self._modem)
        self._auto_run = AutoRunQueue(self._state)
        self._retry = RetryManager(self._state)
        self._reset = ResetManager(self._modem)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    def start(self):
        """Called from Integration layer on scan發現."""
        self._running.set()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"worker-{self._port_id}",
            daemon=True
        )
        self._thread.start()

    def stop(self):
        """Graceful shutdown."""
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run_loop(self):
        """Main worker loop — runs in own thread."""
        while self._running.is_set():
            if self._state.should_block_auto_run():
                time.sleep(0.1)
                continue

            step = self._auto_run.next_step()
            if step is None:
                time.sleep(0.1)
                continue

            try:
                self._execute_step(step)
            except Exception as e:
                self._event_bus.publish(STATUS_UPDATE, {
                    "port": self._port_id,
                    "status": "ERROR",
                    "failure": str(e)
                })
            finally:
                self._auto_run.mark_done(step)
```

### 4.3 PortWorkerState (Fixes M-02, M-03)

```python
class PortWorkerState:
    def __init__(self):
        self._lock = threading.RLock()  # RLock, not Lock
        self._auto_run_enabled = False
        self._force_retry = False
        self._single_action = None
        self._unknown_count = 0
        self._checking_count = 0
        self._card_cycle_awaiting = False

    def consume_auto_run(self, enabled: bool):
        """Atomic toggle for auto-run."""
        with self._lock:
            self._auto_run_enabled = enabled

    def consume_force_retry(self):
        """Atomic consume — returns and clears."""
        with self._lock:
            val = self._force_retry
            self._force_retry = False
            return val

    def consume_single_action(self):
        """Atomic consume — returns and clears."""
        with self._lock:
            val = self._single_action
            self._single_action = None
            return val

    def increment_unknown(self):
        """Atomic increment with threshold check."""
        with self._lock:
            self._unknown_count += 1
            return self._unknown_count >= CPIN_UNKNOWN_THRESHOLD

    def snapshot(self) -> dict:
        """Thread-safe snapshot of all state."""
        with self._lock:
            return {
                "auto_run": self._auto_run_enabled,
                "force_retry": self._force_retry,
                "single_action": self._single_action,
                "unknown_count": self._unknown_count,
                "checking_count": self._checking_count,
                "card_cycle_awaiting": self._card_cycle_awaiting,
            }
```

---

## 5. Auto-Run Design

### 5.1 Global Toggle (Fixes B-01)

Single source of truth: `rules.should_block_auto_run(state, config)`.

```python
def should_block_auto_run(state: PortWorkerState, config: Config) -> bool:
    """Returns True if auto-run should be blocked."""
    snap = state.snapshot()
    if not snap["auto_run"]:
        return True
    if snap["force_retry"]:
        return True
    if snap["single_action"] is not None:
        return True
    if snap["card_cycle_awaiting"]:
        return True
    return False
```

### 5.2 Step Execution

Each auto-run step is atomic:
1. Check gate (`should_block_auto_run`)
2. Pop next step from queue
3. Execute step (USSD dial, inject, verify)
4. Publish result to EventBus
5. Mark step done
6. Sleep `DIAL_COOLDOWN` (4.0s) between steps

### 5.3 Step Cleanup

After each step, regardless of outcome:
- Update `PortWorkerState` with result
- Publish `STATUS_UPDATE` to UI
- Release any held locks
- Reset transient flags (e.g., `card_cycle_awaiting`)

---

## 6. Modem Monitoring Design

### 6.1 Online/Offline Detection (Fixes I-01)

```python
class ModemMonitor:
    """Runs in worker thread, checks modem presence every 5s."""

    def __init__(self, modem: ModemPort, event_bus: EventBus):
        self._modem = modem
        self._event_bus = event_bus
        self._online = False

    def check(self) -> bool:
        """Returns True if modem responds to AT."""
        try:
            response = self._modem.send_at("AT", timeout=2.0)
            was_online = self._online
            self._online = response is not None

            if was_online and not self._online:
                self._event_bus.publish(MODEM_OFFLINE, {"port": self._modem.port_id})
            elif not was_online and self._online:
                self._event_bus.publish(MODEM_ONLINE, {"port": self._modem.port_id})

            return self._online
        except Exception:
            self._online = False
            return False
```

### 6.2 COM Disappearance Handling

```
COM Disappear
     │
     ├──publish(MODEM_OFFLINE)──→ UI
     │
     ├──stop worker thread
     │
     ├──wait 30s
     │
     ├──re-enumerate COM ports
     │
     ├──if COM reappears: restart worker
     │
     └──if COM gone: publish(PORT_REMOVED)──→ UI
```

### 6.3 SIM Transition Detection

```
SIM Changed (MSISDN mismatch)
     │
     ├──compare current MSISDN vs registered MSISDN
     │
     ├──if mismatch:
     │     ├──stop worker
     │     ├──publish(SIM_CHANGED, {old, new})──→ UI
     │     ├──update registry
     │     └──restart worker with new MSISDN
     │
     └──if match: continue
```

---

## 7. USSD Engine Design

### 7.1 Classification Pipeline (Fixes I-04)

```
Raw USSD Response
     │
     ▼
┌─────────────────┐
│  BR-014: Tier   │  9-tier priority classification
│  Classifier     │  (PULSA, MENU, PIN, ERROR, etc.)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  BR-015: Intent │  Extracts intent from tier
│  Classifier     │  (check_balance, check_status, etc.)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  BR-016:        │  Checks if payload complete
│  Completeness   │  (keyword matching)
└────────┬────────┘
         │
         ▼
  Classified USSD
  {tier, intent, complete, payload}
```

### 7.2 Session Fence (BR-018)

```python
class SessionFence:
    def __init__(self, config: Config):
        self._min_interval = config.get("ussd.session_fence_min", 0.75)
        self._quiet_interval = config.get("ussd.session_fence_quiet", 0.25)
        self._timeout = config.get("ussd.session_fence_timeout", 3.0)
        self._last_dial = 0.0

    def wait_before_dial(self):
        """Enforces minimum interval between USSD dials."""
        elapsed = time.time() - self._last_dial
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_dial = time.time()

    def cancel_session(self, modem: ModemPort):
        """Sends AT+CUSD=2 to cancel active USSD session."""
        modem.send_at("AT+CUSD=2", timeout=self._timeout)
```

### 7.3 Cooldown (BR-019)

```python
class DialCooldown:
    def __init__(self, min_seconds: float = 4.0):
        self._min_seconds = min_seconds
        self._last_dial = 0.0

    def wait(self):
        elapsed = time.time() - self._last_dial
        if elapsed < self._min_seconds:
            time.sleep(self._min_seconds - elapsed)
        self._last_dial = time.time()
```

---

## 8. Reactivation Flow Design

### 8.1 Full Flow (BR-003 through BR-009)

```
Start
  │
  ▼
[1] Classify Card (BR-010)
  │  ├── AKTIF/TENGGANG → SKIP (BR-001)
  │  └── HANGUS → continue
  │
  ▼
[2] Get NIK (BR-003)
  │  ├── Cache hit → use cached
  │  ├── NIK&NIK mode → KK = NIK (BR-025)
  │  └── Cache miss → USSD dial *185#
  │
  ▼
[3] Get KK (BR-004)
  │  ├── NIK&NIK mode → skip
  │  ├── Cache hit → use cached
  │  └── Cache miss → DB lookup → Telegram
  │
  ▼
[4] Validate NIK/KK (BR-024)
  │  └── 16 digits each
  │
  ▼
[5] Inject (BR-005)
  │  ├── BoundedSemaphore(2) (HR-015)
  │  ├── AT+CUSD for injection
  │  └── Provisional success check (BR-006)
  │
  ▼
[6] Wait 15s (BR-007)
  │
  ▼
[7] Verify (BR-007)
  │  ├── Dial *185# again
  │  └── Compare before/after
  │
  ▼
[8] Evaluate Outcome (BR-008)
  │  ├── SUCCESS → TENGGANG (BR-020)
  │  ├── TENGGANG → TENGGANG (BR-021)
  │  └── FAILED → FAILED (BR-022)
  │
  ▼
[9] Update Registry
  │
  ▼
End
```

### 8.2 Injection Lock (Fixes HR-015)

```python
# Global injection lock — max 2 concurrent
injection_lock = threading.BoundedSemaphore(2)

def inject(modem: ModemPort, payload: str):
    with injection_lock:
        return modem.send_ussd(payload)
```

### 8.3 Verification Response Parsing (Fixes H11-F)

```python
def parse_verification_response(response: str, cached_state: dict) -> dict:
    """Parse verification USSD response with grace date support."""
    # Must include grace dates in verification response
    card_status = classify_card(response)
    grace_dates = extract_grace_dates(response)  # NEW: was missing

    return {
        "card_status": card_status,
        "grace_dates": grace_dates,
        "msisdn": extract_msisdn(response),
    }
```

---

## 9. UI Integration Design

### 9.1 Event Bus (Fixes D-04)

```python
class EventBus:
    """Thread-safe pub/sub for worker-UI communication."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[callable]] = {}

    def subscribe(self, event_type: str, callback: callable):
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event_type: str, data: dict):
        with self._lock:
            callbacks = self._subscribers.get(event_type, []).copy()
        for cb in callbacks:
            try:
                cb(data)
            except Exception:
                pass  # Never crash worker thread
```

### 9.2 Update Queue (Fixes D-06)

```python
class UpdateQueue:
    """Thread-safe queue for UI updates."""

    def __init__(self):
        self._queue = queue.Queue()
        self._seen = set()  # Deduplication

    def put(self, update: dict):
        key = (update["port"], update["status"])
        if key not in self._seen:
            self._seen.add(key)
            self._queue.put(update)

    def drain(self) -> list[dict]:
        """Called from main thread every 100ms."""
        updates = []
        while not self._queue.empty():
            updates.append(self._queue.get())
        self._seen.clear()
        return updates
```

### 9.3 Controller (Fixes B-03)

```python
class Controller:
    """Bridges EventBus events to worker actions."""

    def __init__(self, event_bus: EventBus, worker_registry: dict):
        self._event_bus = event_bus
        self._registry = worker_registry

        # Subscribe to all commands
        self._event_bus.subscribe("CMD_RUN_ALL", self._handle_run_all)
        self._event_bus.subscribe("CMD_STOP_ALL", self._handle_stop_all)
        self._event_bus.subscribe("CMD_RESTART", self._handle_restart)
        self._event_bus.subscribe("CMD_FORCE_RETRY", self._handle_force_retry)
        self._event_bus.subscribe("CMD_RESET_MODEM", self._handle_reset_modem)

    def _handle_restart(self, data: dict):
        port_id = data["port_id"]
        worker = self._registry.get(port_id)
        if worker:
            worker.restart()
```

---

## 10. Thread Safety Strategy

### 10.1 Lock Hierarchy

| Level | Lock | Protects | Rule |
|-------|------|----------|------|
| 1 | `PortWorkerState._lock` (RLock) | Worker state | Never hold while calling EventBus |
| 2 | `EventBus._lock` | Subscriber list | Copy before iterating |
| 3 | `UpdateQueue._lock` | Update queue | Never hold during drain |
| 4 | `injection_lock` (Semaphore) | Concurrent injections | Max 2 system-wide |
| 5 | `SerialPort._lock` | Serial I/O | One command at a time |

### 10.2 Deadlock Prevention

```python
# RULE: Never call EventBus while holding PortWorkerState lock
# WRONG:
with state._lock:
    state.auto_run = True
    event_bus.publish(STATUS_UPDATE, ...)  # DEADLOCK RISK

# RIGHT:
with state._lock:
    state.auto_run = True
event_bus.publish(STATUS_UPDATE, ...)  # After releasing lock
```

### 10.3 Thread Ownership

| Resource | Owner | Access Pattern |
|----------|-------|----------------|
| Tkinter widgets | Main thread | Queue-drain pattern |
| Serial port | Worker thread | One command at a time |
| Database | Any thread | Connection-per-operation |
| EventBus | Any thread | Lock-protected publish |

---

## 11. Dependency Injection Strategy

### 11.1 Port Interfaces (ABC)

```python
# app/domain/ports/modem.py
class ModemPort(ABC):
    @abstractmethod
    def send_at(self, command: str, timeout: float = 5.0) -> str | None: ...

    @abstractmethod
    def send_ussd(self, payload: str, timeout: float = 10.0) -> str | None: ...

    @abstractmethod
    def close(self) -> None: ...

# app/domain/ports/database.py
class DatabasePort(ABC):
    @abstractmethod
    def lookup_nik(self, msisdn: str) -> str | None: ...

    @abstractmethod
    def lookup_kk(self, nik: str) -> str | None: ...

    @abstractmethod
    def save_result(self, msisdn: str, result: dict) -> None: ...

# app/domain/ports/telegram.py
class TelegramPort(ABC):
    @abstractmethod
    def query_nik(self, kk: str) -> str | None: ...

    @abstractmethod
    def query_kk(self, nik: str) -> str | None: ...
```

### 11.2 Infrastructure Adapters

```python
# app/infrastructure/serial/modem_adapter.py
class ModemPortAdapter(ModemPort):
    def __init__(self, port_id: str, config: Config):
        self._serial = serial.Serial(port_id, baudrate=115200, timeout=1)
        self._lock = threading.Lock()

    def send_at(self, command: str, timeout: float = 5.0) -> str | None:
        with self._lock:
            self._serial.write(f"{command}\r\n".encode())
            return self._serial.read_until(b"OK", timeout=timeout)

# app/infrastructure/database/sqlite_adapter.py
class SQLiteAdapter(DatabasePort):
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path)

    def lookup_nik(self, msisdn: str) -> str | None:
        cursor = self._conn.execute("SELECT nik FROM cards WHERE msisdn=?", (msisdn,))
        row = cursor.fetchone()
        return row[0] if row else None
```

### 11.3 Wire-Up

```python
# main.py
def create_app():
    config = load_config("configs/default.ini")
    event_bus = EventBus()
    db = SQLiteAdapter(config.get("database.path"))
    telegram = TelegramAdapter(config.get("telegram.token"))

    # Wire domain services
    modem_factory = lambda port_id: ModemPortAdapter(port_id, config)

    # Create integration layer
    integration = IntegrationLayer(
        config=config,
        event_bus=event_bus,
        modem_factory=modem_factory,
        database=db,
        telegram=telegram,
    )

    # Create UI
    ui = MainWindow(event_bus, integration)

    return ui
```

---

## 12. Failure Recovery Strategy

### 12.1 Worker Crash Recovery

```python
def recover_worker(worker: PortWorker):
    """Called when worker thread dies unexpectedly."""
    try:
        worker.stop()
    except Exception:
        pass

    # Wait for COM port to stabilize
    time.sleep(5.0)

    # Re-enumerate COM ports
    ports = enumerate_com_ports()

    # If worker's COM still exists, restart
    if worker.port_id in [p.id for p in ports]:
        worker.restart()
    else:
        # Publish removal event
        event_bus.publish(PORT_REMOVED, {"port": worker.port_id})
```

### 12.2 USSD Session Recovery

```python
def recover_ussd_session(modem: ModemPort):
    """Recover from stuck USSD session."""
    # Send cancel command
    modem.send_at("AT+CUSD=2", timeout=3.0)

    # Wait for modem to settle
    time.sleep(2.0)

    # Send AT to verify modem is responsive
    response = modem.send_at("AT", timeout=3.0)

    if response is None:
        # Modem unresponsive — trigger reset
        raise ModemUnresponsiveError()
```

### 12.3 Database Recovery

```python
def recover_database(db: DatabasePort):
    """Recover from database lock/contention."""
    # Close and reopen connection
    db.close()
    time.sleep(1.0)
    db.reconnect()
```

---

## 13. Future Extension Points

### 13.1 Planned Extensions

| Extension | Current State | Future State | Migration Path |
|-----------|--------------|--------------|----------------|
| Telegram Gateway | Mock (HR-012) | Real Bot API | Replace `TelegramAdapter` |
| CSV Import/Export | Not implemented | Full support | New `CsvPort` adapter |
| Per-Port Logging | Single log file | Per-port rotating | New `PortLogger` adapter |
| License Gate | Not implemented | Optional | New `LicensePort` adapter |
| Web Dashboard | Not implemented | Optional | New `WebEventBus` adapter |

### 13.2 Plugin Architecture

```python
# Future: Plugin system
class Plugin(ABC):
    @abstractmethod
    def on_event(self, event_type: str, data: dict) -> dict | None: ...

    @abstractmethod
    def on_worker_start(self, worker: PortWorker) -> None: ...

    @abstractmethod
    def on_worker_stop(self, worker: PortWorker) -> None: ...

# Registration
plugins = [LicensePlugin(), CsvPlugin(), WebPlugin()]
for plugin in plugins:
    event_bus.subscribe_all(plugin.on_event)
```

---

## 14. Audit Findings Addressed

### 14.1 Critical Findings Fixed

| Finding | Issue | Fix | Section |
|---------|-------|-----|---------|
| M-01 | No PortWorker thread | Implement `PortWorker` with daemon thread | §4.2 |
| M-02 | `PortWorkerState` unlocked | Add `RLock` to all `consume_*()` methods | §4.3 |
| M-03 | TOCTOU in state reads | Atomic `snapshot()` method | §4.3 |
| M-13 | `threading.Lock` deadlock | Change to `threading.RLock` | §4.3, §10 |
| I-03 | Duplicate `CPinState` enums | Single `CPinState` in `domain/enums.py` | §2.1 |
| I-04 | Duplicate `CardStatus` enums | Single `CardStatus` in `domain/enums.py` | §2.1 |
| I-05 | Duplicate `BusinessOutcome` | Single `BusinessOutcome` in `domain/enums.py` | §2.1 |
| I-06 | Duplicate `FailureCode` | Single `FailureCode` in `domain/enums.py` | §2.1 |

### 14.2 High Findings Fixed

| Finding | Issue | Fix | Section |
|---------|-------|-----|---------|
| B-01 | 4 copies of auto-run gate | Single `should_block_auto_run()` in `rules.py` | §5.1 |
| B-02 | `PortWorkerState` race | Lock all state mutations | §4.3 |
| B-03 | Controller direct widget access | All UI via EventBus + UpdateQueue | §9.3 |
| I-01 | `BusinessOutcome` value mismatch | Unified enum value `"SUKSES"` vs `"SUCCESS"` | §2.1 |
| I-02 | `MSISDN_RE` in two places | Single `MSISDN_RE` in `domain/classifier.py` | §2.1 |
| I-08 | `reader.py:209` AttributeError | Use `.ussd_class.name` not `.classification.name` | §7.1 |
| I-09 | `full_flow.py:292` None check | Add `if response:` before `.provisional.is_waiting` | §8.1 |
| I-10 | `full_flow.py:186` enum comparison | Compare enum values, not strings | §8.1 |
| H11-F | Grace dates missing in verification | Add `extract_grace_dates()` to verification | §8.3 |

### 14.3 Medium Findings Fixed

| Finding | Issue | Fix | Section |
|---------|-------|-----|---------|
| M-04 | `BoundedSemaphore` not wired | Wire to injection function | §8.2 |
| M-05 | `reader.py:148` dead variable | Remove `quiet_start` | §7 |
| M-06 | `is_ussd_payload_complete` keyword subset | Use full `PROMPT_KEYWORDS` list | §7.1 |
| M-07 | `full_flow.py:196` date parser | Use 4-format date parser from `verification.py` | §8.1 |
| M-08 | `full_flow.py:184` late import | Move import to top of module | §8.1 |
| M-09 | `require_card_cycle()` not called | Add call in full flow | §8.1 |
| M-10 | `session.py:148` dead variable | Remove `quiet_start` | §7 |
| M-11 | 13+ magic wait values | Named constants in `domain/constants.py` | §1.1 |
| M-12 | `StatusGuard` not wired | Wire to controller | §9.3 |
| M-14 | `resolve_kk_source()` broken | Return `LOCAL_DB`/`TELEGRAM` when appropriate | §8.1 |
| M-15 | `should_skip_injection()` params | Respect `bypass_aktif`/`bypass_tenggang` | §5.1 |
| M-16 | `evaluate_business_outcome()` exclusion | Add `"TENGGANG"` to exclusion set | §8.1 |

### 14.4 Low Findings Fixed

| Finding | Issue | Fix | Section |
|---------|-------|-----|---------|
| L-01 | Dead code in `cpin_sm.py` | Remove dead branches | §5 |
| L-02 | Dead code in `autorun.py` | Remove dead branches | §5 |
| L-03 | Dead code in `retry.py` | Remove dead branches | §5 |
| L-04 | Dead code in `reset.py` | Remove dead branches | §5 |
| L-05 | Dead code in `reader.py` | Remove dead branches | §7 |
| L-06 | Dead code in `full_flow.py` | Remove dead branches | §8 |
| L-07 | Dead code in `session.py` | Remove dead branches | §7 |
| L-08 | Unused event names in `events.py` | Remove unused events | §3.3 |
| L-09 | Unused methods in worker modules | Remove unused methods | §4 |
| L-10 | `CPIN_MAX_REMOVAL_CONFIRM` not enforced | Enforce threshold | §6.1 |
| L-11 | `HR-014` partial date parsing | Implement 4-format parser | §8.1 |
| L-12 | `HR-021` Telegram mock acknowledged | Document as mock | §13.1 |

---

## Appendix A: Timing Constants

| Constant | Value | Location |
|----------|-------|----------|
| `DIAL_COOLDOWN` | 4.0s | `domain/constants.py` |
| `USSD_SESSION_FENCE_MIN` | 0.75s | `domain/constants.py` |
| `USSD_SESSION_FENCE_QUIET` | 0.25s | `domain/constants.py` |
| `USSD_SESSION_FENCE_TIMEOUT` | 3.0s | `domain/constants.py` |
| `CPIN_UNKNOWN_THRESHOLD` | 3 | `domain/constants.py` |
| `PROMPT_RECOVERY_MAX` | 2 | `domain/constants.py` |
| `VERIFICATION_DELAY` | 15.0s | `domain/constants.py` |
| `VERIFICATION_READ_TIMEOUT` | 30.0s | `domain/constants.py` |
| `STABILIZATION` | 15.0s | `domain/constants.py` |
| `BAUD_RATES` | [9600, 19200, 115200] | `domain/constants.py` |

## Appendix B: Failure Codes

| Code | Description | Trigger |
|------|-------------|---------|
| `GAGAL_CEK_NIK` | NIK lookup failed | NIK not in cache or DB |
| `GAGAL_KK` | KK lookup failed | KK not in cache, DB, or Telegram |
| `GAGAL_INJEKSI` | Injection failed | Modem unresponsive or error |
| `GAGAL_VERIFIKASI` | Verification failed | Post-injection check failed |
| `GAGAL` | Generic failure | Any other error |

## Appendix C: Thread Model

| Thread | Count | Purpose | Lifetime |
|--------|-------|---------|----------|
| Main (Tkinter) | 1 | UI rendering, event drain | Application lifetime |
| Port Worker | N (per COM) | Modem communication | Per-port lifetime |
| Background Scanner | 1 | COM port enumeration | 30s intervals |
| Background Tasks | 1 | KK lookup, Telegram query | Task queue |
