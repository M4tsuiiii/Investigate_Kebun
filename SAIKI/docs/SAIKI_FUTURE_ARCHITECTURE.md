# SAIKI FUTURE ARCHITECTURE

Rekomendasi arsitektur target untuk SAIKI, berdasarkan analisis GOOD vs SAIKI.

---

## Subsystem Status

### WorkflowRunner → KEEP

**Alasan**: Arsitektur workflow SAIKI sudah benar. Pemisahan workflow definition, skill execution, dan context management adalah improvement signifikan dari GOOD monolith.

**What to keep**:
- `WorkflowDefinition` (name, description, steps)
- `WorkflowContext` (per-run, thread-safe)
- `WorkflowResult` (success, steps_executed, steps_failed, errors)
- `WorkflowRegistry` (9 workflows registered)
- Sequential execution, first-fail-stops
- `on_step_complete` callback (Sprint 15U bridge)

**Enhancement needed**:
- Tambah `on_workflow_complete` callback untuk final result delivery

---

### SkillFactory → KEEP

**Alasan**: Factory pattern SAIKI (Sprint 15S.2) solved the global skill map overwrite problem. Per-port dependency resolution via `SkillDependencyResolver` adalahsolusi yang benar.

**What to keep**:
- `_SkillFactoryBase` abstract class
- 8 factory classes (`_CekNomorSkillFactory`, etc.)
- `SkillDependencyResolver` (per-port, per-workflow-run)
- `resolve()` method on factories
- `log_binding()` for instrumentation

**Enhancement needed**:
- Tambah factory untuk skills baru (cek_limit, dll)

---

### AutomationEngine → KEEP

**Alasan**: Engine sudah menangani trigger→scheduler→policy→queue→execute pipeline dengan benar. `_on_step_complete` callback (Sprint 15U) menyelesaikan gap result delivery.

**What to keep**:
- `handle_trigger()` — trigger→evaluate→select→enqueue
- `enqueue_workflow()` — manual enqueue
- `_execute_workflow()` — thread execution
- `_on_step_complete()` — skill result → PortWorkerState → EventBus
- `_should_retry()` — retry for reactivate workflows
- Duplicate detection (5s window)
- COMMAND ACCEPTED / COMMAND RESULT split

**Enhancement needed**:
- Port this to use phone cache for NIK/KK lookup
- Add power injection lock (BoundedSemaphore)

---

### PortWorker → KEEP (with enhancements)

**Alasan**: PortWorker SAIKI lebih terstruktur dari GOOD monolith. Pemisahan CpRuntime, UssdRuntime, dan workflow execution adalah benar.

**What to keep**:
- Per-port thread isolation
- Tick loop with priority (reset > single > force > auto > cpin)
- Modem online/offline detection
- Integration with EventBus

**Enhancement needed**:
- Tambah prompt recovery handler
- Tambah CHECKING overlay fix (HR-017)
- Tambah card cycle clear path validation

---

### CpinRuntime → KEEP (with enhancements)

**Alasan**: CpinRuntime SAIKI sudah mengadopsi sebagian besar GOOD logic termasuk stabilization, confirmation polls, dan adaptive polling.

**What to keep**:
- Stabilization rules (UNKNOWN threshold, CHECKING threshold)
- Confirmation polls for transitions
- Buffer flush before queries
- Adaptive polling intervals
- `cpin.transition` event publication

**Enhancement needed**:
- Validasi removal confirmation flow (READY→NOT_READY path)
- Tambah HR-017 (CHECKING overlay stuck fix)

---

### EventBus → KEEP

**Alasan**: EventBus SAIKI sudah benar sebagai single communication channel antara backend dan UI. 26+ event types sudah terdefinisi.

**What to keep**:
- Thread-safe publish/subscribe
- Event enums (UIEvent, CommandEvent)
- `port.data.updated` event (Sprint 15U)

---

### WorkerManager → KEEP

