# Command Catalog — GOOD Monolith

Sumber: `app/kebun_reaktivasi(rev).py` (2907 baris) + `worker/` modules.

---

## 1. AT Commands

### 1.1 AT — Baud Rate Detection

| Field | Value |
|-------|-------|
| **Command** | `AT\r\n` |
| **Purpose** | Deteksi baud rate — test apakah modem merespons |
| **Lokasi** | Line 1287 |
| **Timeout** | 0.2s |
| **Expected Response** | `OK` |
| **Usage** | Dikirim di setiap baud rate saat startup: `[9600, 19200, 115200]` |
| **On Success** | Simpan `current_baud`, lanjut ke `ATE0` |
| **On Failure** | Coba baud berikutnya. Jika semua gagal: `"Modem tidak teraliri daya/mati"`, sleep 4s |

### 1.2 ATE0 — Disable Echo

| Field | Value |
|-------|-------|
| **Command** | `ATE0\r\n` |
| **Purpose** | Matikan echo setelah koneksi terbentuk |
| **Lokasi** | Line 1306 |
| **Timeout** | Default AT timeout |
| **Expected Response** | `OK` |
| **Usage** | Dikirim sekali setelah baud rate terdeteksi |

### 1.3 AT+CPIN? — SIM Card State Polling

| Field | Value |
|-------|-------|
| **Command** | `AT+CPIN?\r\n` |
| **Purpose** | Periksa status SIM card (periodic polling) |
| **Lokasi** | Line 1334 |
| **Timeout** | `CPIN_POLL_TIMEOUT = 3.0s` |
| **Poll Interval** | `CPIN_POLL_INTERVAL = 1.0s` |
| **Expected Response** | `+CPIN: READY`, `+CPIN: NOT INSERTED`, `+CPIN: SIM PIN`, `+CPIN: NOT READY` |
| **Usage** | Dikirim secara periodik di worker run loop sebagai aksi terendah (prioritas 4) |

### 1.4 AT+CPIN? — Final Confirmation Query

| Field | Value |
|-------|-------|
| **Command** | `AT+CPIN?\r\n` |
| **Purpose** | Konfirmasi akhir setelah 3x UNKNOWN berturut-turut |
| **Lokasi** | Line 1369 |
| **Timeout** | `CPIN_FINAL_CONFIRM_TIMEOUT = 3.0s` |
| **Expected Response** | `+CPIN: READY`, `+CPIN: NOT INSERTED`, atau `+CME ERROR: 10` |
| **Usage** | Hanya dikirim jika `unknown_failure_count >= CPIN_UNKNOWN_THRESHOLD (3)` |

### 1.5 AT+CPIN? — Removal Confirmation Retry

| Field | Value |
|-------|-------|
| **Command** | `AT+CPIN?\r\n` |
| **Purpose** | Konfirmasi ulang saat flow removal confirmation aktif |
| **Lokasi** | Line 1420 |
| **Timeout** | 3s |
| **Expected Response** | `+CPIN: READY`, `+CPIN: NOT INSERTED`, atau `+CPIN: NOT READY` |
| **Usage** | Dikirim saat `pending_removal_confirmation == True` |

### 1.6 ATZ — Modem Soft Reset

| Field | Value |
|-------|-------|
| **Command** | `ATZ\r\n` |
| **Purpose** | Reset modem ke konfigurasi default |
| **Lokasi** | Line 1091 |
| **Timeout** | 0.2s wait setelah kirim |
| **Expected Response** | `OK` |
| **Usage** | Bagian dari `_perform_modem_reset()`, dikirim sebelum `AT+CFUN=1,1` |

### 1.7 AT+CFUN=1,1 — Full Radio Restart

| Field | Value |
|-------|-------|
| **Command** | `AT+CFUN=1,1\r\n` |
| **Purpose** | Restart radio modem secara penuh |
| **Lokasi** | Line 1095 |
| **Timeout** | 1.0s wait setelah kirim |
| **Expected Response** | `OK` |
| **Usage** | Bagian dari `_perform_modem_reset()`, dikirim setelah `ATZ` |

### 1.8 AT+CUSD=1,"{cmd}",15 — Send USSD Command

