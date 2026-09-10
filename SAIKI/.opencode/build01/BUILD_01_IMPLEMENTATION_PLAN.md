# BUILD_01: IMPLEMENTATION PLAN — Modem Command Layer Rebuild

Sprint ini memperbaiki semua AT command, USSD command, parser, dan skill wiring yang salah.

---

## Executive Summary

### Problem Statement

SAIKI backend architecture benar. Tapi command layer punya **5 critical bugs** dan **8 missing features**:

| # | Severity | Issue | Impact |
|---|----------|-------|--------|
| 1 | **CRITICAL** | `CekNikSkill` kirim `*185#` bukan `*888*4444*1#` | NIK tidak bisa diambil |
| 2 | **CRITICAL** | `CekKkSkill` kirim `*185#` (sama dengan NIK) | KK tidak bisa diambil |
| 3 | **CRITICAL** | `InjectReaktivasiSkill` tidak ada parser | Response tidak di-classify |
| 4 | **CRITICAL** | `VerifyGraceSkill` tidak compare before/after | Success criteria tidak jalan |
| 5 | **CRITICAL** | CekNomorSkill tidak extract grace date dari `*185#` | MASA AKTIF selalu "-" |
| 6 | **HIGH** | Missing 9-tier USSD classification | Response salah di-classify |
| 7 | **HIGH** | Missing USSD intent classification | Tidak bisa tentukan success/failure |
| 8 | **HIGH** | Missing business outcome evaluation | Tidak ada SUCCESS/TENGGANG/FAILED |
| 9 | **HIGH** | Missing provisional success evaluation | Injection response tidak di-evaluate |
| 10 | **HIGH** | Missing NIK extraction parser | NIK tidak di-extract dari response |
| 11 | **MEDIUM** | Missing evidence classification | Tenggang/hangus/aktif evidence hilang |
| 12 | **MEDIUM** | `cek_nik` dan `cek_kk` identik (duplikat) | Code smell, maintenance burden |
| 13 | **MEDIUM** | `parse_cpin_response` duplikat di 2 tempat | Potential inconsistency |

### Scope

- **8 skills** yang communicating dengan modem (reset_hardware dihapus)
- **8 workflows** yang menggunakan skills (hardware_reset dihapus)
- **25 parsers** dari GOOD yang perlu di-port (17 high-value)
- **1 Command Registry** baru (8 entries — reset_hardware dihapus)

### Out of Scope

- Auto-run default/persistence (GAP-001/002) — sprint terpisah
- Telegram gateway (P2) — belum ready
- Report tab / export (P2) — belum ready
- Modem health dashboard (P2) — belum ready
- Forensics/audit — sudah selesai

---

## Phase 1: Fix Critical Bugs (Week 1)

**Goal**: Semua skill kirim command yang benar dan return data yang benar.

### 1.1 Fix CekNikSkill — WRONG USSD CODE

**Current**: `*185#` (cek nomor code)
**Correct**: `*888*4444*1#` (cek NIK code)

**Files affected**:
- `SAIKI/worker/skills/cek_nik.py` — change USSD code
- `SAIKI/worker/skills/cek_nik.py` — add NIK extraction parser

**Risk**: LOW — single line change + add parser
**Rollback**: Revert to `*185#`

### 1.2 Fix CekKkSkill — NOT USSD-BASED

**Current**: Duplicates CekNikSkill, sends `*185#`
**Correct**: KK comes from cache → DB → Telegram (NOT from USSD directly)

**Files affected**:
- `SAIKI/worker/skills/cek_kk.py` — complete rewrite

**New behavior**:
1. Check phone cache → if hit, return cached KK
2. Check local DB (panen_raya table) → if hit, return KK
3. Check format mode → if "NIK & NIK", KK = NIK
4. Telegram lookup → query bot
5. Fail → return error

**Risk**: MEDIUM — new skill logic
**Rollback**: Keep current `*185#` behavior temporarily

### 1.3 Fix CekNomorSkill — MISSING GRACE DATE EXTRACTION

**Current**: Only extracts `number` from `*185#`
**Correct**: `*185#` returns 2 data points: nomor + grace_date. Status diHITUNG dari grace_date.

**Current response pattern**:
```
"Good Morning , Your number 08586xxxxxxx, Balance Rp.0 Active 24-08-2026..."
```

