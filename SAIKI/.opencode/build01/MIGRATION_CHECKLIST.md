# MIGRATION CHECKLIST

Step-by-step checklist untuk implementasi BUILD_01.

---

## Phase 1: Fix Critical Bugs

### 1.1 Fix CekNikSkill — WRONG USSD CODE

- [ ] Read `SAIKI/worker/skills/cek_nik.py`
- [ ] Change USSD code from `*185#` to `*888*4444*1#`
- [ ] Add `_extract_nik(raw)` parser function
- [ ] Add regex `r'(\d{16})'` for NIK extraction
- [ ] Add validation `re.fullmatch(r"\d{16}", nik)`
- [ ] Update `SkillResult.data` to include `{"nik": nik}`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: NIK extraction works with sample response

### 1.2 Fix CekKkSkill — NOT USSD-BASED

- [ ] Read `SAIKI/worker/skills/cek_kk.py`
- [ ] Rewrite to use cache → DB → Telegram logic
- [ ] Add phone cache check: `phone_cache.get(nomor)`
- [ ] Add local DB check: query `panen_raya` table
- [ ] Add NIK&NIK mode check: `if format_mode == "NIK & NIK", kk = nik`
- [ ] Add Telegram lookup: query bot
- [ ] Add `_extract_kk(raw)` parser function
- [ ] Update `SkillResult.data` to include `{"kk": kk, "source": source}`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: KK lookup works with all sources

### 1.3 Fix CekNomorSkill — MISSING GRACE DATE EXTRACTION

- [ ] Read `SAIKI/worker/skills/cek_nomor.py`
- [ ] Add `_extract_grace_date(raw)` parser function
- [ ] Add regex `r'Active\s+(\d{2}-\d{2}-\d{4})'` for grace date
- [ ] Add `_classify_card_status(grace_date)` parser function
- [ ] Add logic: `grace_date - today = masa aktif` → calculate status:
  - [ ] `masa aktif > 0` → `"AKTIF"`
  - [ ] `-30 ≤ masa aktif ≤ 0` → `"TENGGANG"`
  - [ ] `masa aktif < -30` → `"HANGUS"`
  - [ ] NOTE: Kata "Active" di response BUKAN status kartu. Status diHITUNG dari grace_date.
- [ ] Update `SkillResult.data` to include `{"grace_date": grace_date, "card_status": card_status}`
- [ ] Update `SAIKI/automation/engine.py`:
  - [ ] Add `"grace_date": "masa_aktif"` to `_SKILL_RESULT_TO_STATE`
  - [ ] Add `"card_status"` to `_SKILL_RESULT_TO_RESPON`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Grace date extraction works with sample response
- [ ] Verify: Card status calculated correctly from grace_date - today

### 1.4 Fix InjectReaktivasiSkill — ADD PARSER

- [ ] Read `SAIKI/worker/skills/inject_reaktivasi.py`
- [ ] Add `classify_injection_response(raw)` parser function
- [ ] Add keyword matching:
  - [ ] `"Permintaan kamu sedang di proses"` → HANGUS
  - [ ] `"sedang dalam masa tenggang"` → TENGGANG
  - [ ] `"Layanan Hanya Dapat Dilakukan"` → AKTIF
- [ ] Add `_evaluate_provisional(raw)` parser function
- [ ] Add provisional evaluation logic
- [ ] Update `SkillResult.data` to include `{"injected": injected, "provisional": provisional, "card_status": card_status}`
- [ ] Update `SAIKI/automation/engine.py`:
  - [ ] Add `"provisional"` to `_SKILL_RESULT_TO_RESPON`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Injection response classification works

### 1.5 Fix VerifyGraceSkill — ADD BEFORE/AFTER COMPARISON

- [ ] Read `SAIKI/worker/skills/verify_grace.py`
- [ ] Add `has_grace_date_changed(before, after)` parser function
- [ ] Add date comparison logic
- [ ] Add `evaluate_business_outcome(before, after, inject_response)` parser function
- [ ] Add outcome logic: SUCCESS/TENGGANG/FAILED
- [ ] Update `SkillResult.data` to include `{"success": success, "outcome": outcome, "grace_date_before": before}`
- [ ] Update `SAIKI/workflow/context.py`:
  - [ ] Ensure `grace_date` field available in context
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Before/after comparison works

### 1.6 Fix COMMAND_ROUTES — Cek Limit

- [ ] Create `SAIKI/worker/skills/cek_limit.py`
- [ ] Add `_extract_pulsa(raw)` parser function
- [ ] Add regex `r'Rp[\s.]?(\d[\d.,]*)'` for pulsa extraction
- [ ] Update `SkillResult.data` to include `{"pulsa": pulsa}`
- [ ] Update `SAIKI/workflow/definitions.py`:
  - [ ] Add `check_limit` workflow definition
- [ ] Update `SAIKI/workflow/registry.py`:
  - [ ] Register `check_limit` workflow
