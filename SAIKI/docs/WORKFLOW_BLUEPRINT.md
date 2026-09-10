# SAIKI — Workflow Blueprint

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## 1. Atomic Workflows (single skill)

### WF-001: CHECK_NUMBER

| Field | Value |
|-------|-------|
| Name | `check_number` |
| Trigger | Manual (button/context menu) or auto-run |
| Steps | `["cek_nomor"]` |

**Skill**: CekNomorSkill  
**Modem commands**: `AT+CNUM` → parse MSISDN → USSD fallback if no number  
**Expected response**: `+CNUM: "","081234567890",129`  
**Success condition**: Parsed number ≠ None  
**Failure conditions**: No AT client, AT+CNUM error, no number found, USSD code not configured

---

### WF-002: CHECK_STATUS

| Field | Value |
|-------|-------|
| Name | `check_status` |
| Trigger | Manual or auto-run |
| Steps | `["cek_status"]` |

**Skill**: CekStatusSkill  
**Modem commands**: `AT+CPIN?`  
**Expected response**: `+CPIN: READY`  
**Success condition**: CpinState = READY  
**Failure conditions**: NOT_INSERTED, PIN_REQUIRED, NOT_READY, UNKNOWN, no AT client

---

### WF-003: CHECK_NIK

| Field | Value |
|-------|-------|
| Name | `check_nik` |
| Trigger | Manual or auto-run |
| Steps | `["cek_nik"]` |

**Skill**: CekNikSkill  
**Modem commands**: USSD `*185#`  
**Expected response**: NIK information payload  
**Success condition**: Non-empty USSD response  
**Failure conditions**: No USSD runtime, USSD dial failed, empty response

---

### WF-004: CHECK_KK

| Field | Value |
|-------|-------|
| Name | `check_kk` |
| Trigger | Manual or auto-run |
| Steps | `["cek_kk"]` |

**Skill**: CekKkSkill  
**Modem commands**: USSD `*185#`  
**Expected response**: KK information payload  
**Success condition**: Non-empty USSD response  
**Failure conditions**: No USSD runtime, USSD dial failed, empty response

---

### WF-005: HARDWARE_RESTART

| Field | Value |
|-------|-------|
| Name | `hardware_restart` |
| Trigger | Manual (Restart Port / Restart All) |
| Steps | `["restart_hardware"]` |

**Skill**: RestartHardwareSkill  
**Modem commands**: `ATZ` → wait 15s → `AT` (check modem)  
**Expected response**: OK after ATZ, modem responds after wait  
**Success condition**: Modem online after restart  
**Failure conditions**: No AT client, modem did not come back online

---

### WF-006: HARDWARE_RESET

| Field | Value |
|-------|-------|
| Name | `hardware_reset` |
| Trigger | Manual (Reset Port / Reset Modem) |
| Steps | `["reset_hardware"]` |

**Skill**: ResetHardwareSkill  
**Modem commands**: Close serial → wait 15s → reopen → `AT+CPIN?`  
**Expected response**: Serial reopens, +CPIN: READY  
**Success condition**: Modem online AND CpinState = READY  
**Failure conditions**: No serial, failed to reopen, modem offline, SIM not ready

---

## 2. Composite Workflows (multi-skill)

### WF-010: CHECK_DATA

| Field | Value |
|-------|-------|
| Name | `check_data` |
| Trigger | Auto-run or Cek Nomor Massal |
| Steps | `["cek_nomor", "cek_nik", "cek_kk"]` |

**Execution order**:
1. `cek_nomor` → AT+CNUM → get phone number
2. `cek_nik` → USSD *185# → get NIK
3. `cek_kk` → USSD *185# → get KK

**Success condition**: All 3 steps succeed  
**Failure**: Stops at first failure  
**Note**: This is the workflow for "Cek Nomor Massal" button

---

### WF-011: REACTIVATE_FAST

| Field | Value |
|-------|-------|
| Name | `reactivate_fast` |
| Trigger | Auto-run |
| Steps | `["inject_reaktivasi", "verify_grace"]` |

**Execution order**:
1. `inject_reaktivasi` → USSD *185# → send reactivation
2. `verify_grace` → USSD *185# → check card status

**Success condition**: inject succeeds AND card status is AKTIF or TENGGANG  
**Failure**: inject fails, or card is HANGUS  
**Retry**: Max 1 retry if grace unchanged (ReactivateRetryPolicy)

---

### WF-012: REACTIVATE_FULL

| Field | Value |
|-------|-------|
| Name | `reactivate_full` |
| Trigger | Manual (Reaktivasi Massal) or auto-run |
| Steps | `["cek_nomor", "cek_status", "cek_nik", "cek_kk", "inject_reaktivasi", "verify_grace"]` |

**Execution order**:
1. `cek_nomor` → AT+CNUM → get phone number
2. `cek_status` → AT+CPIN? → verify SIM ready
3. `cek_nik` → USSD *185# → get NIK
4. `cek_kk` → USSD *185# → get KK
5. `inject_reaktivasi` → USSD *185# → send reactivation
6. `verify_grace` → USSD *185# → check card status

**Success condition**: All 6 steps succeed, card is AKTIF/TENGGANG  
**Failure**: Stops at first failure  
**Retry**: Max 1 retry if grace unchanged

---

## 3. Workflow Execution Rules

| Rule | Description |
|------|-------------|
| Step ordering | Steps execute in list order, strictly sequential |
| First failure stops | If any step fails, workflow terminates immediately |
| No inter-skill calls | Skills never call other skills |
| Cleanup between steps | `CleanupManager.full_cleanup()` runs between non-final steps |
| Cooldown between steps | `DIAL_COOLDOWN_SECONDS` (4s) between USSD operations |
| Timeout per step | Configurable per skill, defaults: AT=2s, USSD=30s |
| Thread isolation | Each workflow runs in its own thread |

---

## 4. Workflow → Mode Mapping

| AutomationMode | Workflow |
|----------------|----------|
| `CHECK_DATA` | `check_data` |
| `REACTIVATE_FAST` | `reactivate_fast` |
| `REACTIVATE_FULL` | `reactivate_full` |

The mode is set by the controller before enqueueing mass commands. The policy selects the workflow based on mode.