**Important**: Kata "Active" di response BUKAN status kartu. Itu hanya bagian dari balance display. Status kartu diHITUNG dari rumus:
```
grace_date - today = masa aktif
```
- `masa aktif > 0` → AKTIF
- `-30 ≤ masa aktif ≤ 0` → TENGGANG
- `masa aktif < -30` → HANGUS

**New extraction**:
- Nomor: `r'(08\d{9,11})'` → `data["number"]`
- Grace Date: `r'Active\s+(\d{2}-\d{2}-\d{4})'` → `data["grace_date"]`
- Status: DIHITUNG dari `grace_date - today` → `data["card_status"]`

**Files affected**:
- `SAIKI/worker/skills/cek_nomor.py` — add grace_date extraction + calculate card_status from date math
- `SAIKI/automation/engine.py` — update `_SKILL_RESULT_TO_STATE` mapping

**Risk**: LOW — add fields to existing skill
**Rollback**: Keep current behavior (only number)

### 1.4 Fix InjectReaktivasiSkill — ADD PARSER

**Current**: Returns raw response, no classification
**Correct**: Classify response by card status (HANGUS/TENGGANG/AKTIF)

**Response patterns** (from PENUNJANG.md):
| Card Status | Response |
|------------|----------|
| HANGUS | `"Permintaan kamu sedang di proses..."` |
| TENGGANG | `"Nomor 08575xxxxxxx sedang dalam masa tenggang..."` |
| AKTIF | `"Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus"` |

**New parser**: `classify_injection_response(raw)` → returns `{"injected": bool, "provisional": str, "card_status": str}`

**Files affected**:
- `SAIKI/worker/skills/inject_reaktivasi.py` — add parser
- `SAIKI/automation/engine.py` — update `_SKILL_RESULT_TO_RESPON` mapping

**Risk**: LOW — add parser to existing skill
**Rollback**: Keep raw passthrough

### 1.5 Fix VerifyGraceSkill — ADD BEFORE/AFTER COMPARISON

**Current**: Extracts grace_date_after, no comparison
**Correct**: Compare grace_date_before vs grace_date_after

**Success criteria** (from PENUNJANG.md):
- **Sukses**: `grace_date_before ≠ grace_date_after`
- **Gagal**: `grace_date_before = grace_date_after`

**New behavior**:
- Read `grace_date` from `WorkflowContext` (written by CekNomorSkill step)
- Compare with `grace_date_after` from this skill
- Return `{"success": bool, "grace_date_before": str, "grace_date_after": str}`

**Files affected**:
- `SAIKI/worker/skills/verify_grace.py` — add comparison logic
- `SAIKI/workflow/context.py` — ensure `grace_date` field available

**Risk**: LOW — add comparison to existing skill
**Rollback**: Keep current behavior (no comparison)

### 1.6 Fix COMMAND_ROUTES — Cek Limit

**Current**: `cmd.cek_limit` routes to `check_number` (AT+CNUM)
**Correct**: Should route to dedicated USSD check (configurable)

**Files affected**:
- `SAIKI/worker/ui/controller.py` — update routing
- `SAIKI/workflow/definitions.py` — add `check_limit` workflow
- `SAIKI/worker/skills/cek_limit.py` — new skill

**Risk**: MEDIUM — new workflow + skill
**Rollback**: Keep routing to `check_number`

### 1.7 Consolidate Hardware Features — REMOVE Reset, Keep Restart Only

**Current**: 2 hardware features (restart_hardware + reset_hardware)
**Correct**: 1 hardware feature only — Restart modem (`ATZ`)

**Why**: Restart = scanning ulang seperti startup awal, tanpa auto run. Reset (serial close/open) terlalu destructive untuk regular use.

**Restart behavior**:
- Command: `ATZ` (soft reset)
- Tunggal: restart 1 port
- Massal: restart semua port
- Setelah restart: worker rescan modem, re-detect SIM

**Files affected**:
- `SAIKI/worker/skills/reset_hardware.py` — DELETE (or keep as dead code)
- `SAIKI/worker/skills/restart_hardware.py` — update AT command to `ATZ`
- `SAIKI/workflow/definitions.py` — remove `hardware_reset` workflow
- `SAIKI/workflow/registry.py` — remove `hardware_reset` registration
- `SAIKI/worker/ui/controller.py` — remove `cmd.reset_modem` routing

