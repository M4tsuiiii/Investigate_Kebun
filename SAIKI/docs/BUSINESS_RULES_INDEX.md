# Business Rules Index

## Reference Documents

| Document | Location | Purpose |
|----------|----------|---------|
| **BLUEPRINT_REBUILD_V2.md** | `GOOD/docs/BLUEPRINT_REBUILD_V2.md` | Architecture design, layer structure, component specs |
| **AUDIT_REPORT.md** | `GOOD/docs/AUDIT_REPORT.md` | Findings from rebuild audit: missing rules, bugs, dead code |
| **HUNTER-RE-05--BUSINESS_RULE_EXTRACTION.md** | `GOOD/docs/HUNTER-RE-05--BUSINESS_RULE_EXTRACTION.md` | All business rules extracted from monolith |
| **Original Monolith** | `GOOD/app/kebun_reaktivasi(rev).py` | Ground truth reference (2907 lines) |

---

## Business Rules (BR-001 through BR-029)

| Rule | Description | Source | Status |
|------|-------------|--------|--------|
| **BR-001** | Skip injection for AKTIF/TENGGANG card | monolith:1835 | ✅ Implemented |
| **BR-002** | Only HANGUS cards proceed to reactivation | monolith:1850 | ✅ Implemented |
| **BR-003** | NIK required for reactivation (cache → USSD) | monolith:1851-1889 | ✅ Implemented |
| **BR-004** | KK required (NIK&NIK → DB → Telegram) | monolith:1893-1911 | ⚠️ Partial (resolve_kk_source broken) |
| **BR-005** | Injection only for HANGUS, lock max 2 | monolith:1916-1920 | ✅ Implemented |
| **BR-006** | Provisional injection success criteria | monolith:1922-1949 | ✅ Implemented |
| **BR-007** | Mandatory verification (15s → *185#) | monolith:1577-1587 | ✅ Implemented |
| **BR-008** | Business outcome evaluation (single source) | monolith:844-860 | ✅ Implemented |
| **BR-009** | Grace date change detection | monolith:830-841 | ✅ Implemented |
| **BR-010** | Card status classification (7-tier) | monolith:801-827 | ✅ Implemented |
| **BR-011** | Auto-run on insert gating | monolith:218-224 | ⚠️ 4 copies (consolidation needed) |
| **BR-012** | Card cycle requirement | monolith:1847,2010 | ⚠️ Partial (not called in full_flow) |
| **BR-013** | SIM removal confirmation flow | monolith:1352 | ✅ Implemented |
| **BR-014** | USSD classification (9-tier priority) | monolith:679-715 | ✅ Implemented |
| **BR-015** | USSD intent classification | monolith:738-761 | ✅ Implemented |
| **BR-016** | USSD payload completeness check | monolith:764-774 | ⚠️ Partial (keyword subset) |
| **BR-017** | USSD grace read for empty payload | monolith:1503 | ✅ Implemented |
| **BR-018** | USSD session fence (AT+CUSD=2) | monolith:1198-1227 | ✅ Implemented |
| **BR-019** | DIAL cooldown (4s minimum) | monolith:1484-1487 | ✅ Implemented |
| **BR-020** | SUCCESS business outcome | monolith:854-855 | ✅ Implemented |
| **BR-021** | TENGGANG business outcome | monolith:857-858 | ✅ Implemented |
| **BR-022** | FAILED business outcome | monolith:860 | ✅ Implemented |
| **BR-024** | NIK/KK validation (16-digit) | monolith:337,348 | ✅ Implemented |
| **BR-025** | NIK&NIK mode KK=NIK | monolith:1893 | ✅ Implemented |
| **BR-026** | Prompt recovery retry (max 2) | monolith:1601-1620 | ✅ Implemented |
| **BR-027** | Status update guard (registry) | monolith:149-164 | ⚠️ Not wired to controller |
| **BR-028** | UI status tags (color mapping) | monolith:2622-2637 | ✅ Implemented |
| **BR-029** | UI update thread safety | monolith:2639-2644 | ✅ Implemented |

---

## Hidden Rules (HR-001 through HR-021)

| Rule | Description | Source | Status |
|------|-------------|--------|--------|
| **HR-001** | Implicit priority queue in run loop | monolith:1311-1330 | ✅ Implemented |
| **HR-002** | Force retry cleared before guard check | monolith:1324 | ✅ Implemented |
| **HR-003** | Single action vs force retry race | monolith:1324-1325 | ✅ Handled |
| **HR-004** | Awaiting card cycle stuck true | monolith:2010,233,236 | ✅ Handled |
| **HR-005/008** | Prompt recovery clears auto-run | monolith:1614 | ✅ Implemented |
| **HR-006** | Force retry pending on disabled ports | monolith:2815 | ✅ Implemented |
| **HR-007** | Force retry not retried for non-READY | monolith:1324-1326 | ✅ Implemented |
| **HR-009** | CPIN_MAX_REMOVAL_CONFIRM not enforced | monolith:46 | ⚠️ Partial |
| **HR-010** | Reset clears flags + queues auto-run | monolith:1068-1071,1107 | ✅ Implemented |
| **HR-011** | 13+ magic wait values | monolith:various | ✅ Named constants |
| **HR-012/021** | Telegram gateway is mock | monolith:893-1001 | ✅ Acknowledged |
| **HR-013** | Format mode NIK&NIK uses NIK as KK | monolith:1893 | ✅ Implemented |
| **HR-014** | Grace date parsing 2 formats | monolith:787-793 | ⚠️ Partial (4 vs 2) |
| **HR-015** | Power injection lock max 2 | monolith:53,1916 | ⚠️ Not wired |
| **HR-016** | Status guard priority | monolith:149-164 | ✅ Implemented |
| **HR-017** | CHECKING overlay stuck fix | monolith:1455-1459 | ✅ Implemented |
| **HR-018** | CHECKING threshold (2) | monolith:1465 | ✅ Implemented |
| **HR-019** | Two CPIN failure counters | monolith:various | ✅ Implemented |
| **HR-020** | NIK/KK validation only at cache write | monolith:337,348 | ✅ Implemented |

---

## Failure Codes

| Code | Trigger | Source |
|------|---------|--------|
| `GAGAL_CEK_NIK` | NIK not found | monolith:1872,1881 |
| `GAGAL_KK` | KK not found | monolith:1909 |
| `GAGAL_INJEKSI` | Injection failure | monolith:1961 |
| `GAGAL_VERIFIKASI` | Verification failure | monolith:1972,1985,2032 |
| `GAGAL` | Generic failure | monolith:various |

---

## Timing Constants

| Constant | Value | Source |
|----------|-------|--------|
| `DIAL_COOLDOWN_SECONDS` | 4.0 | monolith:35 |
| `USSD_SESSION_FENCE_MIN_SECONDS` | 0.75 | monolith:40 |
| `USSD_SESSION_FENCE_QUIET_SECONDS` | 0.25 | monolith:41 |
| `USSD_SESSION_FENCE_TIMEOUT_SECONDS` | 3.0 | monolith:42 |
| `CPIN_UNKNOWN_THRESHOLD` | 3 | monolith:44 |
| `PROMPT_RECOVERY_MAX` | 2 | monolith:48 |
| `VERIFICATION_DELAY_SECONDS` | 15.0 | monolith:50 |
| `VERIFICATION_READ_TIMEOUT` | 30.0 | monolith:51 |
| `STABILIZATION_SECONDS` | 15.0 | monolith:1783 |
| `BAUD_RATES` | [9600, 19200, 115200] | monolith:33 |