**Alasan**: WorkerManager SAIKI sudah menjadi single source of truth untuk modem lifecycle. Per-port worker registry, factory methods, dan event publication sudah benar.

**What to keep**:
- `create_worker()` / `destroy_worker()`
- Per-port worker registry
- Hardware injection (serial/at_client factories)
- Validation cache
- Modem discovery integration

---

### SkillDependencyResolver → KEEP

**Alasan**: Resolver SAIKI solved the global dependency injection problem. Per-port, per-run resolution adalah benar.

**What to keep**:
- `get_at_client()` — resolve per-port AT client
- `get_ussd_runtime()` — resolve per-port USSD runtime
- `log_binding()` — instrumentation

---

### GOOD Monolith Loop → REMOVE

**Alasan**: Single 2907-line file dengan 4-way CPIN state ownership, dead code, magic values. SAIKI sudah menggantinya dengan modular architecture.

**What to remove**:
- `kebun_reaktivasi(rev).py` sebagai execution engine
- PortWorker inline dalam monolith
- CPIN monitoring inline
- USSD dialing inline
- Business flow execution inline

---

### GOOD CPIN Monitor → MERGE to CpinRuntime

**Alasan**: GOOD CPIN monitor punya beberapa fitur yang SAIKI belum lengkap.

**What to merge**:
- HR-017: CHECKING overlay stuck fix
- Removal confirmation flow (VALIDATE path)
- Final confirmation timeout logic

---

### GOOD USSD Classification → ADD to SAIKI

**Alasan**: GOOD punya 9-tier USSD classification yang lebih robust dari SAIKI. SAIKI hanya basic classify.

**What to add**:
- 9-tier classification (USSD_PAYLOAD → TIMEOUT)
- USSD Intent classification (6 intents)
- Prompt keywords detection (16 keywords)
- Modem notification patterns
- USSD payload completeness check
- Evidence classification (success/processing/tenggang)

---

### GOOD Session Fence → ADD to SAIKI

**Alasan**: GOOD punya session fence logic yang lebih lengkap dari SAIKI `CleanupManager`.

**What to add**:
- AT+CUSD=2 cancel
- 0.75s minimum fence time
- 0.25s quiet time
- 3.0s maximum total fence time
- Stale byte flushing

---

### GOOD Grace Read Window → ADD to SAIKI

**Alasan**: SAIKI belum punya grace read window untuk empty payload responses.

**What to add**:
- 0.5s initial wait
- 3s read window
- Exit on payload complete + 0.8s quiet
- Timeout at 3s

---

### GOOD Phone Cache → ADD to SAIKI

**Alasan**: SAIKI belum punya phone cache. Cache mengurangi USSD charges dan mempercepat flow.

**What to add**:
- `phone_cache[nomor] = {nik, kk, ...}`
- Cache hit → skip NIK lookup
- Cache miss → USSD NIK
- Cache write after successful lookup

---

### GOOD Bypass Flags → ADD to SAIKI

**Alasan**: SAIKI belum punya bypass flags untuk AKTIF/TENGGANG cards.

**What to add**:
- `abai_aktif` flag
- `abai_tenggang` flag
- Logic:如果flags ON → skip injection, langsung DONE

---

### GOOD Format Mode → ADD to SAIKI

**Alasan**: SAIKI belum punya format mode NIK&NIK vs NIK&KK.

**What to add**:
- `format_mode` setting
- `"NIK & KK"` — KK dari database/Telegram
- `"NIK & NIK"` — KK = NIK

---

### GOOD Provisional Success → ADD to SAIKI

**Alasan**: SAIKI belum punya provisional success evaluation untuk injection.

**What to add**:
- 9 conditions → provisional success/waiting/failure
- `USSD_STATUS_ONLY:0` → PROVISIONAL_SUCCESS
- `USSD_EMPTY_PAYLOAD` → PROVISIONAL_WAITING
- Intent classification → provisional mapping

---

