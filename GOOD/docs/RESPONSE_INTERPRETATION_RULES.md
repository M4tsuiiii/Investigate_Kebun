# Response Interpretation Rules — GOOD Monolith

Sumber: `app/kebun_reaktivasi(rev).py` (2907 baris) + `worker/ussd/classification.py` + `worker/reactivation/classifier.py`.

---

## 1. AT Response Parsing

### 1.1 CPIN State Extraction (`_extract_cpin_state`, Line 1131)

**Input**: Raw string dari `AT+CPIN?` response

**Prioritas parsing** (dicek secara berurutan):

| Prioritas | Pattern | Output | Keterangan |
|-----------|---------|--------|------------|
| 1 | `"+CPIN: NOT READY"` | `"NOT_READY"` | Dicek DULU sebelum READY |
| 2 | `"+CPIN: READY"` (bukan NOT READY) | `"READY"` | |
| 3 | Contains `"PIN"` atau `"PUK"` | `"PIN_REQUIRED"` | |
| 4 | `"NOT INSERTED"` atau `"+CME ERROR: 10"` | `"NOT_INSERTED"` | |
| 5 | Else | `"UNKNOWN"` | |

**Catatan Penting**: `"NOT READY"` harus dicek sebelum `"READY"` karena string `"NOT READY"` mengandung substring `"READY"`.

### 1.2 CNUM Parsing (`_parse_cnum`, CekNomorSkill)

**Input**: Raw string dari `AT+CNUM` response

**Format expected**:
```
+CNUM: "","081234567890",129
```

**Regex**: `r'\+CNUM:\s*"",\s*"(\d+)"'`

**Output**: Nomor telepon (string) atau `None`

### 1.3 Phone Number Extraction

**Regex**: `(08\d{9,11})`

**Match**: 10-13 digit nomor telepon Indonesia

**Lokasi**: Line 1644 (execute_single_action), Line 1810 (execute_full_flow)

**Contoh match**: `081234567890`, `0812345678901`

### 1.4 NIK Extraction

**Regex**: `(\d{16})`

**Validasi**: `re.fullmatch(r"\d{16}", nik)`

**Lokasi**: Line 1665 (execute_single_action), Line 1878 (execute_full_flow)

**Contoh match**: `3276015001900001`

---

## 2. USSD Response Classification

### 2.1 Primary Classification (`classify_ussd_response`, Line 679)

**Input**: Raw USSD response string

**Output**: Tuple `(kind_string, clean_text)`

**Prioritas** (dicek secara berurutan):

| Prioritas | Condition | Kind | Clean Text |
|-----------|-----------|------|------------|
| 1 | `+CUSD: N,"<payload>"` dengan payload non-empty | `USSD_PAYLOAD` | Payload tanpa quotes |
| 2 | `+CUSD: N,""` (empty quoted) | `USSD_EMPTY_PAYLOAD` | `""` |
| 3 | `+CUSD: N` (tanpa quotes, hanya status) | `USSD_STATUS_ONLY` | Status code |
| 4 | `+CUSD: N,"<unclosed` | `PARTIAL_RESPONSE` | Raw text |
| 5 | Prompt keywords hadir | `PROMPT_CONFIRMATION` | Raw text |
| 6 | `+CME ERROR` atau `CMS ERROR` | `ERROR` | Raw text |
| 7 | AT OK (tanpa CUSD) | `AT_OK` | Raw text |
| 8 | `AT+CUSD=` echo | `COMMAND_ECHO` | Raw text |
| 9 | `+WIND:`/`+CPIN:`/`+CREG:`/dst | `MODEM_NOTIFICATION` | Raw text |
| 10 | Else | `WAITING_RESPONSE` | Raw text |
| 11 | No text at all | `TIMEOUT` | `""` |

### 2.2 Prompt Keywords

Daftar keyword yang mendeteksi prompt USSD:

```python
[
    "confirm", "konfirmasi", "pilih", "silakan pilih", "silahkan pilih",
    "input angka", "jawab", "1.", "2."
]
```

### 2.3 Modem Notification Patterns

Regex pattern untuk mendeteksi notifikasi modem:

```python
r"\+WIND:|\+MREG:|\+CPIN:|\+CREG:|\+CGREG:|\+CIEV:|\+CSQ:"
```

---

## 3. USSD Evidence Classification (`classify_ussd_evidence`, Line 718)

**Input**: Raw USSD response string

**Output**: Object dengan boolean flags

### 3.1 Success Evidence

```python
has_success_evidence = any(k in text for k in (
    "sukses", "berhasil", "success", "completed"
))
```

### 3.2 Processing Evidence

```python
has_processing_evidence = any(k in text for k in (
    "sedang diproses", "sedang di proses", "di proses",
    "dalam proses", "permintaan diterima", "diterima",
    "accepted", "processing", "in process", "queued", "diproses"
))
```

### 3.3 Tenggang Evidence

```python
has_tenggang_evidence = bool(re.search(
    r"\b(dalam\s+masa\s+tenggang|masa\s+tenggang|"
    r"sedang\s+dalam\s+masa\s+tenggang|sedang\s+dalam\s+tenggang)\b",
    text, re.IGNORECASE
))
```

