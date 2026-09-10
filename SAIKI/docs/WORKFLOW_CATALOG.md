# SAIKI — Workflow Catalog

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## Workflow → Skill Mapping

### WC-001: CHECK_NUMBER

| Field | Value |
|-------|-------|
| Workflow | `check_number` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `cek_nomor` | AT+CNUM, USSD fallback | IMPLEMENTED |

---

### WC-002: CHECK_STATUS

| Field | Value |
|-------|-------|
| Workflow | `check_status` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `cek_status` | AT+CPIN? | IMPLEMENTED |

---

### WC-003: CHECK_NIK

| Field | Value |
|-------|-------|
| Workflow | `check_nik` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `cek_nik` | USSD *185# | IMPLEMENTED |

---

### WC-004: CHECK_KK

| Field | Value |
|-------|-------|
| Workflow | `check_kk` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `cek_kk` | USSD *185# | IMPLEMENTED |

---

### WC-005: CHECK_DATA

| Field | Value |
|-------|-------|
| Workflow | `check_data` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `cek_nomor` | AT+CNUM, USSD fallback | IMPLEMENTED |
| 2 | `cek_nik` | USSD *185# | IMPLEMENTED |
| 3 | `cek_kk` | USSD *185# | IMPLEMENTED |

---

### WC-006: REACTIVATE_FAST

| Field | Value |
|-------|-------|
| Workflow | `reactivate_fast` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `inject_reaktivasi` | USSD *185# | IMPLEMENTED |
| 2 | `verify_grace` | USSD *185# | IMPLEMENTED |

---

### WC-007: REACTIVATE_FULL

| Field | Value |
|-------|-------|
| Workflow | `reactivate_full` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `cek_nomor` | AT+CNUM, USSD fallback | IMPLEMENTED |
| 2 | `cek_status` | AT+CPIN? | IMPLEMENTED |
| 3 | `cek_nik` | USSD *185# | IMPLEMENTED |
| 4 | `cek_kk` | USSD *185# | IMPLEMENTED |
| 5 | `inject_reaktivasi` | USSD *185# | IMPLEMENTED |
| 6 | `verify_grace` | USSD *185# | IMPLEMENTED |

---

### WC-008: HARDWARE_RESTART

| Field | Value |
|-------|-------|
| Workflow | `hardware_restart` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `restart_hardware` | ATZ | IMPLEMENTED |

---

### WC-009: HARDWARE_RESET

| Field | Value |
|-------|-------|
| Workflow | `hardware_reset` |
| Status | **COMPLETE** |

| Step | Skill | AT/USSD | Status |
|------|-------|---------|--------|
| 1 | `reset_hardware` | Serial close/reopen + AT+CPIN? | IMPLEMENTED |

---

## Summary

| Workflow | Steps | Status |
|----------|-------|--------|
| `check_number` | 1 | COMPLETE |
| `check_status` | 1 | COMPLETE |
| `check_nik` | 1 | COMPLETE |
| `check_kk` | 1 | COMPLETE |
| `check_data` | 3 | COMPLETE |
| `reactivate_fast` | 2 | COMPLETE |
| `reactivate_full` | 6 | COMPLETE |
| `hardware_restart` | 1 | COMPLETE |
| `hardware_reset` | 1 | COMPLETE |

**All 9 workflows are COMPLETE.**
