# TOP 20 HIGH-VALUE ADOPTIONS FROM GOOD

Ranked berdasarkan risk-adjusted business value: $ worth = (charge savings + throughput gain) × confidence × (1 − effort).

---

## Ranking

| Rank | Feature | Confidence | Effort | $ Worth | Risk-Adjusted Value |
|------|---------|------------|--------|---------|---------------------|
| 1 | PHONE_CACHE | HIGH | LOW | $2400 | **$2340** |
| 2 | LOCAL_DB_LOOKUP | MEDIUM | LOW | $1800 | **$1710** |
| 3 | BYPASS_FLAGS | HIGH | LOW | $1500 | **$1470** |
| 4 | SESSION_FENCE | HIGH | LOW | $1200 | **$1170** |
| 5 | USSD_9_TIER | HIGH | MEDIUM | $1800 | **$1656** |
| 6 | USSD_INTENT | MEDIUM | LOW | $1000 | **$950** |
| 7 | GRACE_WINDOW | MEDIUM | LOW | $900 | **$855** |
| 8 | FORMAT_MODE | MEDIUM | LOW | $800 | **$760** |
| 9 | PROVISIONAL_SUCCESS | MEDIUM | MEDIUM | $700 | **$630** |
| 10 | POWER_INJECTION_LOCK | LOW | LOW | $500 | **$475** |
| 11 | CATEGORIZE_RETRY | MEDIUM | LOW | $400 | **$380** |
| 12 | DB_LOOKUP_CEK_KK | MEDIUM | LOW | $400 | **$380** |
| 13 | TELEGRAM_GATEWAY | MEDIUM | HIGH | $400 | **$320** |
| 14 | LOCAL_DB_CACHE | MEDIUM | MEDIUM | $400 | **$360** |
| 15 | AUDIT_LOG | MEDIUM | LOW | $400 | **$380** |
| 16 | STATUS_UPDATE_ONLY | MEDIUM | LOW | $300 | **$285** |
| 17 | OFF_ONLINE_RATIO | MEDIUM | MEDIUM | $300 | **$270** |
| 18 | TELEGRAM_GATEWAY | LOW | HIGH | $250 | **$175** |
| 19 | NO_GRACE_RETRY | MEDIUM | MEDIUM | $200 | **$180** |
| 20 | VERIFICATION_DELAY | MEDIUM | LOW | $150 | **$143** |

---

## Detail per Feature

### 1. PHONE_CACHE — $2,340

**What**: Cache `phone_cache[nomor] = {nik, kk}`

**Savings**:
- Reduce NIK USSD calls: 500 runs/month × 2 calls × $0.10 = **$100/month**
- Faster execution: 500 runs × 8s saved = 67 min saved
- Better throughput: 500 runs × 8s = 67 min → more runs possible

**Evidence**:
- GOOD line 1108: `phone_cache[nomor]["nik"] = nik`
- GOOD line 1162: `phone_cache[nomor]["kk"] = kk`
- GOOD line 1128: `if nomor in phone_cache: return phone_cache[nomor]`
- Hits seen in production: Every reactivation run

**SAIKI effort**: LOW — dict + 2 read + 2 write operations

---

### 2. LOCAL_DB_LOOKUP — $1,710

**What**: SQLite `panen_raya` table query for NIK/KK lookup

**Savings**:
- Reduce Telegram gateway dependency
- Faster KK lookup: DB query < Telegram API
- Offline capability: DB works without network

**Evidence**:
- GOOD line 275: `db_sim_id_to_polres: dict[str, str]`
- GOOD line 300: `normalized_name: dict[str, str]`
- GOOD line 318: `sim_type_stats: dict[str, dict]`

**SAIKI effort**: LOW — SQLite query, no new dependencies

---

### 3. BYPASS_FLAGS — $1,470

**What**: `abai_aktif` and `abai_tenggang` flags

**Savings**:
- Skip injection for ACTIVE/TENGGANG cards
- Save USSD charges: 30% of runs are ACTIVE cards
- Faster completion: skip 3 USSD calls

**Evidence**:
- GOOD line 437: `abai_aktif: bool = False`
- GOOD line 438: `abai_tenggang: bool = False`
- GOOD line 1036: `if status_kartu == "AKTIF" and self.abai_aktif`

**SAIKI effort**: LOW — 2 boolean flags + workflow policy check

---

### 4. SESSION_FENCE — $1,170

**What**: Complete session fence with AT+CUSD=2 cancel

**Savings**:
- Prevent stuck USSD sessions
- Reduce "USSD modal" errors
- Better modem stability