---

## 4. USSD Intent Classification (`classify_ussd_intent`, Line 738)

**Input**: Raw USSD response string

**Output**: Intent string

| Intent | Condition |
|--------|-----------|
| `EMPTY_RESPONSE` | Empty text |
| `NUMBER_INFO` | Contains `08xxxxxxxxx` (phone number pattern) |
| `SUCCESS_MESSAGE` | Success keywords hadir |
| `REQUEST_ACCEPTED` | Processing keywords hadir |
| `MENU_RESPONSE` | Menu keywords hadir ATAU numbered list detected |
| `UNKNOWN` | Fallback |

### 4.1 Menu Keywords

```python
(
    "try again", "good evening", "welcome", "menu", "account", "content",
    "impoint", "your number", "pilih", "silakan pilih", "silahkan pilih"
)
```

---

## 5. USSD Payload Completeness (`is_ussd_payload_complete`, Line 764)

**Input**: Raw USSD response string

**Output**: Boolean

```python
complete = (
    extract_ussd_payload(text) is not None      # Ada quoted payload
    or "+CME ERROR" in text                       # Error response
    or is_prompt_confirmation(text)               # Prompt detected
)
```

---

## 6. Grace Date Extraction (`extract_grace_date`, Line 784)

**Input**: Raw USSD response string

**Output**: String tanggal (format `YYYY-MM-DD`) atau `"-"`

### 6.1 Format 1: ISO (YYYY-MM-DD atau YYYY/MM/DD)

```python
match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})', text)
if match:
    return match.group(1).replace('/', '-')
```

### 6.2 Format 2: Local (DD-MM-YYYY atau DD/MM/YYYY)

```python
match = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4})', text)
if match:
    parts = re.split(r'[-/]', match.group(1))
    return f"{parts[2]}-{parts[1]}-{parts[0]}"
```

### 6.3 No Match

```python
return "-"
```

---

## 7. Card Status Classification (`classify_card_status`, Line 801)

**Input**: `grace_date` (string), `raw_response` (string)

**Output**: `CardStatus` enum (`AKTIF`, `TENGGANG`, `HANGUS`, `UNKNOWN`)

### 7.1 Prioritas Classification

| Prioritas | Condition | Output |
|-----------|-----------|--------|
| 1 | Evidence "tenggang" dalam response | `TENGGANG` |
| 2 | Evidence "hangus" dalam response | `HANGUS` |
| 3 | Evidence "aktif" dalam response | `AKTIF` |
| 4 | `days_remaining is None` (parse error) | `UNKNOWN` |
| 5 | `days_remaining > 0` | `AKTIF` |
| 6 | `days_remaining >= -30 AND <= 0` | `TENGGANG` |
| 7 | `days_remaining < -30` | `HANGUS` |

### 7.2 Tenggang Keywords

```python
r"\b(dalam\s+masa\s+tenggang|masa\s+tenggang|sedang\s+dalam\s+masa\s+tenggang|sedang\s+dalam\s+tenggang)\b"
```

### 7.3 Hangus Keywords

```python
r"\bnomor\s+hangus\b|\bstatus\s+hangus\b|\btelah\s+hangus\b"
```

### 7.4 Aktif Keywords

```python
r"\bmasih\s+aktif\b|\bstatus\s+(?:kartu\s+)?aktif\b|\bkartu\s+aktif\b"
```

---

## 8. Business Outcome Evaluation (`evaluate_business_outcome`, Line 844)

**Input**:
- `before_grace`: Grace date sebelum inject
- `after_grace`: Grace date setelah verifikasi
- `before_status`: Status kartu sebelum inject
- `after_status`: Status kartu setelah verifikasi
- `inject_response`: Raw response dari injection

**Output**: `BusinessOutcome` enum (`SUCCESS`, `TENGGANG`, `FAILED`)

### 8.1 Decision Logic

```python
grace_changed = has_grace_date_changed(before_grace, after_grace)
evidence = classify_ussd_evidence(inject_response)

if grace_changed and after_status not in {"", "HANGUS", "UNKNOWN"}:
    return "SUCCESS"

if not grace_changed and evidence.has_tenggang_evidence:
    return "TENGGANG"

return "FAILED"
```

### 8.2 Grace Date Change Detection (`has_grace_date_changed`, Line 830)

```python
if either value empty or "-": return False
Parse both as YYYY-MM-DD date objects
return before_date != after_date
```

---

## 9. Provisional Success Classification (Injection)

**Input**: Raw USSD response dari injection

**Output**: `PROVISIONAL_SUCCESS`, `PROVISIONAL_WAITING`, atau `GAGAL_INJEKSI`

### 9.1 Provisional Success Conditions

