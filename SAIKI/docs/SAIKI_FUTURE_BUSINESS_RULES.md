# SAIKI FUTURE BUSINESS RULES

Kumpulan business rules final yang HARUS dimiliki SAIKI.
Digabung dari GOOD (source of truth) + SAIKI (arsitektur baru).

---

## SIM Rules

### BR-SIM-001: SIM State Detection
SIM state ditentukan oleh response `AT+CPIN?`:
- `+CPIN: READY` → READY
- `+CPIN: NOT READY` → NOT_READY (dicek SEBELUM "READY" untuk hindari substring false positive)
- `+CPIN: SIM PIN` / `+CPIN: SIM PUK` → PIN_REQUIRED
- `NOT INSERTED` atau `+CME ERROR: 10` → NOT_INSERTED
- Lainnya → UNKNOWN

### BR-SIM-002: SIM Ready for Operations
SIM hanya bisa diproses jika state = `READY`. Operasi lain (NIK/KK/inject/verify) DILARANG jika state bukan READY.

### BR-SIM-003: SIM Removal Confirmation
Trigger: `READY → NOT_READY`
1. Set `pending_removal_confirmation = True`, clear card fields
2. Retry: kirim `AT+CPIN?` lagi
3. `READY` → cancel confirmation
4. `NOT_INSERTED` → confirm removal
5. `NOT_READY` → increment counter
6. Max retry: `CPIN_MAX_REMOVAL_CONFIRM = 2`

---

## CPIN Rules

### BR-CPIN-001: CPIN Polling
`AT+CPIN?` dikirim secara periodik:
- Interval: 1.0s (`CPIN_POLL_INTERVAL`)
- Timeout: 3.0s (`CPIN_POLL_TIMEOUT`)
- Buffer flush sebelum setiap query

### BR-CPIN-002: UNKNOWN Threshold
Jika `UNKNOWN` muncul ≥3 kali berturut-turut (`CPIN_UNKNOWN_THRESHOLD`):
1. Flush buffer
2. Sleep 0.2s
3. Kirim `AT+CPIN?` dengan timeout 3.0s
4. Decision: `NOT_INSERTED`/`CME ERROR 10` → NOT_INSERTED; `READY` → READY; lainnya → tetap READY

### BR-CPIN-003: CHECKING Threshold
Jika `UNKNOWN` muncul ≥2 kali berturut-turut (`CPIN_CHECKING_THRESHOLD`):
- UI menampilkan status `CHECKING` dengan pesan "CPIN not responding; rechecking..."

### BR-CPIN-004: Counter Reset
Semua counter (`unknown_failure_count`, `cpin_failure_count`, `prompt_recovery_count`) direset saat:
- Transisi ke `READY`
- Transisi ke `NOT_INSERTED`
- Transisi ke `PIN_REQUIRED`
- Reset modem selesai

### BR-CPIN-005: Adaptive Polling
Interval polling menyesuaikan state:
- `READY`: 3.0s
- `NOT_READY`: 0.5s
- `UNKNOWN`: 1.0s

---

## USSD Rules

### BR-USSD-001: Dial Cooldown
Waktu minimum antar USSD dial: `DIAL_COOLDOWN_SECONDS = 4.0s`
- Enforce di awal `send_ussd()`
- Setelah response: `next_dial_allowed_at = now + 4.0`

### BR-USSD-002: Session Fence
Sebelum setiap dial baru, batalkan sesi USSD sebelumnya:
1. Kirim `AT+CUSD=2` (cancel)
2. Tunggu minimum 0.75s (`USSD_SESSION_FENCE_MIN_SECONDS`)
3. Tunggu tambahan 0.25s quiet (`USSD_SESSION_FENCE_QUIET_SECONDS`)
4. Maximum 3.0s total (`USSD_SESSION_FENCE_TIMEOUT_SECONDS`)
5. Buang semua byte stale

### BR-USSD-003: Grace Read Window
Jika response awal `USSD_EMPTY_PAYLOAD`:
1. Tunggu 0.5s (`USSD_GRACE_READ_INITIAL_WAIT`)
2. Read hingga 3s (`USSD_GRACE_READ_WINDOW`)
3. Exit: payload complete + 0.8s quiet ATAU 3s timeout
4. Jika payload ditemukan → `USSD_PAYLOAD`, else → `USSD_EMPTY_PAYLOAD`

