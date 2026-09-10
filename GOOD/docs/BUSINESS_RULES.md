# Business Rules — GOOD Monolith

Sumber: `app/kebun_reaktivasi(rev).py` (2907 baris) + `worker/` modules.

---

## 1. Workflow Resmi

```text
SIM INSERT
  → CPIN POLL (AT+CPIN?)
  → READY detected
  → Auto-Run Gate Check
  → execute_full_flow()
      ├── STABILISASI (15s)
      ├── CEK NOMOR (*185#) → snapshot_before (nomor, grace_date, raw)
      ├── classify_card_status()
      │     ├── AKTIF/TENGGANG → BYPASS/RECORD → DONE
      │     ├── UNKNOWN → GAGAL
      │     └── HANGUS → continue
      ├── CEK NIK (*888*4444*1#) → extract NIK
      ├── CEK KK (cache → Telegram) → extract KK
      ├── INJECT (*888*89*1*NIK*KK#) → provisional success check
      ├── WAIT 15s
      ├── CEK NOMOR (*185#) → snapshot_after
      └── EVALUASI → SUKSES / TENGGANG / GAGAL
```

---

## 2. Business Rules (BR-IDs)

### BR-001: Auto-Run Gate

**Lokasi**: Line 222-224

Semua kondisi harus terpenuhi:
1. `trigger_mode == "Auto-Run on Insert"`
2. `old_state != "READY"` (belum READY sebelumnya)
3. `not awaiting_card_cycle`

Jika semua pass → `_queue_auto_run()`

### BR-002: Skip Injection for Active/Tenggang

**Lokasi**: Line 1835

```
IF derived_card_status IN ("AKTIF", "TENGGANG"):
    IF bypass_enabled (abai_aktif/abai_tenggang):
        → Status DONE, early exit
    ELSE:
        → record_status_match() to SQLite, Status DONE
    → require_card_cycle()
    → RETURN (no injection)
```

Hanya kartu **HANGUS** yang masuk ke flow reaktivasi.

### BR-003: NIK Required

**Lokasi**: Lines 1850-1889

Sumber NIK (prioritas):
1. Cache: `phone_cache[nomor]["nik"]`
2. USSD: `*888*4444*1#` → regex `(\d{16})`

Jika tidak ditemukan → `GAGAL_CEK_NIK`, `record_reactivation_result()`

### BR-004: KK Required

**Lokasi**: Lines 1893-1911

Sumber KK (prioritas):
1. `format_mode == "NIK & NIK"` → KK = NIK (tidak perlu lookup)
2. Local SQLite: `db_cache[nik]`
3. Telegram: `mock_telegram_gateway_query(nik)`

Jika tidak ditemukan → `GAGAL_KK`, `record_reactivation_result()`

### BR-005/006: Injection + Provisional Success

**Lokasi**: Lines 1916-1963

```python
with power_injection_lock:  # BoundedSemaphore(2)
    send_ussd(*888*89*1*NIK*KK#)
```

Provisional Success jika:
- `USSD_STATUS_ONLY:0` → `PROVISIONAL_SUCCESS`
- `USSD_EMPTY_PAYLOAD` → `PROVISIONAL_WAITING`
- `COMMAND_EXECUTED` → `PROVISIONAL_SUCCESS`
- Intent `SUCCESS_MESSAGE` / `REQUEST_ACCEPTED` → `PROVISIONAL_SUCCESS`
- Intent `MENU_RESPONSE` / `NUMBER_INFO` / `EMPTY` / `UNKNOWN` → `PROVISIONAL_WAITING`

Failure jika:
- Tidak ada provisional AND (timeout/error/partial/tidak ada success evidence) → `GAGAL_INJEKSI`

### BR-007: Mandatory Verification

**Lokasi**: Lines 1577-1587, 1965-1987

```
_wait(15s)  # VERIFICATION_DELAY_SECONDS
send_ussd(*185#, timeout=30s)  # VERIFICATION_READ_TIMEOUT
IF None → return (port disabled/stopped)
IF USSD_STATUS_ONLY → GAGAL_VERIFIKASI
IF PROMPT → recover prompt
→ Extract grace_date, classify_card_status, decide_business_outcome
```

### BR-008: Business Outcome

**Lokasi**: Lines 844-860

```
evaluate_business_outcome(before_grace, after_grace, before_status, after_status, inject_response):
  grace_changed = has_grace_date_changed(before, after)
  evidence = classify_ussd_evidence(inject_response)

  IF grace_changed AND after_status NOT IN {"", "HANGUS", "UNKNOWN"}:
      → "SUCCESS"
  IF NOT grace_changed AND evidence.has_tenggang_evidence:
      → "TENGGANG"
  ELSE:
      → "FAILED"
```