- [ ] Update `SAIKI/worker/ui/controller.py`:
  - [ ] Update `cmd.cek_limit` routing to `check_limit`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Cek Limit works with configurable USSD code

### 1.7 Consolidate Hardware Features — REMOVE Reset, Keep Restart Only

- [ ] Verify RestartHardwareSkill uses `ATZ` (soft reset)
- [ ] Verify restart has 2 types: tunggal (per port) + massal (all ports)
- [ ] After restart: worker rescan modem, re-detect SIM
- [ ] NO auto run after restart (user must trigger manually)
- [ ] Remove `hardware_reset` workflow from `SAIKI/workflow/definitions.py`
- [ ] Remove `hardware_reset` registration from `SAIKI/workflow/registry.py`
- [ ] Remove `cmd.reset_modem` routing from `SAIKI/worker/ui/controller.py`
- [ ] Delete or keep as dead code: `SAIKI/worker/skills/reset_hardware.py`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Only restart feature works, no reset feature

---

## Phase 2: Port MISSING Parsers

### 2.1 USSD Classification Engine

- [ ] Create `SAIKI/worker/ussd/__init__.py`
- [ ] Create `SAIKI/worker/ussd/classification.py`
- [ ] Port `classify_ussd_response()` from GOOD
- [ ] Implement 11-tier classification:
  - [ ] `USSD_PAYLOAD`
  - [ ] `USSD_EMPTY_PAYLOAD`
  - [ ] `USSD_STATUS_ONLY`
  - [ ] `PARTIAL_RESPONSE`
  - [ ] `PROMPT_CONFIRMATION`
  - [ ] `ERROR`
  - [ ] `AT_OK`
  - [ ] `COMMAND_ECHO`
  - [ ] `MODEM_NOTIFICATION`
  - [ ] `WAITING_RESPONSE`
  - [ ] `TIMEOUT`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Classification works with sample responses

### 2.2 USSD Intent Classification

- [ ] Port `classify_ussd_intent()` from GOOD
- [ ] Implement 6 intents:
  - [ ] `EMPTY_RESPONSE`
  - [ ] `NUMBER_INFO`
  - [ ] `SUCCESS_MESSAGE`
  - [ ] `REQUEST_ACCEPTED`
  - [ ] `MENU_RESPONSE`
  - [ ] `UNKNOWN`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Intent classification works

### 2.3 Evidence Classification

- [ ] Port `classify_ussd_evidence()` from GOOD
- [ ] Implement 3 evidence flags:
  - [ ] `has_success_evidence`
  - [ ] `has_processing_evidence`
  - [ ] `has_tenggang_evidence`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Evidence classification works

### 2.4 NIK Extraction Parser

- [ ] Port NIK extraction from GOOD
- [ ] Add regex `r'(\d{16})'`
- [ ] Add validation `re.fullmatch(r"\d{16}", nik)`
- [ ] Integrate with CekNikSkill
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: NIK extraction works

### 2.5 Grace Date Extraction from `*185#`

- [ ] Port grace date extraction from GOOD
- [ ] Add Stage 1: ISO format `r'(\d{4}[-/]\d{2}[-/]\d{2})'`
- [ ] Add Stage 2: Local format `r'(\d{2}[-/]\d{2}[-/]\d{4})'`
- [ ] Add normalization: reverse to YYYY-MM-DD
- [ ] Integrate with CekNomorSkill
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Grace date extraction works

### 2.6 Card Status Classification (Enhanced)

- [ ] Port enhanced card status classification from GOOD
- [ ] Implement 7-tier priority:
  - [ ] `has_tenggang_evidence` → `TENGGANG`
  - [ ] `hangus` keywords → `HANGUS`
  - [ ] `aktif` keywords → `AKTIF`
  - [ ] `days_remaining is None` → `UNKNOWN`
  - [ ] `days_remaining > 0` → `AKTIF`
  - [ ] `-30 <= days_remaining <= 0` → `TENGGANG`
  - [ ] `days_remaining < -30` → `HANGUS`
- [ ] Integrate with VerifyGraceSkill
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Card status classification works

### 2.7 Provisional Success Evaluation

- [ ] Port provisional success evaluation from GOOD
- [ ] Implement evaluation logic:
  - [ ] `USSD_STATUS_ONLY:0` → `PROVISIONAL_SUCCESS`
  - [ ] `USSD_EMPTY_PAYLOAD` → `PROVISIONAL_WAITING`
  - [ ] `PROMPT_CONFIRMATION` → `FAILURE`
  - [ ] `COMMAND_ECHO` → `PROVISIONAL_SUCCESS`
  - [ ] `USSD_PAYLOAD` + `SUCCESS_MESSAGE` → `PROVISIONAL_SUCCESS`
  - [ ] `USSD_PAYLOAD` + `REQUEST_ACCEPTED` → `PROVISIONAL_SUCCESS`
  - [ ] `ERROR` → `FAILURE`
  - [ ] Others → `PROVISIONAL_WAITING`
- [ ] Integrate with InjectReaktivasiSkill
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Provisional success evaluation works

