# COMMAND RESPONSE MATRIX

Lengkap semua command modem, response yang diharapkan, parser, dan destination field.

---

## 1. AT Commands

| Feature | Command | Expected Response | Parser | Destination Field |
|---------|---------|-------------------|--------|-------------------|
| **Baud Detection** | `AT\r\n` | `OK` | String contains "OK" | `current_baud` |
| **Disable Echo** | `ATE0\r\n` | `OK` | String contains "OK" | — |
| **SIM State Poll** | `AT+CPIN?` | `+CPIN: READY` | `parse_cpin_response()` | `cpin_state`, `status`, `respon` |
| **SIM State Poll** | `AT+CPIN?` | `+CPIN: NOT INSERTED` | `parse_cpin_response()` | `cpin_state`, `status` |
| **SIM State Poll** | `AT+CPIN?` | `+CPIN: SIM PIN` | `parse_cpin_response()` | `cpin_state`, `status` |
| **SIM State Poll** | `AT+CPIN?` | `+CPIN: NOT READY` | `parse_cpin_response()` | `cpin_state`, `status` |
| **SIM State Poll** | `AT+CPIN?` | `+CME ERROR: 10` | `parse_cpin_response()` | `cpin_state`, `status` |
| **SIM State Poll** | `AT+CPIN?` | (timeout/no response) | `parse_cpin_response()` | `cpin_state` = UNKNOWN |
| **Phone Number** | `AT+CNUM` | `+CNUM: "","081234567890",129` | `_parse_cnum()` regex `r'\+CNUM:\s*"",\s*"(\d+)"'` | `nomor` |
| **Phone Number** | `AT+CNUM` | (no number in response) | `_parse_cnum()` returns None | — (try USSD fallback) |
| **Modem Reset** | `ATZ` | `OK` | String contains "OK" | `restart_sent` |
| **Full Radio Restart** | `AT+CFUN=1,1` | `OK` | String contains "OK" | — |
| **Cancel USSD** | `AT+CUSD=2` | `OK` atau (no response) | — | — |

---

## 2. USSD Commands

| Feature | USSD Code | Expected Response | Parser | Destination Field |
|---------|-----------|-------------------|--------|-------------------|
| **Cek Nomor** | `*185#` | `"Good Morning , Your number 08586xxxxxxx, Balance Rp.0 Active 24-08-2026 How can we assist you? ^ 1.Account ^ ..."` | `_parse_ussd_number()` regex `r'(08\d{9,11})'` + `_extract_grace_date()` + `_classify_card_status()` | `nomor`, `masa_aktif`, `status` |
| **Cek NIK** | `*888*4444*1#` | `"Nomor IM3 kamu telah terdaftar dengan ^ NIK : 31750554xxxxxxxx"` | `cek_nik.py` regex `r'NIK\s*:\s*(\d{16})'` | `raw_response` (needs upstream extraction) |
| **Reaktivasi (Hangus)** | `*888*89*1*{NIK}*{KK}#` | `"Permintaan kamu sedang di proses, cek SMS untuk mengetahui status permintaan kamu"` | `classify_ussd_evidence()` | `injected`, `raw_response` |
| **Reaktivasi (Tenggang)** | `*888*89*1*{NIK}*{KK}#` | `"Nomor 08575xxxxxxx sedang dalam masa tenggang. SEGERA lalukan isi ulang/beli paket agar nomor tetap AKTIF..."` | `classify_ussd_evidence()` | `injected`, `raw_response` |
| **Reaktivasi (Aktif)** | `*888*89*1*{NIK}*{KK}#` | `"Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus"` | `classify_ussd_evidence()` | `injected=False`, `raw_response` |
| **Verifikasi** | `*185#` | Same as Cek Nomor — extract grace date before vs after | `_extract_grace_date()` | `card_status`, `grace_date`, `masa_aktif` |

### 2.1 *185# Response Breakdown

`*185#` returns **3 data points** sekaligus:
1. **Nomor**: regex `r'(08\d{9,11})'` dari string
2. **Grace Date**: regex `r'Active\s+(\d{2}-\d{2}-\d{4})'` atau `r'(\d{2}-\d{2}-\d{4})'`
3. **Status**: `"Active"` → AKTIF, `"Expired"` → HANGUS, `"Tenggang"` → TENGGANG