### BR-USSD-004: Prompt Recovery
Jika response = `PROMPT_CONFIRMATION`:
1. Kirim `AT+CUSD=2` (cancel)
2. Flush serial input
3. Jika requeue AND `prompt_recovery_count ≤ 2`:
   - Increment count, queue auto-run
4. ELSE: clear pending_auto_run, reset count, GAGAL

### BR-USSD-005: 9-Tier Classification
Response USSD diklasifikasikan secara berurutan:
1. `USSD_PAYLOAD` — ada quoted payload non-empty
2. `USSD_EMPTY_PAYLOAD` — empty quoted
3. `USSD_STATUS_ONLY` — hanya status code
4. `PARTIAL_RESPONSE` — unclosed payload
5. `PROMPT_CONFIRMATION` — prompt keywords detected
6. `ERROR` — +CME ERROR / +CMS ERROR
7. `AT_OK` — OK tanpa CUSD
8. `COMMAND_ECHO` — AT+CUSD= echo
9. `MODEM_NOTIFICATION` — +WIND/+MREG/+CPIN/+CREG/+CGREG/+CIEV/+CSQ
10. `WAITING_RESPONSE` — lainnya
11. `TIMEOUT` — tidak ada text

### BR-USSD-006: USSD Codes
| Kode | Purpose | Configurable |
|------|---------|-------------|
| `*185#` | Cek Nomor / Cek Status | Ya (`dial_cek_nomor`) |
| `*888*4444*1#` | Cek NIK | Ya (`dial_cek_nik`) |
| `*888*89*1*{NIK}*{KK}#` | Reaktivasi Injection | Template |
| Configurable | Nomor USSD code | Ya (`number_ussd_code`) |

---

## Workflow Rules

### BR-WF-001: Sequential Execution
Workflow dijalankan step-by-step, urutan sesuai definisi.

### BR-WF-002: First-Fail-Stops
Jika satu step gagal, workflow berhenti. Step berikutnya TIDAK dijalankan.

### BR-WF-003: No Inter-Skill Calls
Setiap skill bersifat independen. Skill TIDAK BOLEH memanggil skill lain.

### BR-WF-004: Cleanup Between Steps
Antara step: close_session → 0.5s → clear_buffer → cooldown (4.0s)

### BR-WF-005: Auto-Run Sequence
Ketika auto-run trigger:
1. Cek Nomor (`*185#`) → extract nomor + grace_date + card_status (3 data sekaligus)
2. Cek Status (`AT+CPIN?`) → SIM state
3. Cek NIK (`*888*4444*1#`) → extract NIK dari response
4. Cek KK (cache → local DB → Telegram → format_mode NIK&NIK → GAGAL)
5. Reaktivasi (`*888*89*1*NIK*KK#`) → classify response by card status
6. Verifikasi (`*185#`) → extract grace_date_after → compare with grace_date_before
7. Evaluasi outcome: SUKSES jika grace_date BERUBAH

### BR-WF-006: Two Workflow Types
| Workflow | Description | Steps |
|----------|-------------|-------|
| **FULL REACTIVATION** | Cek nomor → cek nik → match kk → reactivation → success validation | CekNomor → CekNik → CekKk → Inject → VerifyGrace |
| **REACTIVASI** | Sending reactivation command → cek nomor dan status sebagai validator | Inject → VerifyGrace |

### BR-WF-007: Success Criteria (from PENUNJANG.md)
Reaktivasi dinyatakan:
- **Sukses**: jika ada perubahan grace date setelah melakukan reaktivasi (`grace_date_before ≠ grace_date_after`)
- **Gagal**: jika tidak ada perubahan grace date (`grace_date_before = grace_date_after`)

### BR-WF-008: Thread Isolation
Setiap workflow run memiliki `WorkflowContext` sendiri. Tidak sharing antar port.

### BR-WF-009: Max Concurrent
Maximum 2 workflow berjalan bersamaan (`max_concurrent=2`).

### BR-WF-010: Dedup Window
Trigger yang sama untuk port yang sama dalam 5 detik → skip.

### BR-WF-011: Retry Max 1
Retry hanya untuk `reactivate_fast` dan `reactivate_full`. Maximum 1 retry.

### BR-WF-012: Result Propagation
Setelah setiap skill, hasilnya dipetakan ke PortWorkerState dan dipublikasikan via EventBus.

---

## Phone Cache Rules

### BR-CACHE-001: Cache Structure
```
phone_cache[nomor] = {
    "nik": "...",
    "kk": "...",
    "nomor": "...",
}
```

