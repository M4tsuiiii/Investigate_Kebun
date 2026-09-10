# SKILL COMMAND DEPENDENCY MAP

Complete dependency map: Skill → Command → Parser → Workflow → UI Field.

---

## 1. CekNomorSkill

```
CekNomorSkill
├── AT Command: AT+CNUM
│   └── Parser: _parse_cnum()
│       └── Regex: r'\+CNUM:\s*"",\s*"(\d+)"'
│           └── Output: data["number"]
├── USSD Fallback: *185# (configurable)
│   └── Parser: _parse_ussd_number()
│       └── Regex: r'(08\d{9,11})'
│           └── Output: data["number"]
├── [NEW] Grace Date Extraction from *185#
│   └── Parser: _extract_grace_date()
│       └── Regex: r'Active\s+(\d{2}-\d{2}-\d{4})'
│           └── Output: data["grace_date"]
└── [NEW] Card Status — DIHITUNG dari grace_date
    └── Parser: _classify_card_status()
        └── Logic: grace_date - today = masa aktif
            ├── masa aktif > 0 → AKTIF
            ├── -30 ≤ masa aktif ≤ 0 → TENGGANG
            └── masa aktif < -30 → HANGUS
        └── Output: data["card_status"]

NOTE: Kata "Active" di response *185# BUKAN status kartu.
Status diHITUNG dari rumus: grace_date - today = masa aktif.

Used in Workflows:
├── check_number (Step 1)
├── check_data (Step 1)
└── reactivate_full (Step 1)

Output → UI Mapping:
├── data["number"] → PortWorkerState._nomor → NOMOR column
├── data["grace_date"] → PortWorkerState._masa_aktif → MASA AKTIF column
└── data["card_status"] → RESPON column
```

---

## 2. CekStatusSkill

```
CekStatusSkill
├── AT Command: AT+CPIN?
│   └── Parser: parse_cpin_response()
│       └── Logic: "NOT READY" before "READY" check
│           └── Output: data["cpin_state"]

Used in Workflows:
├── check_status (Step 1)
└── reactivate_full (Step 2)

Output → UI Mapping:
└── data["cpin_state"] → RESPON column
```

---

## 3. CekNikSkill

```
CekNikSkill
├── [FIX] USSD Code: *888*4444*1# (was *185#)
│   └── [NEW] Parser: _extract_nik()
│       └── Regex: r'(\d{16})'
│           └── Validation: re.fullmatch(r"\d{16}", nik)
│               └── Output: data["nik"]

Used in Workflows:
├── check_nik (Step 1)
├── check_data (Step 2)
└── reactivate_full (Step 3)

Output → UI Mapping:
└── data["nik"] → PortWorkerState._nik → NIK column
```

---

## 4. CekKkSkill

```
CekKkSkill
├── [REWRITE] Source: cache → DB → Telegram → NIK&NIK mode
│   ├── [NEW] Phone Cache Check
│   │   └── Logic: phone_cache.get(nomor)
│   │       └── Output: data["kk"], data["source"] = "cache"
│   ├── [NEW] Local DB Check
│   │   └── Logic: query panen_raya table
│   │       └── Output: data["kk"], data["source"] = "db"
│   ├── [NEW] NIK&NIK Mode Check
│   │   └── Logic: if format_mode == "NIK & NIK", kk = nik
│   │       └── Output: data["kk"], data["source"] = "nik_mode"
│   └── [NEW] Telegram Lookup
│       └── Logic: query bot
│           └── Output: data["kk"], data["source"] = "telegram"

Used in Workflows:
├── check_kk (Step 1)
├── check_data (Step 3)
└── reactivate_full (Step 4)

Output → UI Mapping:
└── data["kk"] → PortWorkerState._kk → KK column
```

---

## 5. InjectReaktivasiSkill

```
InjectReaktivasiSkill
├── USSD Code: *888*89*1*{NIK}*{KK}# (configurable)
│   ├── [NEW] Parser: classify_injection_response()
│   │   └── Logic: keyword match by card status
│   │       ├── "Permintaan kamu sedang di proses" → HANGUS
│   │       ├── "sedang dalam masa tenggang" → TENGGANG
│   │       └── "Layanan Hanya Dapat Dilakukan" → AKTIF
│   │           └── Output: data["injected"], data["card_status"]
│   └── [NEW] Parser: _evaluate_provisional()
│       └── Logic: USSD response classification
│           ├── USSD_STATUS_ONLY:0 → PROVISIONAL_SUCCESS
│           ├── USSD_EMPTY_PAYLOAD → PROVISIONAL_WAITING
│           ├── PROMPT_CONFIRMATION → FAILURE
│           └── ERROR → FAILURE
│               └── Output: data["provisional"]

Used in Workflows:
├── reactivate_fast (Step 1)
└── reactivate_full (Step 5)

Output → UI Mapping:
├── data["injected"] → RESPON column
└── data["provisional"] → RESPON column
```

---

## 6. VerifyGraceSkill

```
VerifyGraceSkill
├── USSD Code: *185#
│   ├── Parser: _extract_grace_date()
│   │   └── Regex: r'(\d{2}[-/]\d{2}[-/]\d{4})'
│   │       └── Output: data["grace_date_after"]
│   ├── [NEW] Parser: _classify_card_status()
│   │   └── Logic: 7-tier priority
│   │       └── Output: data["card_status"]
│   ├── [NEW] Parser: has_grace_date_changed()
│   │   └── Logic: before != after
│   │       └── Output: data["success"]
│   └── [NEW] Parser: evaluate_business_outcome()
│       └── Logic: SUCCESS/TENGGANG/FAILED
│           └── Output: data["outcome"]

Used in Workflows:
├── reactivate_fast (Step 2)
└── reactivate_full (Step 6)

Output → UI Mapping:
├── data["grace_date_after"] → PortWorkerState._masa_aktif → MASA AKTIF column
└── data["card_status"] → RESPON column
```