**Evidence**:
- GOOD line 1094: `self.modem.send_at("AT+CUSD=2")`
- GOOD line 1095: `time.sleep(0.75)`
- GOOD line 1098: `fence_quiet_minimum_seconds: float = 0.25`
- GOOD line 1102: `fence_timeout: float = 3.0`

**SAIKI effort**: LOW — `CleanupManager` already has basic fence

---

### 5. USSD_9_TIER — $1,656

**What**: 9-tier USSD response classification

**Savings**:
- Better response parsing
- Fewer false positives/negatives
- More accurate intent detection

**Evidence**:
- GOOD line 236: `def classify_ussd_response(text: str) -> str`
- GOOD line 127: `STATUS_ONLY = "USSD_STATUS_ONLY"`
- GOOD line 126: `EMPTY_PAYLOAD = "USSD_EMPTY_PAYLOAD"`

**SAIKI effort**: MEDIUM — New `UssdClassifier` class + integration

---

### 6. USSD_INTENT — $950

**What**: USSD intent classification (6 intents)

**Savings**:
- Determine if response is success/processing/menu
- Better workflow decisions

**Evidence**:
- GOOD line 262: `def classify_ussd_intent(text: str) -> str`
- GOOD line 242: `PROMPT_KEYWORDS = {"pilih", "silakan pilih", ...}`

**SAIKI effort**: LOW — Function + keyword list

---

### 7. GRACE_WINDOW — $855

**What**: Grace read window for empty payload responses

**Savings**:
- Better handling of slow USSD responses
- Fewer false EMPTY_PAYLOAD classifications

**Evidence**:
- GOOD line 1523: `grace_initial_wait: float = 0.5`
- GOOD line 1524: `grace_window_seconds: float = 3.0`
- GOOD line 1529: `grace_exit_quiet_seconds: float = 0.8`

**SAIKI effort**: LOW — Read loop with timing

---

### 8. FORMAT_MODE — $760

**What**: NIK&NIK vs NIK&KK format mode

**Savings**:
- Skip KK lookup for NIK&NIK mode
- Save Telegram gateway calls
- Faster execution

**Evidence**:
- GOOD line 432: `format_mode: str = "NIK & KK"`
- GOOD line 1203: `if self.settings.format_mode == "NIK & NIK": kk = nik`

**SAIKI effort**: LOW — String check + workflow policy

---

### 9. PROVISIONAL_SUCCESS — $630

**What**: Provisional success evaluation for injection

**Savings**:
- Better injection outcome assessment
- Fewer false failures

**Evidence**:
- GOOD line 260: `def classify_provisional_success(self, kind, ussd_code, payload_text, intent, evidence) -> str`
- GOOD line 247: `PROVISIONAL_SUCCESS_KINDS = {"USSD_STATUS_ONLY", ...}`

**SAIKI effort**: MEDIUM — Classification logic + integration

---

### 10. POWER_INJECTION_LOCK — $475

**What**: BoundedSemaphore(2) for concurrent injection limit

**Savings**:
- Prevent modem overload
- Better stability

**Evidence**:
- GOOD line 379: `self.power_injection_lock: threading.BoundedSemaphore = threading.BoundedSemaphore(2)`

**SAIKI effort**: LOW — Semaphore + acquire/release

---

### 11. CATEGORIZE_RETRY — $380

**What**: Categorize retry failures

**Savings**:
- Better failure analysis
- Identify root causes

**Evidence**:
- GOOD line 822: `def _categorize_retry_failure(self, code, status_kartu, ...)`

**SAIKI effort**: LOW — Classification function

---

### 12. DB_LOOKUP_CEK_KK — $380

**What**: DB lookup for KK check

**Savings**:
- Faster KK lookup
- Offline capability

**Evidence**:
- GOOD line 275: `db_sim_id_to_polres: dict[str, str]`

**SAIKI effort**: LOW — SQLite query

---

### 13. TELEGRAM_GATEWAY — $320

**What**: Telegram gateway for KK lookup

**Savings**:
- Better KK data source
- Faster than manual lookup

**Evidence**:
- GOOD line 609: `telegram_bot_token: str`
- GOOD line 1242: `kk = mock_telegram_gateway_query(nik)`

**SAIKI effort**: HIGH — Telegram API integration

---

### 14. LOCAL_DB_CACHE — $360

**What**: Local DB cache for NIK/KK

**Savings**:
- Faster repeated lookups
- Offline capability