| Field | Value |
|-------|-------|
| **Command** | `AT+CUSD=1,"{kode_ussd}",15\r\n` |
| **Purpose** | Kirim perintah USSD ke operator |
| **Lokasi** | Line 1237 |
| **Timeout** | Bervariasi per context (3-30 detik) |
| **Expected Response** | `+CUSD: N,"<payload>"` |
| **Usage** | Fungsi `_write_ussd_transport_command()`. `{kode_ussd}` diganti dengan kode USSD aktual |

### 1.9 AT+CUSD=2 — Cancel USSD Session

| Field | Value |
|-------|-------|
| **Command** | `AT+CUSD=2\r\n` |
| **Purpose** | Batalkan sesi USSD aktif (fence) |
| **Lokasi** | Line 1206, 1603 |
| **Timeout** | Bagian dari fence timeout (0.75-3.0s) |
| **Expected Response** | `OK` atau tidak ada |
| **Usage** | Dikirim sebelum setiap dial baru (fence) DAN saat recovery dari prompt |

---

## 2. USSD Codes

### 2.1 *185# — Cek Nomor

| Field | Value |
|-------|-------|
| **Kode** | `*185#` |
| **Purpose** | Cek nomor telepon + Grace Date |
| **Variabel** | `global_settings["dial_cek_nomor"]` |
| **Default** | `"*185#"` |
| **Lokasi** | Line 1503-1542 (execute_full_flow), Line 1644 (execute_single_action) |
| **Timeout** | `VERIFICATION_READ_TIMEOUT = 30.0s` |
| **Expected Response** | Teks berisi nomor telepon (08xxxxxxxxx) dan tanggal grace |
| **Parse** | Regex `(08\d{9,11})` untuk nomor, `extract_grace_date()` untuk tanggal |
| **Usage** | Dikirim 2x dalam full flow: snapshot_before dan snapshot_after (verifikasi) |

### 2.2 *888*4444*1# — Cek NIK

| Field | Value |
|-------|-------|
| **Kode** | `*888*4444*1#` |
| **Purpose** | Ambil NIK dari operator |
| **Variabel** | `global_settings["dial_cek_nik"]` |
| **Default** | `"*888*4444*1#"` |
| **Lokasi** | Line 1878 (execute_full_flow), Line 1665 (execute_single_action) |
| **Timeout** | `VERIFICATION_READ_TIMEOUT = 30.0s` |
| **Expected Response** | Teks berisi NIK 16 digit |
| **Parse** | Regex `(\d{16})` |
| **Usage** | Hanya dikirim jika NIK tidak ada di cache |

### 2.3 *888*89*1*{NIK}*{KK}# — Reaktivasi Injection

| Field | Value |
|-------|-------|
| **Kode** | `*888*89*1*{NIK}*{KK}#` |
| **Purpose** | Kirim perintah reaktivasi ke operator |
| **Template** | `build_reaktivasi_command(nik, kk)` |
| **Lokasi** | Line 1916-1963 (execute_full_flow) |
| **Timeout** | Default USSD timeout |
| **Expected Response** | Konfirmasi dari operator (tekstual) |
| **Parse** | `classify_ussd_evidence()` untuk cek success evidence |
| **Concurrency** | Dibatasi oleh `power_injection_lock = BoundedSemaphore(2)` |
| **Usage** | Hanya dikirim setelah NIK dan KK ditemukan, dan kartu HANGUS |

---

## 3. Command → Skill Mapping (SAIKI)

| Command AT/USSD | SAIKI Skill | Workflow |
|----------------|-------------|----------|
| `AT+CNUM` | `cek_nomor` | `check_number`, `check_data`, `reactivate_full` |
| `AT+CPIN?` | `cek_status` | `check_status`, `reactivate_full`, `reset_hardware` |
| `ATZ` | `restart_hardware` | `hardware_restart` |
| close/reopen serial + `AT+CPIN?` | `reset_hardware` | `hardware_reset` |
| USSD `*185#` | `cek_nik` | `check_nik`, `check_data`, `reactivate_full` |
| USSD `*185#` | `cek_kk` | `check_kk`, `check_data`, `reactivate_full` |
| USSD configurable | `inject_reaktivasi` | `reactivate_fast`, `reactivate_full` |
| USSD `*185#` | `verify_grace` | `reactivate_fast`, `reactivate_full` |

---

## 4. AT Command Response Format

### +CNUM — Nomor Telepon