**Risk**: LOW — remove unused feature
**Rollback**: Keep both features

---

## Phase 2: Port MISSING Parsers (Week 2)

**Goal**: Port 17 high-value parsers dari GOOD ke SAIKI.

### 2.1 USSD Classification Engine

Port `classify_ussd_response` (9-tier + TIMEOUT) dari GOOD.

**Source**: `GOOD/worker/ussd/classification.py`
**Target**: `SAIKI/worker/ussd/classification.py` (NEW)

**Tiers**:
1. `USSD_PAYLOAD` — `+CUSD: N,"<payload>"`
2. `USSD_EMPTY_PAYLOAD` — `+CUSD: N,""`
3. `USSD_STATUS_ONLY` — `+CUSD: N` (no quotes)
4. `PARTIAL_RESPONSE` — unclosed payload
5. `PROMPT_CONFIRMATION` — prompt keywords
6. `ERROR` — `+CME ERROR` / `+CMS ERROR`
7. `AT_OK` — `OK` without CUSD
8. `COMMAND_ECHO` — `AT+CUSD=` echo
9. `MODEM_NOTIFICATION` — `+WIND:`/`+CPIN:`/`+CREG:`
10. `WAITING_RESPONSE` — fallback
11. `TIMEOUT` — empty

**Files affected**:
- `SAIKI/worker/ussd/classification.py` (NEW)
- `SAIKI/worker/skills/cek_nik.py` — use classifier
- `SAIKI/worker/skills/cek_kk.py` — use classifier
- `SAIKI/worker/skills/inject_reaktivasi.py` — use classifier
- `SAIKI/worker/skills/verify_grace.py` — use classifier

**Risk**: MEDIUM — new module, integrates with all USSD skills
**Rollback**: Keep raw passthrough

### 2.2 USSD Intent Classification

Port `classify_ussd_intent` dari GOOD.

**Source**: `GOOD/worker/ussd/classification.py`
**Target**: `SAIKI/worker/ussd/classification.py`

**Intents**:
1. `EMPTY_RESPONSE`
2. `NUMBER_INFO`
3. `SUCCESS_MESSAGE`
4. `REQUEST_ACCEPTED`
5. `MENU_RESPONSE`
6. `UNKNOWN`

**Files affected**:
- `SAIKI/worker/ussd/classification.py` — add intent classifier
- `SAIKI/worker/skills/inject_reaktivasi.py` — use intent classifier

**Risk**: LOW — extends existing classifier
**Rollback**: Remove intent classifier

### 2.3 Evidence Classification

Port `classify_ussd_evidence` dari GOOD.

**Source**: `GOOD/app/kebun_reaktivasi(rev).py` lines 718-735
**Target**: `SAIKI/worker/ussd/classification.py`

**Evidence flags**:
- `has_success_evidence`
- `has_processing_evidence`
- `has_tenggang_evidence`

**Files affected**:
- `SAIKI/worker/ussd/classification.py` — add evidence classifier
- `SAIKI/worker/skills/verify_grace.py` — use evidence classifier

**Risk**: LOW — extends existing classifier
**Rollback**: Remove evidence classifier

### 2.4 NIK Extraction Parser

Port NIK extraction dari GOOD.

**Source**: `GOOD/app/kebun_reaktivasi(rev).py` line 1878
**Target**: `SAIKI/worker/skills/cek_nik.py`

**Logic**:
- Regex: `r'(\d{16})'`
- Validation: `re.fullmatch(r"\d{16}", nik)`
- Response pattern: `"Nomor IM3 kamu telah terdaftar dengan ^ NIK : 31750554xxxxxxxx"`

**Files affected**:
- `SAIKI/worker/skills/cek_nik.py` — add NIK extraction

**Risk**: LOW — add parser to existing skill
**Rollback**: Remove parser

### 2.5 Grace Date Extraction from `*185#`

Port grace date extraction dari GOOD.

**Source**: `GOOD/app/kebun_reaktivasi(rev).py` lines 784-793
**Target**: `SAIKI/worker/skills/cek_nomor.py`