### GOOD Power Injection Lock → ADD to SAIKI

**Alasan**: SAIKI belum punya concurrency limit untuk injection.

**What to add**:
- `BoundedSemaphore(2)` — maximum 2 concurrent injections

---

### GOOD Local DB Lookup → ADD to SAIKI

**Alasan**: SAIKI `DbLookup` ada tapi belum terkoneksi ke workflow.

**What to add**:
- Query KK dari `panen_raya` table berdasarkan NIK
- Jika found → skip Telegram lookup
- Jika not found → Telegram lookup (future)

---

### GOOD Audit Log → ADD to SAIKI

**Alasan**: SAIKI belum punya audit log untuk reactivation attempts.

**What to add**:
- `riwayat_reaktivasi` table
- Record: nomor, nik, kk, status_awal, status_akhir, hasil, timestamp

---

### GOOD Status Update Guard → KEEP in CpinRuntime

**Alasan**: Logic sudah ada di `CpinRuntime._apply_stabilization()`. Pastikan lengkap.

**What to validate**:
- OFF→IDLE: only if NOT_INSERTED
- READY→IDLE: only if NOT_INSERTED

---

## Architecture Diagram (Future)

```
┌─────────────────────────────────────────────────────────────┐
│                          GUI Layer                           │
│  MainWindow → PortStatusTable → LogViewer → WorkerMonitor   │
│  SettingsDialog → PortContextMenu                           │
└──────────────────────┬──────────────────────────────────────┘
                       │ EventBus
┌──────────────────────┴──────────────────────────────────────┐
│                       Controller Layer                       │
│  UIController → COMMAND_ROUTES (21 entries)                 │
│  Eligibility checks → Mass command handlers                 │
└──────────────────────┬──────────────────────────────────────┘
                       │ EventBus
┌──────────────────────┴──────────────────────────────────────┐
│                     Automation Layer                         │
│  AutomationEngine → Scheduler → Policy → Queue              │
│  Trigger handling → Duplicate detection → Retry              │
│  _on_step_complete → PortWorkerState → EventBus             │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                      Workflow Layer                          │
│  WorkflowRunner → WorkflowRegistry (9 workflows)            │
│  WorkflowContext → SkillDependencyResolver                  │
│  Sequential execution → First-fail-stops → Cleanup          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                        Skill Layer                           │
│  CekNomor → CekStatus → CekNik → CekKk                     │
│  InjectReaktivasi → VerifyGrace                             │
│  RestartHardware → ResetHardware                             │
│  [NEW] CekLimit → DBLookup → PhoneCache                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                       Worker Layer                           │
│  PortWorker (per-port) → CpinRuntime → UssdRuntime          │
│  PortWorkerState → HardwareRestart → CleanupManager         │
│  [NEW] PromptRecovery → CardCycleManager                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                     Infrastructure Layer                     │
│  SerialAdapter → ATClient → ModemDiscovery → ModemValidator │
│  [NEW] PhoneCache → LocalDB → AuditLog                      │
│  [NEW] SessionFence → GraceReadWindow → BypassFlags         │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Priority

### P0 (Core — implementasi segera)
1. Phone Cache
2. Local DB Lookup (NIK/KK)
3. Bypass Flags (abai_aktif/abai_tenggang)
4. USSD 9-tier Classification
5. Session Fence (lengkap)
6. Grace Read Window

### P1 (Important — implementasi setelah P0)
7. Provisional Success Evaluation
8. Power Injection Lock
9. Prompt Recovery
10. Audit Log (riwayat_reaktivasi)
11. Format Mode (NIK&NIK)
12. HR-017 CHECKING Overlay Fix

### P2 (Nice-to-have — implementasi nanti)
13. Telegram Gateway (real)
14. Report Tab (history viewer)
15. CSV/Excel Export
16. Modem Health Dashboard (AT+CSQ, AT+CMEE)
17. Per-port Settings Override
18. Batch Size Limit