### BR-009: Grace Date Change Detection

**Lokasi**: Lines 830-841

```
IF either value empty or "-": return False
Parse both as YYYY-MM-DD date objects
Return before_date != after_date
```

### BR-010: Card Status Classification

**Lokasi**: Lines 801-827

Prioritas:
1. Evidence "tenggang" dalam response → `TENGGANG`
2. Evidence "hangus" → `HANGUS`
3. Evidence "aktif" → `AKTIF`
4. `days_remaining is None` → `UNKNOWN`
5. `days_remaining > 0` → `AKTIF`
6. `days_remaining >= -30 AND <= 0` → `TENGGANG`
7. `days_remaining < -30` → `HANGUS`

### BR-011: Card Cycle Requirement

**Lokasi**: Lines 197-198, 1847, 2010

- **SET** setelah: AKTIF/TENGGANG bypass/record ATAU SUCCESS
- **CLEAR** hanya pada: `PIN_REQUIRED` ATAU `NOT_INSERTED`
- **TIDAK clear** pada: READY→READY, READY→UNKNOWN, READY→NOT_READY
- **Efek**: Block auto-run sampai SIM dilepas/dimasukkan ulang (physical cycle)

### BR-012: SIM Removal Confirmation

**Lokasi**: Lines 1351-1445

Trigger: `READY → NOT_READY`

```
1. Set pending_removal_confirmation = True, clear card fields
2. Retry confirm: kirim AT+CPIN? lagi
3. IF READY → cancel confirmation
4. IF NOT_INSERTED → confirm removal
5. IF NOT_READY → increment removal_confirmation_count
6. CPIN_MAX_REMOVAL_CONFIRM = 2
```

### BR-013: Final Confirmation After Repeated UNKNOWN

**Lokasi**: Lines 1360-1413

Trigger: `unknown_failure_count >= CPIN_UNKNOWN_THRESHOLD (3)`

```
Final AT+CPIN? query with 3s timeout
Decision:
  - NOT_INSERTED atau CME ERROR 10 → NOT_INSERTED
  - READY → READY
  - Removal candidate error → keep READY
  - Else → keep READY
```

### BR-014: USSD Session Fence

**Lokasi**: Lines 1198-1227

Setiap `_write_ussd_transport_command`:
1. Kirim `AT+CUSD=2` (cancel)
2. Tunggu minimum 0.75s (`USSD_SESSION_FENCE_MIN_SECONDS`)
3. Tunggu tambahan 0.25s quiet (`USSD_SESSION_FENCE_QUIET_SECONDS`)
4. Max 3.0s total (`USSD_SESSION_FENCE_TIMEOUT_SECONDS`)
5. Buang semua byte stale

### BR-015: Dial Cooldown

**Lokasi**: Line 35

```
DIAL_COOLDOWN_SECONDS = 4.0
Enforcement di awal send_ussd():
  remaining = next_dial_allowed_at - now
  IF > 0: sleep(remaining)
Setelah response: next_dial_allowed_at = now + 4.0
```

### BR-016: Verification Timing

**Lokasi**: HUNTER-7

```
VERIFICATION_DELAY_SECONDS = 15.0  (tunggu sebelum verification dial)
VERIFICATION_READ_TIMEOUT = 30.0   (read window untuk verification)
```

### BR-017: Prompt Recovery

**Lokasi**: Lines 1601-1620

```
PROMPT_RECOVERY_MAX = 2
Flow:
  1. Kirim AT+CUSD=2 (cancel)
  2. Flush serial input
  3. IF requeue AND prompt_recovery_count <= 2:
     → increment count, _queue_auto_run(), return
  4. ELSE: clear pending_auto_run, reset count, GAGAL
```

### BR-018: Status Update Guard

**Lokasi**: Lines 149-164

```
Same status → allow
OFF → IDLE: allow HANYA JIKA last_cpin == "NOT_INSERTED"
READY → IDLE: allow HANYA JIKA last_cpin == "NOT_INSERTED"
ELSE: deny dengan log
```

### BR-019: CPIN Unknown Failure Handling

**Lokasi**: Line 1360

```
READY → UNKNOWN: increment unknown_failure_count
IF unknown_failure_count >= CPIN_UNKNOWN_THRESHOLD (3):
  → Final confirmation: flush, sleep(0.2), AT+CPIN?, 3s timeout
```

### BR-020: CPIN Failure Counter for CHECKING UI

