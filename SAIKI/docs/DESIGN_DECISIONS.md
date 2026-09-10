# Design Decisions

## D-01: Single Enum Source of Truth

**Decision**: All enums defined in `app/domain/enums.py` only.
**Rationale**: Duplicate enums cause `isinstance`/`==` failures across layers.
**Trade-off**: Worker layer must import from domain layer (adds dependency).

## D-02: RLock for State Machines

**Decision**: Use `threading.RLock` instead of `threading.Lock`.
**Rationale**: Listeners may call back into the state machine, causing deadlock with non-reentrant lock.
**Trade-off**: Slightly higher overhead, but correctness is paramount.

## D-03: Consolidated Auto-Run Gate

**Decision**: Single `should_block_auto_run()` in `rules.py`.
**Rationale**: Four copies of the same logic is a maintenance nightmare.
**Trade-off**: All callers must import from `rules.py` (already do).

## D-04: Event-Driven UI

**Decision**: All UI communication via Event Bus.
**Rationale**: Decouples UI from business logic, enables testing.
**Trade-off**: More indirection, harder to trace execution flow.

## D-05: Dependency Inversion for Ports

**Decision**: Domain defines ABC interfaces, infrastructure implements adapters.
**Rationale**: Enables swapping implementations (e.g., real vs mock serial port).
**Trade-off**: More files, but cleaner architecture.

## D-06: Thread-Safe Update Queue

**Decision**: Workers enqueue updates, main thread drains every 100ms.
**Rationale**: Tkinter is not thread-safe; all widget access must be main-thread.
**Trade-off**: Updates may be delayed up to 100ms (acceptable for UI).

## D-07: BoundedSemaphore for Injection

**Decision**: `BoundedSemaphore(2)` limits concurrent injections.
**Rationale**: Prevents modem overload from simultaneous USSD commands.
**Trade-off**: Maximum 2 concurrent injections system-wide.

## D-08: 4-Second DIAL Cooldown

**Decision**: Minimum 4 seconds between USSD dials.
**Rationale**: Prevents carrier-side rate limiting and session conflicts.
**Trade-off**: Slower throughput, but more reliable.

## D-09: 15-Second Verification Delay

**Decision**: Wait 15 seconds after injection before verification.
**Rationale**: Carrier needs time to process reactivation.
**Trade-off**: Each reactivation takes 15+ seconds minimum.

## D-10: CPIN Unknown Threshold = 3

**Decision**: After 3 consecutive UNKNOWN CPIN states, do final confirmation.
**Rationale**: Distinguishes transient errors from permanent SIM removal.
**Trade-off**: 3 polling cycles (~9 seconds) before decision.

## D-11: Prompt Recovery Max = 2

**Decision**: Maximum 2 prompt recovery attempts.
**Rationale**: More retries unlikely to succeed; fail fast.
**Trade-off**: May miss recovery in rare edge cases.

## D-12: Log Cap = 100 Entries

**Decision**: Maximum 100 log entries per port (FIFO eviction).
**Rationale**: Prevents memory leak over long sessions.
**Trade-off**: Old logs lost (acceptable for debugging).

## D-13: Grace Date Formats

**Decision**: Accept ISO (`YYYY-MM-DD`) and local (`DD-MM-YYYY`).
**Rationale**: Carrier responses may use either format.
**Trade-off**: Must handle both in all date parsers.

## D-14: NIK/KK = 16 Digits

**Decision**: Validate NIK and KK as exactly 16 digits.
**Rationale**: Indonesian national ID (NIK) and family card (KK) are 16 digits.
**Trade-off**: No validation for obviously fake numbers.

## D-15: NIK & NIK Mode

**Decision**: When `format_mode == "NIK & NIK"`, KK = NIK.
**Rationale**: Some carriers accept NIK for both fields.
**Trade-off**: No separate KK validation in this mode.

---

## DD-013: Single Hardware Restart

**Decision**: Only one restart action exists. Restart means hardware modem reboot. No separate restart worker.

**After restart**:
| SIM State | Auto Run | Action |
|-----------|----------|--------|
| NOT INSERTED | — | Standby |
| READY | OFF | Standby |
| READY | ON | Enqueue automation |

**Rationale**: Multiple restart types create confusion and error paths. A single atomic restart simplifies state management — one action, one outcome, one recovery path. After restart, the worker re-evaluates conditions from scratch (SIM presence, auto-run toggle) rather than resuming prior state, which prevents stale state bugs.

**Consequences**:
- Restart clears all transient flags (force_retry, single_action, card_cycle_awaiting)
- Restart does NOT clear persistent registry (MSISDN, card status, balance)
- Worker must re-check SIM presence after restart completes
- If SIM absent after restart, worker stays in IDLE until SIM detected
- If SIM ready but auto-run off, worker stays in IDLE
- If SIM ready and auto-run on, worker immediately enqueues full automation sequence

---

## DD-014: Global Auto Run Toggle

**Decision**: Auto Run is a global toggle. No per-port enable/disable.

**Rationale**: Per-port toggles create combinatorial complexity in the auto-run gate. With N ports, you'd need N toggle states × queue states × force_retry states. Global toggle keeps the gate simple: one boolean controls all ports uniformly. Users who want selective execution use the context menu's single-action or force-retry per port.

**Consequences**:
- Single checkbox in Settings dialog controls all ports
- `should_block_auto_run()` checks one global flag, not per-port
- Context menu still offers per-port force_retry and single_action as overrides
- Port-specific behavior is achieved through context menu, not global toggle