```
Format:  +CNUM: "","<nomor>",<type>
Contoh:  +CNUM: "","081234567890",129
Parse:   regex r'\+CNUM:\s*"",\s*"(\d+)"'
```

### +CPIN? — Status SIM

```
Format:  +CPIN: <STATE>
Contoh:  +CNUM: READY
         +CPIN: NOT INSERTED
         +CPIN: SIM PIN
         +CPIN: NOT READY
         +CME ERROR: 10

Mapping:
  "+CPIN: NOT READY" → NOT_READY  (dicek DULU sebelum READY)
  "+CPIN: READY"     → READY
  Contains "PIN"/"PUK" → PIN_REQUIRED
  "NOT INSERTED" atau "+CME ERROR: 10" → NOT_INSERTED
  Else → UNKNOWN
```

### +CUSD — USSD Response

```
Format:  +CUSD: <N>,"<payload>"
         +CUSD: <N>,""
         +CUSD: <N>

Contoh:
  +CUSD: 0,"Nomor Anda: 081234567890\nMasa aktif: 12/12/2026"
  +CUSD: 1,""
  +CUSD: 2

Classification priority:
  1. +CUSD: N,"<payload>" non-empty → USSD_PAYLOAD
  2. +CUSD: N,"" → USSD_EMPTY_PAYLOAD
  3. +CUSD: N (tanpa quotes) → USSD_STATUS_ONLY
  4. +CUSD: N,"<unclosed → PARTIAL_RESPONSE
  5. Prompt keywords → PROMPT_CONFIRMATION
  6. +CME ERROR / CMS ERROR → ERROR
  7. AT OK (tanpa CUSD) → AT_OK
  8. AT+CUSD= echo → COMMAND_ECHO
  9. +WIND:/+CPIN:/+CREG: → MODEM_NOTIFICATION
  10. Else → WAITING_RESPONSE
  11. No text → TIMEOUT
```

### OK — AT Response

```
Format:  OK
Digunakan: ATZ response, ATE0 response, AT response (baud detection)
```

---

## 5. Serial Write Format

Semua AT commands dikirim dengan suffix `\r\n`:

```python
ser.write(b"AT+CPIN?\r\n")    # AT command
ser.write(b"AT+CUSD=1,\"*185#\",15\r\n")  # USSD command
ser.write(b"AT+CUSD=2\r\n")   # Cancel USSD
```

---

## 6. Timing Constants

| Konstanta | Nilai | Penggunaan |
|-----------|-------|------------|
| `DIAL_COOLDOWN_SECONDS` | 4.0 | Waktu minimum antar USSD dial |
| `USSD_SESSION_FENCE_MIN_SECONDS` | 0.75 | Waktu minimum fence sebelum dial baru |
| `USSD_SESSION_FENCE_QUIET_SECONDS` | 0.25 | Waktu tambahan quiet setelah fence |
| `USSD_SESSION_FENCE_TIMEOUT_SECONDS` | 3.0 | Maximum total fence time |
| `VERIFICATION_DELAY_SECONDS` | 15.0 | Tunggu sebelum verification dial |
| `VERIFICATION_READ_TIMEOUT` | 30.0 | Read window untuk verification |
| `CPIN_POLL_INTERVAL` | 1.0 | Interval antar CPIN poll |
| `CPIN_POLL_TIMEOUT` | 3.0 | Timeout per CPIN poll |
| `CPIN_FINAL_CONFIRM_TIMEOUT` | 3.0 | Timeout untuk final confirmation |
| `STABILIZATION_SECONDS` | 15.0 | Tunggu setelah reset sebelum operasi |
| `CPIN_UNKNOWN_THRESHOLD` | 3 | Jumlah UNKNOWN berturut-turut sebelum final confirm |
| `CPIN_MAX_REMOVAL_CONFIRM` | 2 | Max removal confirmation retries |
| `PROMPT_RECOVERY_MAX` | 2 | Max prompt recovery retries |
| `USSD_GRACE_READ_INITIAL_WAIT` | 0.5 | Tunggu awal sebelum grace read |
| `USSD_GRACE_READ_WINDOW` | 3.0 | Window untuk grace read |
| `PAYLOAD_QUIET_SECONDS` | 0.8 | Tunggu quiet setelah payload ditemukan |