**Lokasi**: Line 1464-1467

```
READY → UNKNOWN (bukan pending_removal_confirmation):
  increment cpin_failure_count
  IF cpin_failure_count >= 2:
    → UI: "CHECKING", "CPIN not responding; rechecking..."
```

### BR-021: NIK/KK Validation

```
NIK: exactly 16 digits, re.fullmatch(r"\d{16}")
KK: exactly 16 digits, re.fullmatch(r"\d{16}")
format_mode == "NIK & NIK" → KK = NIK
```

### BR-022: Worker Run Loop Priority Queue

**Lokasi**: Line 1310-1330

Prioritas per iterasi:
1. `reset_requested` (tertinggi) → `_perform_modem_reset()`
2. `single_action` → `execute_single_action()`
3. `force_retry` → `execute_full_flow()` (hanya jika cpin_state == "READY")
4. `pending_auto_run` → `execute_full_flow()`
5. CPIN poll (`AT+CPIN?`) (terendah)

### BR-023: Modem Reset Flow

**Lokasi**: Lines 1068-1110

```
request_modem_reset():
  → reset_requested = True
  → force_retry = False
  → single_action = None
  → pending_auto_run = False

_perform_modem_reset(ser):
  → UI: RESET
  → Close serial
  → Open new serial at current_baud
  → Send ATZ → wait 0.2s → flush
  → Send AT+CFUN=1,1 → wait 1.0s → flush → close
  → current_baud = None
  → pending_auto_run = True (queue auto-run setelah reset)
  → prompt_recovery_count = 0
```

### BR-024: Baud Detection

**Lokasi**: Lines 1282-1302

```
Try BAUD_RATES = [9600, 19200, 115200] secara berurutan:
  Setiap baud: open serial → send "AT\r\n" → wait 0.2s → read → check "OK"
  IF found: set current_baud, break
  IF none: UI: "Modem tidak teraliri daya/mati", sleep(4s)
```

### BR-025: Modem Connection Error

**Lokasi**: Line 1473

```
Exception in run loop:
  → current_baud = None (force re-detection)
  → UI: "Modem error: {e}"
  → sleep(4s)
  → Continue outer loop (retry baud detection)
```

---

## 3. State Machines

### 3A. CPIN State Machine

States: `UNKNOWN`, `READY`, `NOT_INSERTED`, `PIN_REQUIRED`, `NOT_READY`

```
UNKNOWN → READY: _set_status("READY", "+CPIN: READY"), auto-run gate check
UNKNOWN → PIN_REQUIRED: _set_status("PIN LOCK", "+CPIN: PIN/PUK Required")
UNKNOWN → NOT_INSERTED: _set_status("IDLE", "Idle/Standby"), clear fields
READY → (stays READY): prompt_recovery_count = 0, re-set READY status
```

### 3B. Port Status Values

```
IDLE, READY, PROSES, STABILISASI, CHECKING, SUKSES, DONE, GAGAL, OFF, RESET, "PIN LOCK"
```

### 3C. USSD Internal State

```
IDLE → SENDING_COMMAND → WAITING_RESPONSE → VALIDATING_RESPONSE
  → SUCCESS | FAILED | WAITING_CONFIRMATION | EMPTY_PAYLOAD | STATUS_ONLY
```

### 3D. Full Reactivation Flow States

```
1. STABILISASI (15s wait)
2. PROSES (dial *185#)
3. → If nomor found + valid status:
     - AKTIF/TENGGANG → DONE (bypass/record)
     - HANGUS → continue
4. → If HANGUS:
     - CEK NIK (dial *888*4444*1#)
     - CEK KK (cache → Telegram)
     - INJECT *888*89*1*NIK*KK# (with power_injection_lock)
     - WAIT 15s → VERIFY (dial *185#)
     - → SUKSES | TENGGANG | GAGAL
```

---

## 4. Hidden Rules (HR-IDs)