Contoh response:
```
"Good Morning , Your number 0858612345678, Balance Rp.0 Active 24-08-2026 How can we assist you? ^ 1.Account ^ 2.Content ^ 3.IMPoin ^ 4.Help ^ 5.IMEI ^ 6.DND ^ 7.Chat Us"
```
- Nomor: `0858612345678`
- Grace Date: `24-08-2026`
- Status: `Active` → AKTIF

### 2.2 *888*4444*1# Response Breakdown

`*888*4444*1#` returns NIK:
```
"Nomor IM3 kamu telah terdaftar dengan ^ NIK : 31750554xxxxxxxx"
```
- NIK: regex `r'NIK\s*:\s*(\d{16})'` → `31750554xxxxxxxx`

### 2.3 *888*89*1*{NIK}*{KK}# Response by Card Status

| Card Status | Response Pattern | Intent |
|------------|-----------------|--------|
| **HANGUS** | `"Permintaan kamu sedang di proses, cek SMS untuk mengetahui status permintaan kamu"` | `REQUEST_ACCEPTED` |
| **TENGGANG** | `"Nomor 08575xxxxxxx sedang dalam masa tenggang. SEGERA lalukan isi ulang/beli paket agar nomor tetap AKTIF dan bisa menikmati layanan IM3"` | `ALREADY_ACTIVE` |
| **AKTIF** | `"Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus"` | `REJECTED` |

### 2.4 Bot Telegram Response

| Query | Response |
|-------|----------|
| **NIK not found** | `"NIK 352104xxxxxxxxxx\n-> TIDAK DITEMUKAN"` |
| **NIK found** | `"NIK: 640412xxxxxxxxxx\nKK: 640412xxxxxxxxxx (terbit: 13/07/2007)"` |

### 2.5 Cek Limit (Future)
| USSD Code | Expected Response | Parser |
|-----------|-------------------|--------|
| (configurable) | `+CUSD: 0,"Pulsa: Rp 10.000"` | (not yet implemented) |

---

## 3. Response Classification

### 3.1 CPIN Response → CpinState

| Raw Response | CpinState | Status | Respon |
|-------------|-----------|--------|--------|
| `+CPIN: READY` | `READY` | `READY` | `+CPIN: READY` |
| `+CPIN: NOT INSERTED` | `NOT_INSERTED` | `IDLE` | `Idle/Standby` |
| `+CPIN: SIM PIN` | `PIN_REQUIRED` | `PIN LOCK` | `+CPIN: PIN Required` |
| `+CPIN: NOT READY` | `NOT_READY` | `IDLE` | `+CPIN: NOT READY` |
| `+CME ERROR: 10` | `NOT_INSERTED` | `IDLE` | `Idle/Standby` |
| (timeout) | `UNKNOWN` | `CHECKING` | `CPIN not responding` |

**IMPORTANT**: `NOT READY` dicek SEBELUM `READY` untuk menghindari substring false positive.

### 3.2 CNUM Response → Nomor

| Raw Response | Parsed Nomor | Regex |
|-------------|-------------|-------|
| `+CNUM: "","081234567890",129` | `081234567890` | `r'\+CNUM:\s*"",\s*"(\d+)"'` |
| `+CNUM: "","+6281234567890",129` | `+6281234567890` | `r'\+CNUM:\s*"",\s*"(\+?\d+)"'` |
| `+CNUM: "","",129` | None | — |

### 3.3 USSD Response Classification (9-Tier)