### 2.8 Business Outcome Evaluation

- [ ] Port business outcome evaluation from GOOD
- [ ] Implement evaluation logic:
  - [ ] `grace_changed = has_grace_date_changed(before, after)`
  - [ ] `evidence = classify_ussd_evidence(inject_response)`
  - [ ] IF `grace_changed` AND `after_status NOT IN {"", "HANGUS", "UNKNOWN"}` → `SUCCESS`
  - [ ] IF NOT `grace_changed` AND `evidence.has_tenggang_evidence` → `TENGGANG`
  - [ ] ELSE → `FAILED`
- [ ] Integrate with VerifyGraceSkill
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Business outcome evaluation works

---

## Phase 3: Command Registry + Cleanup

### 3.1 Create Command Registry

- [ ] Create `SAIKI/worker/commands/__init__.py`
- [ ] Create `SAIKI/worker/commands/registry.py`
- [ ] Define `CommandDefinition` dataclass
- [ ] Define `COMMAND_REGISTRY` dict with 9 entries
- [ ] Implement `get_command(name)` API
- [ ] Implement `get_ussd_code(name)` API
- [ ] Implement `get_at_command(name)` API
- [ ] Implement `get_parser(name)` API
- [ ] Implement `get_output_fields(name)` API
- [ ] Write tests for registry API
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Registry works correctly

### 3.2 Refactor Skills to Use Registry

- [ ] Update CekNomorSkill to use registry
- [ ] Update CekStatusSkill to use registry
- [ ] Update CekNikSkill to use registry
- [ ] Update CekKkSkill to use registry
- [ ] Update InjectReaktivasiSkill to use registry
- [ ] Update VerifyGraceSkill to use registry
- [ ] Update CekLimitSkill to use registry
- [ ] Update RestartHardwareSkill to use registry
- [ ] Update ResetHardwareSkill to use registry
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: All skills use registry correctly

### 3.3 Deduplicate Parsers

- [ ] Remove duplicate `parse_cpin_response` from skills
- [ ] Keep only in `app.domain.classifier`
- [ ] Remove duplicate grace date extraction from skills
- [ ] Keep only in `SAIKI/worker/ussd/classification.py`
- [ ] Remove duplicate card status classification from skills
- [ ] Keep only in `SAIKI/worker/ussd/classification.py`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: No duplicate parsers

### 3.4 Add CekLimitSkill

- [ ] Create `SAIKI/worker/skills/cek_limit.py`
- [ ] Add configurable USSD code
- [ ] Add `_extract_pulsa(raw)` parser
- [ ] Add regex `r'Rp[\s.]?(\d[\d.,]*)'` for pulsa extraction
- [ ] Update `SkillResult.data` to include `{"pulsa": pulsa}`
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: CekLimitSkill works

### 3.5 Update COMMAND_ROUTES

- [ ] Update `SAIKI/worker/ui/controller.py`
- [ ] Update `COMMAND_ROUTES` table
- [ ] Update `PER_PORT_COMMAND_MAP` dict
- [ ] Update eligibility checks
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Routing works correctly

### 3.6 Update Skill Factories

- [ ] Update `SAIKI/worker/system_bootstrap.py`
- [ ] Update `_wire_skills_for_worker()` function
- [ ] Update 8 factory classes
- [ ] Run tests: `python -m unittest discover`
- [ ] Verify: Factories work correctly

---

## Final Verification

### Unit Tests

- [ ] Run `python -m unittest discover` — all tests pass
- [ ] No test regressions

### Integration Tests

- [ ] All 8 skills return correct data
- [ ] All 9 workflows complete successfully
- [ ] UI columns update correctly (NOMOR/NIK/KK/MASA AKTIF/RESPON)
- [ ] No regressions in existing functionality

### Manual Testing

- [ ] Test with real modem (if available)
- [ ] Test CekNomorSkill — verify grace date extraction
- [ ] Test CekNikSkill — verify NIK extraction with `*888*4444*1#`
- [ ] Test CekKkSkill — verify KK lookup from cache/DB/Telegram
- [ ] Test InjectReaktivasiSkill — verify response classification
- [ ] Test VerifyGraceSkill — verify before/after comparison
- [ ] Test reactivate_full workflow — verify end-to-end flow
- [ ] Verify UI shows correct data in all columns

### Documentation

- [ ] Update `SAIKI/docs/COMMAND_RESPONSE_MATRIX.md`
- [ ] Update `SAIKI/docs/SAIKI_FUTURE_BUSINESS_RULES.md`
- [ ] Update `SAIKI/docs/SKILL_CATALOG.md`
- [ ] Update `SAIKI/docs/WORKFLOW_CATALOG.md`

---

## Rollback Checklist

If any phase fails:

- [ ] Revert all changes in the phase
- [ ] Keep previous phase's changes
- [ ] Run `python -m unittest discover` — verify no regressions
- [ ] Re-assess before retry
- [ ] Document what failed and why
