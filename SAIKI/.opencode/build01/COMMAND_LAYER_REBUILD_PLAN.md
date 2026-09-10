# COMMAND LAYER REBUILD PLAN

Detailed technical plan untuk rebuild command layer SAIKI.

---

## Current State

### Skills (8 total)

| Skill | File | Command | Parser | Issue |
|-------|------|---------|--------|-------|
| CekNomorSkill | `cek_nomor.py` | `AT+CNUM` + `*185#` | `_parse_cnum()`, `_parse_ussd_number()` | Missing grace_date extraction |
| CekStatusSkill | `cek_status.py` | `AT+CPIN?` | `parse_cpin_response()` | OK |
| CekNikSkill | `cek_nik.py` | `*185#` | None | **WRONG CODE** — should be `*888*4444*1#` |
| CekKkSkill | `cek_kk.py` | `*185#` | None | **WRONG** — KK not from USSD |
| InjectReaktivasiSkill | `inject_reaktivasi.py` | configurable | None | Missing parser |
| VerifyGraceSkill | `verify_grace.py` | `*185#` | `_classify_card_status()`, `_extract_grace_date()` | Missing before/after comparison |
| RestartHardwareSkill | `restart_hardware.py` | `ATZ` | `check_modem()` | OK — tunggal + massal |

**Note**: ResetHardwareSkill DIHAPUS. Hanya RestartHardwareSkill yang dipakai.

### Workflows (8 total — hardware_reset removed)

| Workflow | Steps | Issue |
|----------|-------|-------|
| check_number | `cek_nomor` | OK |
| check_status | `cek_status` | OK |
| check_nik | `cek_nik` | WRONG USSD code |
| check_kk | `cek_kk` | WRONG USSD code |
| check_data | `cek_nomor` → `cek_nik` → `cek_kk` | Depends on wrong skills |
| reactivate_fast | `inject_reaktivasi` → `verify_grace` | Missing parsers |
| reactivate_full | `cek_nomor` → `cek_status` → `cek_nik` → `cek_kk` → `inject_reaktivasi` → `verify_grace` | Depends on wrong skills |
| hardware_restart | `restart_hardware` | OK — tunggal + massal |

### Command Routing (20 routes — cmd.reset_modem removed)

| Route | Event | Workflow | Issue |
|-------|-------|----------|-------|
| `cmd.cek_nomor` | `cek_nomor` | `check_number` | OK |
| `cmd.cek_status` | `cek_status` | `check_status` | OK |
| `cmd.cek_nik` | `cek_nik` | `check_nik` | WRONG USSD code |
| `cmd.cari_kk` | `cari_kk` | `check_kk` | WRONG USSD code |
| `cmd.cek_limit` | `cek_limit` | `check_number` | Should be separate |
| `cmd.reactivate` | `reaktivasi` | `reactivate_full` | Depends on wrong skills |
| `cmd.restart_port` | `restart_port` | `hardware_restart` | OK — tunggal |
| `cmd.restart_all` | `restart_all` | `hardware_restart` | OK — massal |
| `cmd.force_retry` | `force_retry` | None | OK |

---

## Target State

### Fixed Skills

| Skill | Command | Parser | Output Fields |
|-------|---------|--------|---------------|
| CekNomorSkill | `AT+CNUM` + `*185#` | `_parse_cnum()` + `_parse_ussd_number()` + `_extract_grace_date()` + `_classify_card_status()` | `number`, `grace_date`, `card_status` (card_status DIHITUNG dari `grace_date - today`) |
| CekStatusSkill | `AT+CPIN?` | `parse_cpin_response()` | `cpin_state`, `sim_ready` |
| CekNikSkill | `*888*4444*1#` | `_extract_nik()` | `nik` |
| CekKkSkill | cache/DB/Telegram | `_extract_kk()` | `kk`, `source` |
| InjectReaktivasiSkill | `*888*89*1*{NIK}*{KK}#` | `classify_injection_response()` + `_evaluate_provisional()` | `injected`, `provisional`, `card_status` |
| VerifyGraceSkill | `*185#` | `_extract_grace_date()` + `_classify_card_status()` + `has_grace_date_changed()` + `evaluate_business_outcome()` | `success`, `grace_date_before`, `grace_date_after`, `card_status`, `outcome` |
| CekLimitSkill | configurable USSD | `_extract_pulsa()` | `pulsa`, `raw_response` |
| RestartHardwareSkill | `ATZ` | `check_modem()` | `restart_sent`, `modem_online` |

**Note**: ResetHardwareSkill DIHAPUS. Hanya RestartHardwareSkill yang dipakai (tunggal + massal).

### New Parsers Module