| Priority | Kind | Condition | Example |
|----------|------|-----------|---------|
| 1 | `USSD_PAYLOAD` | `+CUSD: N,"<payload>"` non-empty | `+CUSD: 0,"Nomor: 081234567890"` |
| 2 | `USSD_EMPTY_PAYLOAD` | `+CUSD: N,""` | `+CUSD: 0,""` |
| 3 | `USSD_STATUS_ONLY` | `+CUSD: N` (no quotes) | `+CUSD: 0` |
| 4 | `PARTIAL_RESPONSE` | `+CUSD: N,"<unclosed` | `+CUSD: 0,"partial...` |
| 5 | `PROMPT_CONFIRMATION` | Prompt keywords detected | Contains "pilih"/"konfirmasi" |
| 6 | `ERROR` | `+CME ERROR` or `+CMS ERROR` | `+CME ERROR: 30` |
| 7 | `AT_OK` | `OK` without CUSD | `OK` |
| 8 | `COMMAND_ECHO` | `AT+CUSD=` echo | `AT+CUSD=1,"*185#",15` |
| 9 | `MODEM_NOTIFICATION` | `+WIND:`/`+CPIN:`/`+CREG:` | `+CSQ: 20` |
| 10 | `WAITING_RESPONSE` | Anything else | (waiting...) |
| 11 | `TIMEOUT` | No text | (timeout) |

### 3.4 USSD Intent Classification

| Intent | Condition | Keywords/Pattern |
|--------|-----------|------------------|
| `EMPTY_RESPONSE` | Empty text | — |
| `NUMBER_INFO` | Contains phone number | `r'0\d{9,12}'` |
| `SUCCESS_MESSAGE` | Success keywords | "sukses", "berhasil", "success", "completed" |
| `REQUEST_ACCEPTED` | Processing keywords | "sedang diproses", "diterima", "accepted", "queued" |
| `MENU_RESPONSE` | Menu keywords or numbered list | "pilih", "silakan pilih", "1.", "2." |
| `UNKNOWN` | Fallback | — |

### 3.5 USSD Evidence Classification

| Evidence | Keywords/Pattern |
|----------|------------------|
| `has_success_evidence` | "sukses", "berhasil", "success", "completed" |
| `has_processing_evidence` | "sedang diproses", "sedang di proses", "di proses", "dalam proses", "permintaan diterima", "diterima", "accepted", "processing", "in process", "queued", "diproses" |
| `has_tenggang_evidence` | `r"\b(dalam\s+masa\s+tenggang\|masa\s+tenggang\|sedang\s+dalam\s+masa\s+tenggang\|sedang\s+dalam\s+tenggang)\b"` |

### 3.6 Card Status Classification

| Priority | Condition | CardStatus | Notes |
|----------|-----------|------------|-------|
| 1 | Evidence "tenggang" | `TENGGANG` | Regex keyword match |
| 2 | Evidence "hangus" | `HANGUS` | Regex keyword match |
| 3 | Evidence "aktif" | `AKTIF` | Regex keyword match |
| 4 | `days_remaining is None` | `UNKNOWN` | Parse error |
| 5 | `days_remaining > 0` | `AKTIF` | Date calculation |
| 6 | `days_remaining >= -30 AND <= 0` | `TENGGANG` | Grace period |
| 7 | `days_remaining < -30` | `HANGUS` | Expired |

### 3.7 Grace Date Extraction

| Format | Regex | Output |
|--------|-------|--------|
| `YYYY-MM-DD` | `r'(\d{4}[-/]\d{2}[-/]\d{2})'` | `YYYY-MM-DD` |
| `YYYY/MM/DD` | `r'(\d{4}[-/]\d{2}[-/]\d{2})'` | `YYYY-MM-DD` |
| `DD-MM-YYYY` | `r'(\d{2}[-/]\d{2}[-/]\d{4})'` | Converted to `YYYY-MM-DD` |
| `DD/MM/YYYY` | `r'(\d{2}[-/]\d{2}[-/]\d{4})'` | Converted to `YYYY-MM-DD` |
| (no match) | — | `"-"` |

---

## 4. Skill → Response Mapping

### 4.1 CekNomorSkill

`*185#` mengambil **3 data sekaligus**: nomor, grace date, status.

| Step | Command | Response | Parser | Output Field |
|------|---------|----------|--------|-------------|
| 1 | `AT+CNUM` | `+CNUM: "","081234567890",129` | `_parse_cnum()` | `data["number"]` |
| 2 (fallback) | USSD `*185#` | `"Good Morning , Your number 08586xxxxxxx, Balance Rp.0 Active 24-08-2026..."` | `_parse_ussd_number()` regex `r'(08\d{9,11})'` + `_extract_grace_date()` + `_classify_card_status()` | `data["number"]`, `data["grace_date"]`, `data["card_status"]` |