| ID | Rule | Deskripsi |
|----|------|-----------|
| HR-001 | Implicit priority queue | Aksi diproses: reset > single_action > force_retry > auto_run > cpin_poll |
| HR-002 | Force retry cleared before guard | force_retry=False sebelum READY check; non-READY ports kehilangan flag secara silent |
| HR-003 | Single action vs force retry race | Jika keduanya diset pada iterasi yang sama, single_action menang tapi force_retry tetap cleared |
| HR-004 | Awaiting card cycle stuck true | Diset pada SUCCESS/AKTIF/TENGGANG, clear HANYA pada PIN_REQUIRED/NOT_INSERTED |
| HR-005 | Prompt recovery clears pending auto-run | `_recover_from_prompt()` clear pending_auto_run secara unconditional |
| HR-006 | Force retry on disabled ports | restart_all set force_retry pada SEMUA workers; persist sampai port enabled |
| HR-007 | Force retry not retried for non-READY | Cleared tapi execute_full_flow skipped jika cpin_state != READY |
| HR-008 | Same as HR-005 | |
| HR-009 | CPIN_MAX_REMOVAL_CONFIRM not enforced | Konstanta ada (2) tapi removal flow tidak pernah cek terhadap batas |
| HR-010 | Reset clears flags + queues auto-run | request_modem_reset clear semua flags, lalu set pending_auto_run=True setelah reset |
| HR-011 | Magic wait values | 13 timing constants tanpa dokumentasi |
| HR-012 | Telegram gateway is mock | `mock_telegram_gateway_query` selalu return "DATA_TIDAK_DITEMUKAN" |
| HR-013 | NIK&NIK mode KK=NIK | Tidak ada validasi bahwa NIK valid sebagai KK format |
| HR-014 | Grace date 2-format parsing | ISO YYYY-MM-DD dan local DD-MM-YYYY saja |
| HR-015 | Power injection lock | BoundedSemaphore(2) limit 2 concurrent injections |
| HR-016 | Status update guard priority | OFF→IDLE dan READY→IDLE diblokir kecuali last_cpin==NOT_INSERTED |
| HR-017 | CHECKING overlay stuck fix | Saat READY terdeteksi ulang, jika CHECKING → re-render READY |
| HR-018 | CHECKING threshold | Hardcoded >= 2 consecutive UNKNOWN polls |
| HR-019 | Two CPIN failure counters | `cpin_failure_count` (CHECKING UI) dan `unknown_failure_count` (final confirm) |
| HR-020 | NIK/KK validation only at cache write | Tidak ada validasi pada USSD extraction atau manual input |
| HR-021 | Telegram always returns not found | Mock mengabaikan NIK parameter |

---

## 5. Retry Rules Summary

| Mekanisme | Max Retries | Cooldown | Trigger |
|-----------|-------------|----------|---------|
| Prompt Recovery | 2 (`PROMPT_RECOVERY_MAX`) | Immediate requeue | PROMPT_CONFIRMATION |
| USSD Grace Read | 1 window (3s) | 0.5s wait | USSD_EMPTY_PAYLOAD |
| CPIN Removal Confirm | 2 (`CPIN_MAX_REMOVAL_CONFIRM`) | 3s per retry | READY→NOT_READY |
| CPIN Final Confirm | 1 final query | 3s timeout | 3x UNKNOWN |
| USSD Fence | 1 per dial | 0.75-3.0s | Setiap dial |
| DIAL Cooldown | N/A | 4.0s antar dial | Setiap send_ussd |
| Verification Delay | N/A | 15s sebelum dial | _verify_reactivation |

**Tidak ada auto-retry untuk**: injection failure, verification failure, NIK/KK lookup failure.

---

## 6. Configuration Constants

### Named Constants

```python
SECRET_SALT = "PAHLAWAN_KEBUN_REAKTIVASI_2026_FOXCOM_SUPER_KEY"
BAUD_RATES = [9600, 19200, 115200]
DIAL_COOLDOWN_SECONDS = 4.0
USSD_RETRY_DELAY_SECONDS = 8.0
USSD_SESSION_FENCE_MIN_SECONDS = 0.75
USSD_SESSION_FENCE_QUIET_SECONDS = 0.25
USSD_SESSION_FENCE_TIMEOUT_SECONDS = 3.0
CPIN_UNKNOWN_THRESHOLD = 3
CPIN_FINAL_CONFIRM_TIMEOUT = 3.0
CPIN_MAX_REMOVAL_CONFIRM = 2
PROMPT_RECOVERY_MAX = 2
VERIFICATION_DELAY_SECONDS = 15.0
VERIFICATION_READ_TIMEOUT = 30.0
```

### Magic Wait Values (HR-011)

```python
STABILIZATION_SECONDS = 15.0
CPIN_POLL_WINDOW = 3.0
USSD_GRACE_READ_INITIAL_WAIT = 0.5
USSD_GRACE_READ_WINDOW = 3.0
PAYLOAD_QUIET_SECONDS = 0.8
```

### Global Settings