---

## 7. CekLimitSkill

```
CekLimitSkill
├── [NEW] USSD Code: configurable (user sets via settings)
│   └── [NEW] Parser: _extract_pulsa()
│       └── Regex: r'Rp[\s.]?(\d[\d.,]*)'
│           └── Output: data["pulsa"]

Used in Workflows:
└── check_limit (Step 1) [NEW WORKFLOW]

Output → UI Mapping:
└── data["pulsa"] → RESPON column
```

---

## 8. RestartHardwareSkill

```
RestartHardwareSkill
├── AT Command: ATZ (soft reset)
│   └── Response: OK
│       └── Output: data["restart_sent"]
├── Wait: 15.0s (STABILIZATION_SECONDS)
└── Check: check_modem()
    └── Output: data["modem_online"]

Types:
├── Tunggal: restart 1 port (context menu / button)
└── Massal: restart semua port (button "Restart All")

After restart:
├── Worker rescan modem
├── Re-detect SIM (AT+CPIN?)
└── NO auto run (user must trigger manually)

Used in Workflows:
├── hardware_restart (Step 1)

Output → UI Mapping:
└── data["modem_online"] → RESPON column
```

**Note**: ResetHardwareSkill DIHAPUS. Hanya RestartHardwareSkill yang dipakai.

---

## 10. Complete Workflow Execution Paths

### reactivate_full (6 steps)

```
Step 1: cek_nomor
  ├── Command: AT+CNUM / *185#
  ├── Parser: _parse_cnum() + _parse_ussd_number()
  ├── [NEW] Parser: _extract_grace_date()
  │   └── Regex: r'Active\s+(\d{2}-\d{2}-\d{4})'
  │       └── Output: data["grace_date"]
  ├── [NEW] Parser: _classify_card_status(grace_date)
  │   └── Logic: grace_date - today = masa aktif
  │       ├── masa aktif > 0 → AKTIF
  │       ├── -30 ≤ masa aktif ≤ 0 → TENGGANG
  │       └── masa aktif < -30 → HANGUS
  │       └── Output: data["card_status"]
  └── Output: {number, grace_date, card_status}
      → PortWorkerState: nomor, masa_aktif

NOTE: Kata "Active" di response *185# BUKAN status kartu.
Status diHITUNG dari rumus: grace_date - today = masa aktif.

Step 2: cek_status
  ├── Command: AT+CPIN?
  ├── Parser: parse_cpin_response()
  └── Output: {cpin_state}
      → PortWorkerState: status

Step 3: cek_nik
  ├── [FIX] Command: *888*4444*1# (was *185#)
  ├── [NEW] Parser: _extract_nik()
  └── Output: {nik}
      → PortWorkerState: nik

Step 4: cek_kk
  ├── [REWRITE] Source: cache → DB → Telegram
  ├── [NEW] Parser: _extract_kk()
  └── Output: {kk, source}
      → PortWorkerState: kk

Step 5: inject_reaktivasi
  ├── Command: *888*89*1*{NIK}*{KK}#
  ├── [NEW] Parser: classify_injection_response()
  ├── [NEW] Parser: _evaluate_provisional()
  └── Output: {injected, provisional, card_status}
      → PortWorkerState: respon

Step 6: verify_grace
  ├── Command: *185#
  ├── [NEW] Parser: _extract_grace_date()
  ├── [NEW] Parser: _classify_card_status()
  ├── [NEW] Parser: has_grace_date_changed()
  ├── [NEW] Parser: evaluate_business_outcome()
  └── Output: {success, grace_date_after, card_status, outcome}
      → PortWorkerState: masa_aktif, respon
```

---

## 11. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKFLOW CONTEXT                          │
│  nomor ← cek_nomor                                          │
│  nik ← cek_nik                                              │
│  kk ← cek_kk                                                │
│  status_awal ← cek_status                                   │
│  grace_date ← cek_nomor (from *185# response)               │
│  card_status ← DIHITUNG dari (grace_date - today)           │
│  grace_akhir ← verify_grace                                  │
│  injection_attempt ← inject_reaktivasi                       │
│                                                              │
│  NOTE: Status BUKAN dari kata "Active" di response.          │
│  Status diHITUNG dari rumus: grace_date - today = masa aktif │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                 SKILL EXECUTION                              │
│  Skill.execute(port, skill_resolver, command_id)            │
│    → SkillResult(success, data, error)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│              ENGINE _on_step_complete()                       │
│  _SKILL_RESULT_TO_STATE = {                                 │
│    "number": "nomor",                                       │
│    "nik": "nik",                                            │
│    "kk": "kk",                                              │
│    "grace_date": "masa_aktif",                              │
│  }                                                          │
│  _SKILL_RESULT_TO_RESPON = {                                │
│    "cpin_state", "card_status", "modem_online",             │
│    "ready", "injected", "provisional", "outcome"            │
│  }                                                          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│              PORTWORKERSTATE UPDATE                           │
│  state.set_card_data(nomor, nik, kk, masa_aktif, respon)   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│              EVENTBUS PUBLICATION                            │
│  EventBus.publish("port.data.updated", {                    │
│    port, nomor, nik, kk, status, respon, masa_aktif         │
│  })                                                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│              CONTROLLER FORWARDING                           │
│  _on_port_data_updated() → UIEvent.PORT_UPDATE              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│              GUI UPDATE                                      │
│  _on_port_update() → PortStatusTable.update_cell()          │
│  NOMOR | NIK | KK | STATUS | RESPON | MASA AKTIF            │
└─────────────────────────────────────────────────────────────┘
```
