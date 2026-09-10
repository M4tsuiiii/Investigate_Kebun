# SAIKI — Skill Catalog

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## Skill Inventory

### SK-001: CekNomorSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/cek_nomor.py` |
| Purpose | Retrieve SIM phone number |
| Status | IMPLEMENTED |

**Dependencies**: ATClient, UssdRuntime (optional)  
**Input**: `port`, `command_id`, `settings`  
**Output**: `SkillResult(data={"number": "081234567890", "modem_responsive": True, "raw_cnum": "..."})`  

**AT Commands**:
1. `AT+CNUM` → parse `+CNUM: "","number",type`
2. If no number: USSD dial configured code → parse number from response

**Failure modes**:
- No AT client → `"No AT client available"`
- AT+CNUM exception → try USSD fallback
- No USSD code configured → `"number_ussd_not_configured"`
- No USSD runtime → skip USSD fallback
- No number found → `"no_number_found"`

---

### SK-002: CekStatusSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/cek_status.py` |
| Purpose | Check SIM/CPIN status |
| Status | IMPLEMENTED |

**Dependencies**: ATClient  
**Input**: `port`, `command_id`, `timeout`  
**Output**: `SkillResult(data={"cpin_state": "READY", "raw_response": "...", "sim_ready": True})`  

**AT Commands**:
1. `AT+CPIN?` → classify via `parse_cpin_response()`

**Failure modes**:
- No AT client → `"No AT client available"`
- NOT_INSERTED → `"SIM not inserted"`
- PIN_REQUIRED → `"SIM PIN required"`
- NOT_READY/UNKNOWN → `"SIM not ready: {state}"`

---

### SK-003: CekNikSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/cek_nik.py` |
| Purpose | Check NIK registration via USSD |
| Status | IMPLEMENTED |

**Dependencies**: UssdRuntime  
**Input**: `port`, `command_id`, `timeout`  
**Output**: `SkillResult(data={"raw_response": "...", "has_payload": True, "ussd_code": "*185#"})`  

**AT Commands**:
1. USSD `*185#` → return raw response

**Failure modes**:
- No USSD runtime → `"No USSD runtime available"`
- USSD dial failed → `"USSD dial failed"`
- Empty response → `"Empty USSD response"`

---

### SK-004: CekKkSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/cek_kk.py` |
| Purpose | Check KK (family card) registration via USSD |
| Status | IMPLEMENTED |

**Dependencies**: UssdRuntime  
**Input**: `port`, `command_id`, `timeout`  
**Output**: `SkillResult(data={"raw_response": "...", "has_payload": True, "ussd_code": "*185#"})`  

**AT Commands**:
1. USSD `*185#` → return raw response

**Failure modes**: Same as CekNikSkill

---

### SK-005: InjectReaktivasiSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/inject_reaktivasi.py` |
| Purpose | Send reactivation command via USSD |
| Status | IMPLEMENTED |

**Dependencies**: UssdRuntime  
**Input**: `port`, `command_id`, `ussd_code` (default `*185#`), `timeout`  
**Output**: `SkillResult(data={"raw_response": "...", "injected": True, "ussd_code": "*185#"})`  

**AT Commands**:
1. USSD `*185#` (or configured code) → return raw response

**Failure modes**:
- No USSD runtime → `"No USSD runtime available"`
- Dial failed → `"USSD dial failed — no response"`
- Empty response → `"Empty response after injection"`

---

### SK-006: VerifyGraceSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/verify_grace.py` |
| Purpose | Verify card grace period via USSD |
| Status | IMPLEMENTED |

**Dependencies**: UssdRuntime  
**Input**: `port`, `command_id`, `timeout`  
**Output**: `SkillResult(data={"raw_response": "...", "card_status": "AKTIF", "grace_date": "..."})`  

**AT Commands**:
1. USSD `*185#` → classify card status

**Card status classification**:
- Contains "hangus"/"burned" → HANGUS
- Contains "tenggang"/"grace" → TENGGANG
- Contains "aktif"/"active" → AKTIF
- Otherwise → UNKNOWN

**Failure modes**:
- No USSD runtime → `"No USSD runtime available"`
- Dial failed → `"USSD dial failed — no response"`
- HANGUS → `"Card is HANGUS (burned): {raw}"`
- UNKNOWN → `"Unknown card status: {raw}"`

---

### SK-007: RestartHardwareSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/restart_hardware.py` |
| Purpose | Restart modem hardware via ATZ |
| Status | IMPLEMENTED |

**Dependencies**: ATClient  
**Input**: `port`, `command_id`, `wait_seconds` (default 15s), `timeout`  
**Output**: `SkillResult(data={"restart_sent": True, "modem_online": True})`  

**AT Commands**:
1. `ATZ` → restart modem
2. Wait `STABILIZATION_SECONDS` (15s)
3. `AT` (check_modem) → verify modem online

**Failure modes**:
- No AT client → `"No AT client available"`
- Modem not back online → `"Modem did not come back online after restart"`

---

### SK-008: ResetHardwareSkill

| Field | Value |
|-------|-------|
| File | `worker/skills/reset_hardware.py` |
| Purpose | Full hardware reset cycle |
| Status | IMPLEMENTED |

**Dependencies**: SerialAdapter, ATClient, CpinRuntime (optional)  
**Input**: `port`, `command_id`, `wait_seconds` (default 15s)  
**Output**: `SkillResult(data={"modem_online": True, "cpin_state": "READY", "ready": True})`  

**Sequence**:
1. Stop CpinRuntime
2. Close serial
3. Wait 15s
4. Reopen serial
5. Start CpinRuntime
6. Check modem (AT)
7. Detect SIM (AT+CPIN?)

**Failure modes**:
- No serial or AT client → `"No serial adapter or AT client available"`
- Failed to reopen → `"Failed to reopen serial port"`
- Modem offline → `"Modem offline after reset"`
- SIM not ready → `"SIM not ready: {state}"`