**Logic**:
- Stage 1: ISO format `r'(\d{4}[-/]\d{2}[-/]\d{2})'`
- Stage 2: Local format `r'(\d{2}[-/]\d{2}[-/]\d{4})'` → reverse to YYYY-MM-DD
- Stage 3: No match → `"-"`

**Files affected**:
- `SAIKI/worker/skills/cek_nomor.py` — add grace date extraction

**Risk**: LOW — add parser to existing skill
**Rollback**: Remove parser

### 2.6 Card Status Classification (Enhanced)

Port enhanced card status classification dari GOOD.

**Source**: `GOOD/app/kebun_reaktivasi(rev).py` lines 801-827
**Target**: `SAIKI/worker/skills/verify_grace.py`

**7-tier priority**:
1. `has_tenggang_evidence` → `TENGGANG`
2. `hangus` keywords → `HANGUS`
3. `aktif` keywords → `AKTIF`
4. `days_remaining is None` → `UNKNOWN`
5. `days_remaining > 0` → `AKTIF`
6. `-30 <= days_remaining <= 0` → `TENGGANG`
7. `days_remaining < -30` → `HANGUS`

**Files affected**:
- `SAIKI/worker/skills/verify_grace.py` — enhance `_classify_card_status()`

**Risk**: LOW — enhance existing parser
**Rollback**: Revert to simple keyword matching

### 2.7 Provisional Success Evaluation

Port provisional success evaluation dari GOOD.

**Source**: `GOOD/worker/reactivation/injection.py` lines 132-200
**Target**: `SAIKI/worker/skills/inject_reaktivasi.py`

**Logic**:
| Response Type | Result |
|--------------|--------|
| `USSD_STATUS_ONLY:0` | PROVISIONAL_SUCCESS |
| `USSD_EMPTY_PAYLOAD` | PROVISIONAL_WAITING |
| `PROMPT_CONFIRMATION` | FAILURE |
| `COMMAND_ECHO` | PROVISIONAL_SUCCESS |
| `USSD_PAYLOAD` + `SUCCESS_MESSAGE` | PROVISIONAL_SUCCESS |
| `USSD_PAYLOAD` + `REQUEST_ACCEPTED` | PROVISIONAL_SUCCESS |
| `ERROR` | FAILURE |
| Others | PROVISIONAL_WAITING |

**Files affected**:
- `SAIKI/worker/skills/inject_reaktivasi.py` — add provisional evaluator

**Risk**: MEDIUM — new evaluation logic
**Rollback**: Remove evaluator

### 2.8 Business Outcome Evaluation

Port business outcome evaluation dari GOOD.

**Source**: `GOOD/app/kebun_reaktivasi(rev).py` lines 844-860
**Target**: `SAIKI/worker/skills/verify_grace.py`

**Logic**:
1. `grace_changed = has_grace_date_changed(before, after)`
2. `evidence = classify_ussd_evidence(inject_response)`
3. IF `grace_changed` AND `after_status NOT IN {"", "HANGUS", "UNKNOWN"}` → `SUCCESS`
4. IF NOT `grace_changed` AND `evidence.has_tenggang_evidence` → `TENGGANG`
5. ELSE → `FAILED`

**Files affected**:
- `SAIKI/worker/skills/verify_grace.py` — add business outcome evaluator

**Risk**: MEDIUM — new evaluation logic
**Rollback**: Remove evaluator

---

## Phase 3: Command Registry + Cleanup (Week 3)

**Goal**: Centralisasi command handling, hapus duplikat, tambah missing features.

### 3.1 Create Command Registry

Create `SAIKI/worker/commands/registry.py` — single source of truth untuk semua commands.

**Registry structure**:
```python
@dataclass
class CommandDefinition:
    name: str
    feature: str
    ussd_code: str | None
    at_command: str | None
    parser: str
    success_rule: str
    output_fields: list[str]
    workflow: str
    scope: str  # "per_port" | "mass"
    eligibility: str  # "sim_ready" | "hw_ready" | "worker_alive"
```