---

## DD-015: Step-Based Automation

**Decision**: Each automation step must follow this strict sequence:

```
send command
receive response
cleanup
cooldown
next step
```

**No overlapping commands.** One USSD dial at a time per port.

**Rationale**: Modems cannot handle concurrent USSD sessions. Overlapping commands cause session conflicts, garbled responses, and carrier-side rate limiting. The 4-second cooldown between steps is the minimum safe interval.

**Consequences**:
- `PortWorker._run_loop()` executes steps sequentially
- `DialCooldown.wait()` called after every step completion
- `SessionFence.cancel_session()` called before each new dial
- BoundedSemaphore(2) limits system-wide concurrent injections (DD-015 is per-port; this is system-wide)
- If a step fails, the cooldown still applies before the next attempt
- No parallel USSD dials across ports — each port's worker runs independently

---

## DD-016: Mass Actions

**Decision**: Add two mass actions to the UI:

| Action | Scope | Trigger |
|--------|-------|---------|
| **Mass Reactivation** | All READY ports | Menu button |
| **Mass Number Check** | All READY ports | Menu button |

**Rationale**: Operators manage dozens of ports. Individual port actions are impractical for fleet operations. Mass actions iterate the port registry and enqueue the same action to each qualifying port.

**Consequences**:
- Mass Reactivation: publishes `CMD_RUN_ALL` to EventBus
- Mass Number Check: publishes `CMD_CHECK_ALL` to EventBus (new event type)
- Each port receives the action independently (not batched)
- Failed ports do not block other ports
- UI shows progress bar or port count during mass action
- Mass action respects auto-run toggle (DD-014) — only ports in READY state receive action

---

## DD-017: Database Lookup

**Decision**: Add context menu items for database lookup:

| Menu Item | Action | Target |
|-----------|--------|--------|
| Check NIK in database | Query NIK for selected port's MSISDN | Context menu |
| Check KK in database | Query KK for selected port's NIK | Context menu |

**Rationale**: Operators need to verify database state without triggering USSD dials. Direct DB lookup is instant and non-destructive. Context menu is the natural UI pattern for per-port inspection.

**Consequences**:
- Adds `CMD_DB_LOOKUP_NIK` and `CMD_DB_LOOKUP_KK` event types
- Controller handles event: queries database adapter, publishes result to UI
- Result displayed in a popup or status bar
- No modem interaction — pure database query
- Requires `DatabasePort.lookup_nik()` and `DatabasePort.lookup_kk()` in domain

---

## DD-018: Modem Monitoring

**Decision**: System must detect and respond to:

| Event | Detection Method | UI Update |
|-------|-----------------|-----------|
| COM appearance | Port scan finds new COM | Add row to port table |
| COM disappearance | Port scan loses COM | Mark row as REMOVED |
| Modem online/offline | AT command response | Status icon change |
| SIM inserted/not inserted | CPIN response | Card status column |

**UI and backend must update immediately** — no deferred updates.

**Rationale**: Modem state changes are hardware events. Delayed detection causes operators to take wrong actions (e.g., trying to dial on a disconnected modem). Immediate update prevents wasted effort and user confusion.

**Consequences**:
- Port scan runs every 30 seconds (configurable)
- ModemMonitor checks AT responsiveness every 5 seconds (configurable)
- CPIN check runs in worker thread, publishes status on change
- `MODEM_OFFLINE` event triggers worker to pause automation
- `MODEM_ONLINE` event triggers worker to resume (if auto-run on)
- `PORT_REMOVED` event triggers row removal from UI
- `PORT_ADDED` event triggers row addition to UI
- No animation or transition — instant state change

---

## DD-019: Cooldown Discipline

**Decision**: Every transition between automation steps must have a configurable cooldown.

**Default cooldowns**:

| Transition | Cooldown | Config Key |
|------------|----------|------------|
| DIAL → next DIAL | 4.0s | `dial.cooldown` |
| INJECT → VERIFY | 15.0s | `verification.delay` |
| RESET → STABILIZE | 15.0s | `stabilization.seconds` |
| Session fence min | 0.75s | `ussd.session_fence_min` |
| Session fence quiet | 0.25s | `ussd.session_fence_quiet` |

**Rationale**: Cooldowns prevent carrier-side rate limiting, modem overload, and session conflicts. Making them configurable allows operators to tune for their carrier's tolerance. The defaults are conservative and safe.

**Consequences**:
- All cooldown values in `configs/default.ini` under `[timing]` section
- `DialCooldown` class reads from config at initialization
- Cooldown cannot be bypassed (not even by force_retry)
- Cooldown applies even after failed steps
- UI shows cooldown timer in status column (optional, future)

---

## DD-020: Reference Preservation

**Decision**: GOOD workspace remains immutable. SAIKI becomes the only active rebuild workspace.

**Rationale**: GOOD is the ground truth reference — the source of all extracted rules, audit findings, and architecture decisions. Modifying GOOD would lose provenance and make it impossible to verify SAIKI against the original. SAIKI is the write target for all new code.

**Consequences**:
- GOOD files are READ-ONLY (no edits, no commits)
- SAIKI files are WRITE-ONLY (edits only, no reference back)
- When implementing a module, read from GOOD, write to SAIKI
- If SAIKI diverges from GOOD, that's intentional (audit fixes)
- Git commits happen only in SAIKI
- GOOD's git history is preserved as-is (single commit e7581fe)
- Any question about "what did the original do" is answered by reading GOOD