### BR-CACHE-002: Cache Hit → Skip NIK Lookup
Jika nomor ada di cache, NIK sudah diketahui. Tidak perlu USSD `*888*4444*1#`.

### BR-CACHE-003: Cache Miss → USSD NIK
Jika nomor tidak ada di cache, kirim USSD `*888*4444*1#` untuk ambil NIK.

### BR-CACHE-004: Cache Write After NIK Lookup
Setelah NIK berhasil diambil via USSD, simpan ke cache.

### BR-CACHE-005: Cache Write After KK Lookup
Setelah KK berhasil diambil, simpan ke cache.

---

## Telegram Rules

### BR-TG-001: Telegram Gateway (Future)
Telegram gateway akan digunakan untuk query KK berdasarkan NIK.
- Status: Belum diimplementasi (GOOD hanya mock)
- Priority: P2 (setelah core functionality selesai)

---

## Port Lifecycle Rules

### BR-PL-001: Port Discovery
USB serial port terdeteksi oleh `ModemDiscovery`:
1. Enumerate semua COM port
2. Filter berdasarkan HWID/VID (Quectel M26)
3. Probe dengan `AT\r\n` di [115200, 9600, 57600, 38400, 19200, 4800]
4. Jika OK → VALID_MODEM → buat worker

### BR-PL-002: Port Registration
Worker dibuat untuk setiap VALID_MODEM:
1. Create `SerialAdapter` (atau factory)
2. Create `ATClient`
3. Create `PortWorker`
4. Send `ATE0` (disable echo)
5. Start `CpinRuntime`

### BR-PL-003: Port Exclusion
User bisa exclude port dari operasi:
- Port yang di-excluded tidak mendapat trigger
- Workflow yang sudah queued dibatalkan
- Force retry tetap persist (HR-006)

### BR-PL-004: Port Removal
USB unplug → destroy worker → rescan

### BR-PL-005: Numeric Sorting
Port table selalu diurutkan secara numerik (COM9 < COM10 < COM101).

---

## Reset Rules

### BR-RS-001: Reset Sequence
1. Stop `CpinRuntime` (pause polling)
2. Close serial connection
3. Tunggu `STABILIZATION_SECONDS = 15.0s`
4. Buka ulang serial connection
5. Start `CpinRuntime` (resume polling)
6. Check modem (`check_modem()`)
7. Detect SIM (`AT+CPIN?`)

### BR-RS-002: Reset Clears All Flags
`request_reset()` menghapus:
- `force_retry = False`
- `single_action = None`
- `pending_auto_run = False`

### BR-RS-003: Auto-Run After Reset
Setelah reset berhasil, queue auto-run untuk port tersebut.

### BR-RS-004: Serial Ownership
Hanya satu pemilik serial dalam satu waktu:
- `CpinRuntime` berhenti sebelum reset
- Reset mengambil alih serial
- `CpinRuntime` resume setelah reset selesai

---

## Auto Run Rules

### BR-AR-001: Default State
Auto-run default: `OFF` (`auto_run_enabled = False`)

### BR-AR-002: Trigger Mode
- `"Auto-Run on Insert"` — otomatis jalan saat READY terdeteksi
- `"Manual Trigger Only"` — harus user klik manual

### BR-AR-003: Gating Conditions
Auto-run HANYA dilakukan jika SEMUA kondisi terpenuhi:
1. `trigger_mode == "Auto-Run on Insert"`
2. `old_state != "READY"` (belum READY sebelumnya)
3. `not awaiting_card_cycle`
4. `modem_online == True`
5. Port tidak excluded
6. Tidak ada workflow lain yang running untuk port ini

### BR-AR-004: Card Cycle Block
`awaiting_card_cycle = True` memblok auto-run. Clear HANYA saat:
- `PIN_REQUIRED` terdeteksi
- `NOT_INSERTED` terdeteksi

### BR-AR-005: Auto-Run Sequence
Ketika auto-run trigger:
1. Cek Nomor (`*185#`) → snapshot_before: nomor + grace_date_before + card_status
2. Cek Status (`AT+CPIN?`) → SIM state
3. Cek NIK (`*888*4444*1#`) → extract NIK
4. Cek KK (cache → local DB → Telegram → format_mode → GAGAL)
5. Reaktivasi (`*888*89*1*NIK*KK#`) → classify response (HANGUS/TENGGANG/AKTIF)
6. Verifikasi (`*185#`) → extract grace_date_after
7. Evaluasi: SUKSES jika `grace_date_before ≠ grace_date_after`