| Condition | Result |
|-----------|--------|
| `USSD_STATUS_ONLY` dengan status 0 | `PROVISIONAL_SUCCESS` |
| `USSD_EMPTY_PAYLOAD` | `PROVISIONAL_WAITING` |
| `COMMAND_EXECUTED` | `PROVISIONAL_SUCCESS` |
| Intent = `SUCCESS_MESSAGE` | `PROVISIONAL_SUCCESS` |
| Intent = `REQUEST_ACCEPTED` | `PROVISIONAL_SUCCESS` |
| Intent = `MENU_RESPONSE` | `PROVISIONAL_WAITING` |
| Intent = `NUMBER_INFO` | `PROVISIONAL_WAITING` |
| Intent = `EMPTY` | `PROVISIONAL_WAITING` |
| Intent = `UNKNOWN` | `PROVISIONAL_WAITING` |

### 9.2 Failure Conditions

```
Tidak ada provisional
DAN (timeout ATAU error ATAU partial ATAU tidak ada success evidence)
→ GAGAL_INJEKSI
```

---

## 10. USSD Grace Read Window (`_ussd_grace_read_window`, Line 1503)

**Input**: Port serial, initial response

**Output**: Final USSD classification

### 10.1 Flow

```
IF USSD_EMPTY_PAYLOAD:
  1. Tunggu 0.5s (USSD_GRACE_READ_INITIAL_WAIT)
  2. Read up to 3s (USSD_GRACE_READ_WINDOW)
  3. Exit: payload complete + 0.8s quiet ATAU 3s timeout
  4. IF payload ditemukan → USSD_PAYLOAD, else → USSD_EMPTY_PAYLOAD
```

---

## 11. USSD Session Fence (`_fence_ussd_transport_session`, Line 1198)

**Input**: Port serial

**Output**: Bersihkan semua byte stale

### 11.1 Flow

```
1. Kirim AT+CUSD=2 (cancel)
2. Tunggu min 0.75s (USSD_SESSION_FENCE_MIN_SECONDS)
3. Tunggu tambahan 0.25s quiet (USSD_SESSION_FENCE_QUIET_SECONDS)
4. Max 3.0s total (USSD_SESSION_FENCE_TIMEOUT_SECONDS)
5. Buang semua byte stale
```

---

## 12. Prompt Recovery (`_recover_from_prompt`, Line 1601)

**Input**: Port serial, requeue flag

**Output**: Recovered atau GAGAL

### 12.1 Flow

```
PROMPT_RECOVERY_MAX = 2
1. Kirim AT+CUSD=2 (cancel)
2. Flush serial input
3. IF requeue AND prompt_recovery_count <= 2:
   → increment count, _queue_auto_run(), return
4. ELSE: clear pending_auto_run, reset count, GAGAL
```

---

## 13. UI Status Tags (`_get_status_tag`, Line 2622)

**Input**: Status string

**Output**: Tkinter tag untuk pewarnaan row

| Status | Tag | Warna |
|--------|-----|-------|
| `"sukses"` | `"sukses"` | Hijau (`#E2F0D9`) |
| `"done"` | `"done"` | Hijau (`#E2F0D9`) |
| `"proses"` / `"ready"` / `"stabilisasi"` | `"proses"` | Biru (`#D9E1F2`) |
| `"no sim"` / `"not inserted"` / `"idle"` | `"idle"` | Abu-abu (`#F5F5F5`) |
| `"off"` | `"off"` | Abu-abu (`#F0F0F0`) |
| `"gagal"` | `"gagal"` | Merah (`#FCE4D6`) |
| Else | `"idle"` | Abu-abu (`#F5F5F5`) |

---

## 14. Status Update Guard (`_is_status_update_allowed`, Line 149)

**Input**: `old_status`, `new_status`, `last_cpin`

**Output**: Boolean

```python
if old_status == new_status:
    return True

if old_status == "OFF" and new_status == "IDLE":
    return last_cpin == "NOT_INSERTED"

if old_status == "READY" and new_status == "IDLE":
    return last_cpin == "NOT_INSERTED"

return False  # deny
```

---

## 15. Default Port State

```python
DEFAULT_PORT_STATE = {
    "port_display": "-",
    "nomor": "-",
    "nik": "-",
    "kk": "-",
    "status": "IDLE",
    "respon": "Idle/Standby",
    "masa_aktif": "-",
    "last_cpin": "UNKNOWN",
    "last_update": None,
}
```

---

## 16. Field Extraction Summary

| Field | Sumber | Regex/Method | Output |
|-------|--------|-------------|--------|
| Nomor | `AT+CNUM` | `r'\+CNUM:\s*"",\s*"(\d+)"'` | String digits |
| Nomor | USSD `*185#` | `r'(08\d{9,11})'` | String digits |
| NIK | USSD `*888*4444*1#` | `r'(\d{16})'` | String 16 digit |
| KK | Cache/Telegram | `re.fullmatch(r"\d{16}", kk)` | String 16 digit |
| Grace Date | USSD `*185#` | `extract_grace_date()` | `YYYY-MM-DD` atau `"-"` |
| CPIN State | `AT+CPIN?` | `_extract_cpin_state()` | `CpinState` enum |
| Card Status | USSD `*185#` | `classify_card_status()` | `CardStatus` enum |
| Success Evidence | USSD inject | `classify_ussd_evidence()` | Boolean flag |
| Tenggang Evidence | USSD response | Regex tenggang keywords | Boolean flag |