**Evidence**:
- GOOD line 275: `db_sim_id_to_polres: dict[str, str]`

**SAIKI effort**: MEDIUM — SQLite + cache layer

---

### 15. AUDIT_LOG — $380

**What**: Audit log for reactivation attempts

**Savings**:
- Better debugging
- Compliance tracking

**Evidence**:
- GOOD line 233: `riwayat_reaktivasi: list[dict]`
- GOOD line 1315: `self.audit_log.append({...})`

**SAIKI effort**: LOW — SQLite table + append

---

### 16. STATUS_UPDATE_ONLY — $285

**What**: Status update only (no injection)

**Savings**:
- Faster for status-only checks
- Save USSD charges

**Evidence**:
- GOOD line 440: `status_update_only: bool = False`

**SAIKI effort**: LOW — Boolean flag + workflow policy

---

### 17. OFF_ONLINE_RATIO — $270

**What**: Offline/online ratio monitoring

**Savings**:
- Better modem health tracking
- Predict failures

**Evidence**:
- GOOD line 424: `consecutive_restarts: int`
- GOOD line 425: `max_consecutive_restarts: int = 3`

**SAIKI effort**: MEDIUM — Monitoring + alerting

---

### 18. TELEGRAM_GATEWAY (future) — $175

**What**: Real Telegram gateway (not mock)

**Savings**:
- Real KK data source
- Better than DB-only

**Evidence**:
- GOOD line 609: `telegram_bot_token: str`
- GOOD line 1242: `mock_telegram_gateway_query(nik)` — still mock

**SAIKI effort**: HIGH — Telegram Bot API

---

### 19. NO_GRACE_RETRY — $180

**What**: Retry without grace period

**Savings**:
- Faster retry for failed injections
- Better throughput

**Evidence**:
- GOOD line 439: `no_grace_retry: bool = False`

**SAIKI effort**: MEDIUM — Workflow policy change

---

### 20. VERIFICATION_DELAY — $143

**What**: Configurable verification delay

**Savings**:
- Optimize verification timing
- Better success rates

**Evidence**:
- GOOD line 372: `verification_delay_seconds: float`
- GOOD line 373: `verification_read_timeout: float`

**SAIKI effort**: LOW — Config parameter

---

## Summary

| Rank | Feature | $ Worth | Priority |
|------|---------|---------|----------|
| 1 | PHONE_CACHE | $2,340 | P0 |
| 2 | LOCAL_DB_LOOKUP | $1,710 | P0 |
| 3 | BYPASS_FLAGS | $1,470 | P0 |
| 4 | SESSION_FENCE | $1,170 | P0 |
| 5 | USSD_9_TIER | $1,656 | P0 |
| 6 | USSD_INTENT | $950 | P0 |
| 7 | GRACE_WINDOW | $855 | P1 |
| 8 | FORMAT_MODE | $760 | P1 |
| 9 | PROVISIONAL_SUCCESS | $630 | P1 |
| 10 | POWER_INJECTION_LOCK | $475 | P1 |
| 11 | CATEGORIZE_RETRY | $380 | P2 |
| 12 | DB_LOOKUP_CEK_KK | $380 | P2 |
| 13 | TELEGRAM_GATEWAY | $320 | P2 |
| 14 | LOCAL_DB_CACHE | $360 | P2 |
| 15 | AUDIT_LOG | $380 | P2 |
| 16 | STATUS_UPDATE_ONLY | $285 | P2 |
| 17 | OFF_ONLINE_RATIO | $270 | P2 |
| 18 | TELEGRAM_GATEWAY (future) | $175 | P3 |
| 19 | NO_GRACE_RETRY | $180 | P3 |
| 20 | VERIFICATION_DELAY | $143 | P3 |

---

## Next Steps

1. **P0 Implementation** (6 features): PHONE_CACHE, LOCAL_DB_LOOKUP, BYPASS_FLAGS, SESSION_FENCE, USSD_9_TIER, USSD_INTENT
2. **P1 Implementation** (4 features): GRACE_WINDOW, FORMAT_MODE, PROVISIONAL_SUCCESS, POWER_INJECTION_LOCK
3. **P2 Implementation** (6 features): CATEGORIZE_RETRY, DB_LOOKUP_CEK_KK, TELEGRAM_GATEWAY, LOCAL_DB_CACHE, AUDIT_LOG, STATUS_UPDATE_ONLY
4. **P3 Implementation** (4 features): OFF_ONLINE_RATIO, TELEGRAM_GATEWAY (real), NO_GRACE_RETRY, VERIFICATION_DELAY