**Output**: `{"number": "0858612345678", "grace_date": "24-08-2026", "card_status": "AKTIF", "modem_responsive": True, "raw_cnum": "..."}`

**Note**: Grace date dan status JUGA diambil dari response yang sama. Tidak perlu USSD terpisah untuk verifikasi awal.

### 4.2 CekStatusSkill

| Step | Command | Response | Parser | Output Field |
|------|---------|----------|--------|-------------|
| 1 | `AT+CPIN?` | `+CPIN: READY` | `parse_cpin_response()` | `data["cpin_state"]` |

**Output**: `{"cpin_state": "READY", "raw_response": "...", "sim_ready": True}`

### 4.3 CekNikSkill

| Step | Command | Response | Parser | Output Field |
|------|---------|----------|--------|-------------|
| 1 | USSD `*888*4444*1#` | `"Nomor IM3 kamu telah terdaftar dengan ^ NIK : 31750554xxxxxxxx"` | regex `r'NIK\s*:\s*(\d{16})'` | `data["nik"]` |

**Output**: `{"nik": "31750554xxxxxxxx", "raw_response": "...", "has_payload": True, "ussd_code": "*888*4444*1#"}`

### 4.4 CekKkSkill

KK **bukan dari USSD langsung**. Sumber:
1. **Phone Cache** — jika nomor sudah ada di cache
2. **Local DB** — query `panen_raya` table berdasarkan NIK
3. **Telegram Bot** — query manual ke bot Telegram
4. **Format Mode NIK&NIK** — KK = NIK (skip lookup)

| Step | Source | Response | Parser | Output Field |
|------|--------|----------|--------|-------------|
| 1 | Cache/DB/Telegram | `"NIK: 640412xxxxxxxxxx\nKK: 640412xxxxxxxxxx (terbit: 13/07/2007)"` | regex `r'KK\s*:\s*(\d{16})'` | `data["kk"]` |

**Output**: `{"kk": "640412xxxxxxxxxx", "source": "cache|db|telegram|nik_mode", "raw_response": "..."}`

### 4.5 InjectReaktivasiSkill

| Step | Command | Response | Parser | Output Field |
|------|---------|----------|--------|-------------|
| 1 | USSD `*888*89*1*{NIK}*{KK}#` | (depends on card status — see 2.3) | `classify_ussd_evidence()` | `data["injected"]`, `data["raw_response"]` |

**Output by Card Status**:
- **HANGUS**: `{"injected": True, "raw_response": "Permintaan kamu sedang di proses...", "provisional": "SUCCESS"}`
- **TENGGANG**: `{"injected": False, "raw_response": "Nomor 08575xxxxxxx sedang dalam masa tenggang...", "provisional": "ALREADY_ACTIVE"}`
- **AKTIF**: `{"injected": False, "raw_response": "Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus", "provisional": "REJECTED"}`

### 4.6 VerifyGraceSkill

| Step | Command | Response | Parser | Output Field |
|------|---------|----------|--------|-------------|
| 1 | USSD `*185#` | Same as Cek Nomor | `_extract_grace_date()` | `data["grace_date_after"]` |

**Output**: `{"raw_response": "...", "grace_date_after": "24-08-2026", "card_status": "AKTIF"}`

**Success Criteria** (from PENUNJANG.md):
- **Sukses**: `grace_date_before ≠ grace_date_after` (ada perubahan grace date)
- **Gagal**: `grace_date_before = grace_date_after` (tidak ada perubahan)

### 4.7 RestartHardwareSkill

| Step | Command | Response | Parser | Output Field |
|------|---------|----------|--------|-------------|
| 1 | `ATZ` | `OK` | — | `data["restart_sent"]` |
| 2 | (wait 15s) | — | — | — |
| 3 | `check_modem()` | `True/False` | — | `data["modem_online"]` |

**Output**: `{"restart_sent": True, "modem_online": True}`

### 4.8 ResetHardwareSkill

| Step | Command | Response | Parser | Output Field |
|------|---------|----------|--------|-------------|
| 1 | (stop CPIN) | — | — | — |
| 2 | (close serial) | — | — | — |
| 3 | (wait 15s) | — | — | — |
| 4 | (reopen serial) | — | — | — |
| 5 | (start CPIN) | — | — | — |
| 6 | `check_modem()` | `True/False` | — | `data["modem_online"]` |
| 7 | `AT+CPIN?` | `+CPIN: READY` | `parse_cpin_response()` | `data["cpin_state"]` |

