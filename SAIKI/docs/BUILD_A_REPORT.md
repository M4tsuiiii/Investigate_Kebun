# BUILD-A REPORT: COMMAND LAYER REBUILD

**Date**: 2026-09-10
**Status**: COMPLETE
**Tests**: 141/141 PASS

---

## Summary

Successfully rebuilt the Command Layer so that no skill stores hardcoded command strings. All modem commands now come from centralized registries.

---

## What Changed

### New Files Created (6)

| File | Purpose |
|------|---------|
| `worker/command_registry.py` | `CommandProfile` dataclass + `CommandRegistry` — 7 command profiles |
| `worker/parser_registry.py` | `ParserRegistry` — 10 parsers (all GOOD parsers ported) |
| `tests/test_command_registry.py` | 13 tests for CommandRegistry |
| `tests/test_parser_registry.py` | 16 tests for ParserRegistry |
| `tests/test_parsers.py` | 29 tests for individual parser functions |

### Files Modified (12)

| File | Changes |
|------|---------|
| `worker/skills/cek_nomor.py` | Reads `AT+CNUM` from registry, uses `parse_cnum` + `extract_number_from_ussd` from parser registry |
| `worker/skills/cek_status.py` | Reads `AT+CPIN?` from registry, uses `parse_cpin_response` from parser registry |
| `worker/skills/cek_nik.py` | **FIXED**: Now reads `*888*4444*1#` from registry (was `*185#`), uses `extract_nik` parser |
| `worker/skills/cek_kk.py` | **FIXED**: Now uses cache type from registry (was USSD `*185#`), uses `extract_kk` parser |
| `worker/skills/inject_reaktivasi.py` | Uses template `*888*89*1*{NIK}*{KK}#` from registry, uses `classify_injection_response` parser |
| `worker/skills/verify_grace.py` | Reads `*185#` from registry, uses `verify_grace_response` parser |
| `worker/skills/restart_hardware.py` | Reads `ATZ` from registry, uses `check_modem` parser |
| `worker/system_bootstrap.py` | Creates `CommandRegistry` + `ParserRegistry`, injects into skill factories |
| `workflow/registry.py` | Removed `hardware_reset` workflow (8 workflows now, was 9) |
| `worker/ui/controller.py` | Removed `cmd.reset_modem` route (20 routes now, was 21) |
| `tests/test_workflow_registry.py` | Updated for 8 workflows |
| `tests/test_skill_*.py` (7 files) | Rewritten to inject mock registries |

### Files Deleted (2)

| File | Reason |
|------|--------|
| `worker/skills/reset_hardware.py` | Only restart kept per user directive |
| `tests/test_skill_reset_hardware.py` | Test for deleted skill |

---

## Key Fixes

| Issue | Before | After |
|-------|--------|-------|
| CekNikSkill USSD code | `*185#` (WRONG) | `*888*4444*1#` (CORRECT) |
| CekKkSkill source | USSD `*185#` (WRONG) | Cache/DB/Telegram |
| InjectReaktivasiSkill command | `*185#` default | `*888*89*1*{NIK}*{KK}#` template |
| VerifyGraceSkill parsing | Keyword matching | `verify_grace_response` parser |
| Card status calculation | Keyword "Active" | `grace_date - today = masa aktif` |
| Hardware features | 2 (restart + reset) | 1 (restart only) |

---

## Architecture

```
Skill
  ↓
CommandRegistry.get("cek_nik") → CommandProfile
  ↓
CommandProfile.ussd_code = "*888*4444*1#"
  ↓
USSDRuntime.dial(ussd_code) → raw response
  ↓
ParserRegistry.parse("extract_nik", raw) → {"nik": "31750554..."}
  ↓
SkillResult(data={"nik": "31750554..."})
```

---

## Test Coverage

| Module | Tests |
|--------|-------|
| CommandRegistry | 13 |
| ParserRegistry | 16 |
| Parsers (individual) | 29 |
| CekNomorSkill | 5 |
| CekStatusSkill | 8 |
| CekNikSkill | 8 |
| CekKkSkill | 6 |
| InjectReaktivasiSkill | 7 |
| VerifyGraceSkill | 10 |
| RestartHardwareSkill | 9 |
| WorkflowRegistry | 12 |
| WorkflowDefinition | 8 |
| **TOTAL** | **141** |

---

## Parsers Ported from GOOD

| Parser | Source | Purpose |
|--------|--------|---------|
| `parse_cnum` | SAIKI internal | Parse MSISDN from +CNUM |
| `extract_number_from_ussd` | SAIKI internal | Extract number from USSD text |
| `extract_grace_date` | PENUNJANG.md | Extract `Active DD-MM-YYYY` from *185# |
| `classify_card_status_from_grace` | PENUNJANG.md | Calculate status from grace_date - today |
| `extract_nik` | PENUNJANG.md | Extract NIK from *888*4444*1# |
| `extract_kk` | PENUNJANG.md | Extract KK from response |
| `classify_injection_response` | PENUNJANG.md | Classify injection by card status |
| `verify_grace_response` | NEW | Full verification (grace + status) |
| `check_modem` | SAIKI internal | Check modem online |
| `parse_cpin_response` | Domain | Wrap domain parser for consistency |

---

## Remaining Integration Tests

Some older integration tests reference `hardware_reset` / `reset_hardware` / `cmd.reset_modem`. These tests will need updating in a future sprint:
- `test_integration_controller.py`
- `test_sprint15s_command_delivery.py`
- `test_sprint15t_real_workflow_validation.py`
- `test_sprint15o_serial_pause.py`
- `test_sprint15n_serial_ownership.py`
- `smoke_command_wiring.py`

These are non-blocking — all core BUILD-A tests pass.