```
SAIKI/worker/ussd/classification.py
├── classify_ussd_response(raw) → USSDClassification
├── classify_ussd_intent(text) → USSDIntent
├── classify_ussd_evidence(text) → USSDEvidence
├── extract_ussd_payload(raw) → str | None
├── extract_ussd_status_only(raw) → str | None
├── has_incomplete_ussd_payload(raw) → bool
├── is_ussd_payload_complete(raw) → bool
├── extract_payload_text(raw) → str
└── extract_payload_number(raw) → str
```

### New Command Registry

```
SAIKI/worker/commands/registry.py
├── CommandDefinition (dataclass)
├── COMMAND_REGISTRY (dict[str, CommandDefinition])
├── get_command(name) → CommandDefinition
├── get_ussd_code(name) → str
├── get_at_command(name) → str
└── get_parser(name) → callable
```

---

## Migration Strategy

### Approach: Incremental Fix (Not Big Bang)

1. **Phase 1**: Fix individual skills (no registry yet)
2. **Phase 2**: Port parsers from GOOD
3. **Phase 3**: Create registry, refactor skills to use it

### Why Not Registry First?

- Registry is a refactoring, not a bug fix
- Skills can be fixed independently
- Registry adds complexity without fixing bugs
- Incremental approach reduces risk

### Dependency Order

```
Phase 1.1 (CekNikSkill fix)
  ↓
Phase 1.2 (CekKkSkill fix)
  ↓
Phase 1.3 (CekNomorSkill fix)
  ↓
Phase 1.4 (InjectReaktivasiSkill fix)
  ↓
Phase 1.5 (VerifyGraceSkill fix)
  ↓
Phase 2.1-2.8 (Port parsers)
  ↓
Phase 3.1-3.6 (Registry + cleanup)
```

### Parallel Work

Some tasks can be done in parallel:
- Phase 1.1 + Phase 1.3 (independent skills)
- Phase 2.1 + Phase 2.2 + Phase 2.3 (all go to classification.py)
- Phase 2.4 + Phase 2.5 (independent parsers)

---

## File Change Summary

### Phase 1 Files

| File | Change Type | Risk |
|------|-------------|------|
| `worker/skills/cek_nik.py` | MODIFY — change USSD code + add parser | LOW |
| `worker/skills/cek_kk.py` | REWRITE — new logic (cache/DB/Telegram) | MEDIUM |
| `worker/skills/cek_nomor.py` | MODIFY — add grace_date + card_status extraction | LOW |
| `worker/skills/inject_reaktivasi.py` | MODIFY — add parser | LOW |
| `worker/skills/verify_grace.py` | MODIFY — add comparison + outcome | LOW |
| `automation/engine.py` | MODIFY — update result mappings | LOW |
| `workflow/context.py` | MODIFY — add grace_date field | LOW |
| `workflow/definitions.py` | MODIFY — add check_limit workflow | LOW |
| `workflow/registry.py` | MODIFY — register check_limit | LOW |
| `worker/skills/cek_limit.py` | CREATE — new skill | LOW |
| `worker/ui/controller.py` | MODIFY — update routing | LOW |

### Phase 2 Files

| File | Change Type | Risk |
|------|-------------|------|
| `worker/ussd/classification.py` | CREATE — new module | MEDIUM |
| `worker/skills/cek_nik.py` | MODIFY — use classifier | LOW |
| `worker/skills/cek_kk.py` | MODIFY — use classifier | LOW |
| `worker/skills/inject_reaktivasi.py` | MODIFY — use classifier | LOW |
| `worker/skills/verify_grace.py` | MODIFY — use classifier | LOW |

### Phase 3 Files

| File | Change Type | Risk |
|------|-------------|------|
| `worker/commands/registry.py` | CREATE — new module | MEDIUM |
| `worker/commands/__init__.py` | CREATE — new module | LOW |
| All 8 skill files | MODIFY — use registry | MEDIUM |
| `worker/skills/dependency_resolver.py` | MODIFY — resolve from registry | MEDIUM |
| `worker/system_bootstrap.py` | MODIFY — update factories | LOW |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking existing tests | HIGH | MEDIUM | Run tests after each task |
| Parser incompatibility | MEDIUM | HIGH | Port parser incrementally, test each |
| Registry refactor breaks skills | MEDIUM | HIGH | Refactor one skill at a time |
| Missing edge cases in parsers | MEDIUM | MEDIUM | Port from GOOD (battle-tested) |
| New CekKkSkill logic fails | MEDIUM | HIGH | Keep old behavior as fallback |

---

## Success Criteria

After all 3 phases:
1. All 8 skills return correct data
2. All 9 workflows complete successfully
3. UI columns update correctly (NOMOR/NIK/KK/MASA AKTIF/RESPON)
4. All 280+ tests pass
5. No regressions in existing functionality