**Output**: `{"modem_online": True, "cpin_state": "READY", "ready": True}`

---

## 5. PortWorkerState Field Mapping

| Skill Result Key | PortWorkerState Field | UI Column | Event Payload Key |
|-----------------|----------------------|-----------|-------------------|
| `data["number"]` | `_nomor` | NOMOR | `nomor` |
| `data["nik"]` | `_nik` | NIK | `nik` |
| `data["kk"]` | `_kk` | KK | `kk` |
| `data["grace_date"]` | `_masa_aktif` | MASA AKTIF | `masa_aktif` |
| `data["cpin_state"]` | — | RESPON | `respon` |
| `data["card_status"]` | — | RESPON | `respon` |
| `data["modem_online"]` | — | RESPON | `respon` |
| `data["ready"]` | — | RESPON | `respon` |
| `data["injected"]` | — | RESPON | `respon` |

### 5.1 Result Propagation Flow

```
Skill Result → Engine._on_step_complete()
  │
  ├── number → PortWorkerState.set_number(nomor)
  │                → EventBus: port.data.updated {nomor: "..."}
  │                → GUI: _on_port_update → update_cell(NOMOR)
  │
  ├── nik → PortWorkerState.set_nik(nik)
  │              → EventBus: port.data.updated {nik: "..."}
  │              → GUI: _on_port_update → update_cell(NIK)
  │
  ├── kk → PortWorkerState.set_kk(kk)
  │             → EventBus: port.data.updated {kk: "..."}
  │             → GUI: _on_port_update → update_cell(KK)
  │
  ├── grace_date → PortWorkerState.set_masa_aktif(masa_aktif)
  │                    → EventBus: port.data.updated {masa_aktif: "..."}
  │                    → GUI: _on_port_update → update_cell(MASA AKTIF)
  │
  └── cpin_state/card_status → EventBus: port.data.updated {respon: "..."}
                                   → GUI: _on_port_update → update_cell(RESPON)
```

---

## 6. Timing Constants

| Constant | Value | Usage | Command |
|----------|-------|-------|---------|
| `DIAL_COOLDOWN_SECONDS` | 4.0s | Minimum antar USSD dial | `send_ussd()` |
| `USSD_SESSION_FENCE_MIN_SECONDS` | 0.75s | Minimum fence time | `AT+CUSD=2` |
| `USSD_SESSION_FENCE_QUIET_SECONDS` | 0.25s | Quiet time after fence | — |
| `USSD_SESSION_FENCE_TIMEOUT_SECONDS` | 3.0s | Maximum fence time | `AT+CUSD=2` |
| `CPIN_POLL_INTERVAL` | 1.0s | Interval antar CPIN poll | `AT+CPIN?` |
| `CPIN_POLL_TIMEOUT` | 3.0s | Timeout per CPIN poll | `AT+CPIN?` |
| `CPIN_FINAL_CONFIRM_TIMEOUT` | 3.0s | Final confirm timeout | `AT+CPIN?` |
| `STABILIZATION_SECONDS` | 15.0s | Wait setelah reset | — |
| `VERIFICATION_DELAY_SECONDS` | 15.0s | Delay sebelum verify | `*185#` |
| `VERIFICATION_READ_TIMEOUT` | 30.0s | Read timeout untuk verify | `*185#` |
| `CPIN_UNKNOWN_THRESHOLD` | 3 | UNKNOWN count → final confirm | — |
| `CPIN_CHECKING_THRESHOLD` | 2 | UNKNOWN count → CHECKING UI | — |
| `CPIN_MAX_REMOVAL_CONFIRM` | 2 | Max removal confirm retries | `AT+CPIN?` |
| `PROMPT_RECOVERY_MAX` | 2 | Max prompt recovery retries | `AT+CUSD=2` |
| `USSD_GRACE_READ_INITIAL_WAIT` | 0.5s | Initial wait untuk grace read | — |
| `USSD_GRACE_READ_WINDOW` | 3.0s | Read window untuk grace read | — |