**Registry entries** (8 commands — reset_hardware removed):
| Feature | Command | USSD/AT | Parser | Success Rule | Output Fields |
|---------|---------|---------|--------|-------------|---------------|
| Cek Nomor | `AT+CNUM` / `*185#` | `_parse_cnum()` / `_parse_ussd_number()` | Number found | number, grace_date, card_status |
| Cek Status | `AT+CPIN?` | `parse_cpin_response()` | State = READY | cpin_state, sim_ready |
| Cek NIK | `*888*4444*1#` | `_extract_nik()` | NIK = 16 digits | nik |
| Cek KK | cache/DB/Telegram | `_extract_kk()` | KK found | kk, source |
| Inject | `*888*89*1*{NIK}*{KK}#` | `classify_injection_response()` | Provisional success | injected, provisional |
| Verify | `*185#` | `_extract_grace_date()` + `_classify_card_status()` | Grace date changed | grace_date_after, card_status |
| Restart | `ATZ` | `check_modem()` | Modem online | restart_sent, modem_online |
| Reset | Serial close/open + `AT+CPIN?` | `parse_cpin_response()` | READY | modem_online, cpin_state, ready |
| Cek Limit | configurable USSD | `_extract_pulsa()` | Pulsa found | pulsa |

**Files affected**:
- `SAIKI/worker/commands/registry.py` (NEW)
- `SAIKI/worker/commands/__init__.py` (NEW)

**Risk**: MEDIUM — new module
**Rollback**: Remove registry, keep current routing

### 3.2 Refactor Skills to Use Registry

Refactor semua skills untuk menggunakan Command Registry.

**Before**: Each skill has hardcoded USSD code + parser
**After**: Skills get command definition from registry

**Files affected**:
- All 8 skill files
- `SAIKI/worker/skills/dependency_resolver.py` — resolve command from registry

**Risk**: MEDIUM — refactor all skills
**Rollback**: Revert to hardcoded commands

### 3.3 Deduplicate Parsers

Remove duplicate parsers:
- `parse_cpin_response` — keep only in `app.domain.classifier`
- Grace date extraction — keep only in `SAIKI/worker/ussd/classification.py`
- Card status classification — keep only in `SAIKI/worker/ussd/classification.py`

**Files affected**:
- `SAIKI/worker/skills/cek_status.py` — use shared parser
- `SAIKI/worker/skills/reset_hardware.py` — use shared parser
- `SAIKI/worker/skills/verify_grace.py` — use shared classifier

**Risk**: LOW — remove code
**Rollback**: Keep duplicate parsers

### 3.4 Add CekLimitSkill

Create new skill for pulsa/quota check.

**USSD Code**: Configurable (user sets via settings)
**Parser**: Extract pulsa amount from response
**Output**: `{"pulsa": str, "raw_response": str}`

**Files affected**:
- `SAIKI/worker/skills/cek_limit.py` (NEW)
- `SAIKI/worker/skills/base.py` — no change
- `SAIKI/workflow/definitions.py` — add `check_limit` workflow
- `SAIKI/workflow/registry.py` — register new workflow
- `SAIKI/worker/ui/controller.py` — update routing

**Risk**: LOW — new skill, new workflow
**Rollback**: Remove skill, keep old routing

### 3.5 Update COMMAND_ROUTES

Update routing to use new command registry.

**Files affected**:
- `SAIKI/worker/ui/controller.py` — update COMMAND_ROUTES + PER_PORT_COMMAND_MAP

**Risk**: LOW — table update
**Rollback**: Revert to old routing

### 3.6 Update Skill Factories

Update 7 factory classes in `system_bootstrap.py` to use new command definitions (reset_hardware removed).

**Files affected**:
- `SAIKI/worker/system_bootstrap.py` — update `_wire_skills_for_worker()`

**Risk**: LOW — factory update
**Rollback**: Revert to old factories

---

## Risk Summary

| Phase | Risk Level | Reason |
|-------|------------|--------|
| Phase 1 | LOW-MEDIUM | Fix bugs, add parsers |
| Phase 2 | MEDIUM | Port new modules from GOOD |
| Phase 3 | MEDIUM | Refactor + new features |

## Rollback Strategy

Every phase has individual rollback per task. If a phase fails:
1. Revert all changes in the phase
2. Keep previous phase's changes
3. Re-assess before retry

## Testing Strategy

After each phase:
1. Run `python -m unittest discover` (280+ tests)
2. Manual test with real modem (if available)
3. Verify all 8 skills return correct data
4. Verify all 9 workflows complete successfully
5. Verify UI columns update correctly (NOMOR/NIK/KK/MASA AKTIF/RESPON)