---

## Result Delivery Rules

### BR-RD-001: Skill Result → PortWorkerState
Setelah setiap skill berhasil, hasilnya dipetakan:
- `number` → `PortWorkerState.nomor`
- `nik` → `PortWorkerState.nik`
- `kk` → `PortWorkerState.kk`
- `grace_date` → `PortWorkerState.masa_aktif`
- `cpin_state` → RESPON column
- `card_status` → RESPON column

### BR-RD-002: EventBus Publication
Perubahan state dipublikasikan via EventBus:
- Event: `port.data.updated`
- Payload: `{port, nomor, nik, kk, status, respon, masa_aktif}`

### BR-RD-003: Controller Forwarding
`UIController._on_port_data_updated()` meneruskan ke `UIEvent.PORT_UPDATE`.

### BR-RD-004: GUI Update
`GUIApplication._on_port_update()` menulis ke port table:
- `nomor`, `nik`, `kk`, `masa_aktif`, `respon`, `status`

### BR-RD-005: No Overwrite on Completion
`automation.completed` hanya set `status=IDLE`. TIDAK overwrite data columns.

---

## Eligibility Rules

### BR-EL-001: Per-Port Command Eligibility
Command per-port hanya bisa dijalankan jika:
1. Worker exists untuk port
2. Port tidak excluded
3. Worker alive (thread running)
4. Modem online
5. SIM state memadai (tergantung command):
   - Cek Nomor/Status/NIK/KK: SIM harus READY
   - Restart/Reset: modem harus online
   - Reprocess: worker harus alive
6. Serial terhubung

---

## Bypass Rules (from GOOD)

### BR-BYP-001: abai_aktif
Jika `abai_aktif = True`:
- Kartu AKTIF → langsung DONE, skip injection
- Tidak perlu verifikasi

### BR-BYP-002: abai_tenggang
Jika `abai_tenggang = True`:
- Kartu TENGGANG → langsung DONE, skip injection
- Tidak perlu verifikasi

### BR-BYP-003: Format Mode
- `"NIK & KK"` — KK diambil dari database/Telegram
- `"NIK & NIK"` — KK = NIK (tidak perlu lookup terpisah)

---

## Verification Rules

### BR-VR-001: Mandatory Verification
Setelah injection, SELALU verifikasi:
1. Tunggu `VERIFICATION_DELAY_SECONDS = 15.0s`
2. Kirim `*185#` dengan timeout `VERIFICATION_READ_TIMEOUT = 30.0s`
3. Extract `grace_date_after` dari response yang sama dengan CekNomor
4. Compare `grace_date_before` vs `grace_date_after`

### BR-VR-002: Provisional Success
Injection dianggap provisional success jika:
- `USSD_STATUS_ONLY` dengan status 0
- `USSD_EMPTY_PAYLOAD`
- `COMMAND_EXECUTED`
- Intent = `SUCCESS_MESSAGE` atau `REQUEST_ACCEPTED`

### BR-VR-003: Business Outcome
| Outcome | Kondisi |
|---------|---------|
| **SUCCESS** | Grace date berubah (`grace_date_before ≠ grace_date_after`) |
| **TENGGANG** | Grace date tidak berubah + ada tenggang evidence |
| **FAILED** | Grace date tidak berubah + tidak ada tenggang evidence |

### BR-VR-004: Card Status Response Mapping (from PENUNJANG.md)
| Card Status | Injection Response | Meaning |
|------------|-------------------|---------|
| **HANGUS** | `"Permintaan kamu sedang di proses, cek SMS untuk mengetahui status permintaan kamu"` | Request accepted, processing |
| **TENGGANG** | `"Nomor 08575xxxxxxx sedang dalam masa tenggang. SEGERA lalukan isi ulang/beli paket agar nomor tetap AKTIF..."` | Already in grace period, no injection needed |
| **AKTIF** | `"Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus"` | Rejected, card is active |

---

## Concurrency Rules

### BR-CQ-001: Power Injection Lock
Maximum 2 injection bersamaan: `BoundedSemaphore(2)`

### BR-CQ-002: Serial Ownership
Hanya satu operasi dalam satu waktu per port:
- CPIN polling berhenti saat reset
- Workflow berjalan satu per satu per port