```python
global_settings = {
    "dial_cek_nomor": "*185#",
    "dial_cek_nik": "*888*4444*1#",
    "format_mode": "NIK & KK",         # atau "NIK & NIK"
    "auto_validasi": True,
    "abai_aktif": True,                # bypass kartu AKTIF
    "abai_tenggang": True,             # bypass kartu TENGGANG
    "abai_hangus": False,              # bypass kartu HANGUS (tidak dipakai)
    "tg_api_id": "",
    "tg_api_hash": "",
    "tg_phone": "",
    "tg_target_bot": "@pencari_data_kpu_bot",
    "tg_format_cmd": "/ceknik {NIK}",
    "tg_limit_cmd": "👤 Profile",
    "trigger_mode": "Auto-Run on Insert",  # atau "Manual Trigger Only"
}
```

---

## 7. Database Schema

### Table: `panen_raya` (harvest records)

```sql
CREATE TABLE IF NOT EXISTS panen_raya (
    nomor TEXT PRIMARY KEY,
    nik TEXT,
    kk TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### Table: `status_kartu` (card status records)

```sql
CREATE TABLE IF NOT EXISTS status_kartu (
    nomor TEXT PRIMARY KEY,
    kategori TEXT,
    masa_aktif TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### Table: `riwayat_reaktivasi` (reactivation audit log)

```sql
CREATE TABLE IF NOT EXISTS riwayat_reaktivasi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nomor TEXT,
    nik TEXT,
    kk TEXT,
    status_awal TEXT,
    status_akhir TEXT,
    hasil TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

---

## 8. Enumerations

```python
CPinState: READY, NOT_INSERTED, PIN_REQUIRED, NOT_READY, UNKNOWN
WorkerStatus: OFF, IDLE, READY, PROSES, CHECKING, SUKSES, DONE, GAGAL, PIN_LOCK
Priority: RESET(0), SINGLE_ACTION(1), FORCE_RETRY(2), AUTO_RUN(3), CPIN_POLL(4)
TriggerMode: AUTO_RUN_ON_INSERT, MANUAL_ONLY
FormatMode: NIK_AND_NIK, NIK_AND_KK
CardStatus: AKTIF, TENGGANG, HANGUS, UNKNOWN
BusinessOutcome: SUCCESS, TENGGANG, FAILED
FailureCode: GAGAL_CEK_NIK, GAGAL_KK, GAGAL_INJEKSI, GAGAL_VERIFIKASI, GAGAL
```

---

## 9. Decision Tree Lengkap

```
SIM INSERT
  │
  ▼
CPIN POLL → READY detected
  │
  ▼
Auto-Run Gate Check:
  ├── trigger_mode != "Auto-Run" → MANUAL ONLY
  ├── old_state == READY → NO AUTO-RUN
  ├── awaiting_card_cycle == True → BLOCKED
  └── ALL PASS → pending_auto_run = True
        │
        ▼
    execute_full_flow()
        │
        ├── STABILISASI 15s
        ├── *185# DIAL → extract nomor + grace_date
        │     ├── STATUS_ONLY → GAGAL
        │     ├── PROMPT → RECOVER + requeue
        │     ├── TIMEOUT/ERROR/PARTIAL/NOT_INSERTED → GAGAL
        │     └── PAYLOAD → EXTRACT
        │
        ├── classify_card_status(grace_date, response)
        │     ├── AKTIF/TENGGANG:
        │     │     ├── bypass ON → DONE + require_card_cycle()
        │     │     └── bypass OFF → record_status_match + DONE + require_card_cycle()
        │     ├── UNKNOWN → GAGAL
        │     └── HANGUS → continue
        │
        ├── NIK LOOKUP
        │     ├── CACHE HIT → proceed
        │     └── CACHE MISS → *888*4444*1# → extract NIK
        │           ├── FAIL → GAGAL_CEK_NIK
        │           └── SUCCESS → KK LOOKUP
        │
        ├── KK LOOKUP
        │     ├── NIK&NIK MODE → KK = NIK
        │     ├── LOCAL DB HIT → proceed
        │     ├── TELEGRAM QUERY → success/fail
        │     └── FAIL → GAGAL_KK
        │
        ├── INJECT *888*89*1*NIK*KK#
        │     ├── PROVISIONAL SUCCESS → VERIFY
        │     └── NO PROVISIONAL + NO SUCCESS → GAGAL_INJEKSI
        │
        ├── VERIFY (15s delay + *185# 30s timeout)
        │     ├── STATUS_ONLY → GAGAL_VERIFIKASI
        │     ├── PROMPT → recover
        │     └── PAYLOAD → evaluate outcome
        │
        └── BUSINESS OUTCOME
              ├── SUCCESS → SUKSES + harvest + require_card_cycle()
              ├── TENGGANG → DONE + record
              └── FAILED → GAGAL
```
