# ADOPTION MATRIX — GOOD → SAIKI

Tabel keputusan adopsi untuk setiap rule, command, parser, workflow, state machine, mechanism.

**Decision Key**:
- `KEEP_SAIKI` = SAIKI sudah benar, tidak perlu ubah
- `ADOPT_FROM_GOOD` = GOOD punya sesuatu yang SAIKI belum punya
- `MERGE` = Keduanya punya versi berbeda, harus digabung
- `REJECT` = Tidak diperlukan di SAIKI

---

## 1. AT Commands

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| `AT\r\n` — Baud Detection | monolith:1287 | Test modem respons di setiap baud rate | KEEP_SAIKI | SAIKI punya `ModemDiscovery.probe()` yang lakukan hal sama |
| `ATE0\r\n` — Disable Echo | monolith:1306 | Matikan echo setelah koneksi | KEEP_SAIKI | Sudah dilakukan di `SystemBootstrap._create_at_client()` |
| `AT+CPIN?` — SIM Polling | monolith:1334 | Periodic SIM state polling | KEEP_SAIKI | `CpinRuntime._poll_loop()` sudah implementasi |
| `AT+CPIN?` — Final Confirm | monolith:1369 | Konfirmasi akhir setelah 3x UNKNOWN | MERGE | SAIKI ada di `CpinRuntime._check_confirmation_needed()`, tapi perlu validasi threshold logic |
| `AT+CPIN?` — Removal Confirm | monolith:1420 | Konfirmasi ulang saat removal flow | MERGE | SAIKI ada `CPIN_MAX_REMOVAL_CONFIRM=2` tapi path removal belum teruji |
| `ATZ` — Soft Reset | monolith:1091 | Reset modem ke default | KEEP_SAIKI | `RestartHardwareSkill` sudah implementasi |
| `AT+CFUN=1,1` — Full Restart | monolith:1095 | Restart radio penuh | ADOPT_FROM_GOOD | SAIKI hanya pakai ATZ. `AT+CFUN=1,1` lebih komprehensif untuk reset penuh |
| `AT+CUSD=1,"{cmd}",15` — USSD Send | monolith:1237 | Kirim USSD command | KEEP_SAIKI | `UssdRuntime.dial()` sudah implementasi |
| `AT+CUSD=2` — Cancel USSD | monolith:1206,1603 | Batalkan sesi USSD | MERGE | SAIKI ada di `CleanupManager.close_session()` tapi fence logic kurang lengkap |

---

## 2. USSD Codes

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| `*185#` — Cek Nomor | global_settings | Cek nomor + grace date | KEEP_SAIKI | Sudah dipakai di `CekNomorSkill` dan `VerifyGraceSkill` |
| `*888*4444*1#` — Cek NIK | global_settings | Ambil NIK dari operator | KEEP_SAIKI | Sudah dipakai di `CekNikSkill` |
| `*888*89*1*{NIK}*{KK}#` — Reaktivasi | build_reaktivasi_command() | Injection reaktivasi | KEEP_SAIKI | Sudah dipakai di `InjectReaktivasiSkill` |
| `number_ussd_code` configurable | settings_dialog | USSD code untuk cek nomor (configurable) | KEEP_SAIKI | Sudah ada di `SettingsDialog` dan `CekNomorSkill._get_ussd_code()` |

---

## 3. CPIN State Machine

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| 5 States (READY/NOT_INSERTED/PIN_REQUIRED/NOT_READY/UNKNOWN) | cpin.py | CPIN state definitions | KEEP_SAIKI | Identik |
| `NOT_READY` checked before `READY` | cpin.py:1131 | Prevent substring false positive | KEEP_SAIKI | `parse_cpin_response()` di `app/domain/classifier.py` sudah benar |
| UNKNOWN→READY: auto-run gate check | cpin.py:222 | Gate check on ready transition | KEEP_SAIKI | `CpinRuntime._apply_stabilization()` sudah implementasi |
| UNKNOWN threshold=3 → NOT_READY | cpin.py:1360 | Final confirm after 3x UNKNOWN | MERGE | SAIKI punya threshold tapi logic flow perlu divalidasi terhadap GOOD |
| CHECKING threshold=2 | cpin.py:1464 | UI CHECKING after 2x UNKNOWN | KEEP_SAIKI | `CpinRuntime` sudah implementasi |
| Removal confirmation (READY→NOT_READY) | cpin.py:1351 | Konfirmasi removal dengan retry | ADOPT_FROM_GOOD | SAIKI punya `CPIN_MAX_REMOVAL_CONFIRM` tapi flow removal belum lengkap |
| Prompt recovery | retry.py:1601 | Cancel USSD + requeue | KEEP_SAIKI | Sudah ada di `CleanupManager` dan `RetryManager` |

---

## 4. USSD Classification

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| 9-tier USSD classification | classification.py | USSD_PAYLOAD → TIMEOUT | ADOPT_FROM_GOOD | SAIKI `UssdRuntime` hanya basic classify. GOOD punya 9-tier classification yang lebih robust |
| USSD Intent classification | classification.py:738 | 6 intents: EMPTY/NUMBER/SUCCESS/ACCEPTED/MENU/UNKNOWN | ADOPT_FROM_GOOD | SAIKI belum punya intent classification |
| Prompt keywords detection | classification.py:655 | 16 keywords: confirm/konfirmasi/pilih/etc | ADOPT_FROM_GOOD | SAIKI belum deteksi prompt |
| Modem notification patterns | classification.py:676 | +WIND/+MREG/+CPIN/+CREG/+CGREG/+CIEV/+CSQ | ADOPT_FROM_GOOD | SAIKI belum filter modem notifications |
| USSD payload completeness | classification.py:764 | Check quoted payload OR CME ERROR OR prompt | ADOPT_FROM_GOOD | SAIKI belum punya completeness check |
| Evidence classification | classification.py:718 | Success/processing/tenggang evidence | ADOPT_FROM_GOOD | SAIKI belum punya evidence classification |

---

## 5. USSD Session Management

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| Session Fence (AT+CUSD=2 → flush) | session.py:1198 | Cancel stale session sebelum dial baru | ADOPT_FROM_GOOD | SAIKI `CleanupManager` ada tapi fence logic kurang lengkap (0.75s min + 0.25s quiet) |
| Dial Cooldown (4.0s) | cooldown.py | Waktu minimum antar dial | KEEP_SAIKI | Sudah ada di `UssdRuntime` via `DIAL_COOLDOWN_SECONDS` |
| Grace Read Window (0.5s → 3s) | reader.py:1503 | Baca response tambahan untuk empty payload | ADOPT_FROM_GOOD | SAIKI belum punya grace read window |
| Session state machine | session.py | IDLE→FENCING→SENDING→WAITING→READING→COMPLETE/ERROR | ADOPT_FROM_GOOD | SAIKI `UssdRuntime` lebih sederhana |

---

## 6. Card Status Classification

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| 7-priority classification | classifier.py:801 | tenggang > hangus > aktif > invalid > days calc | KEEP_SAIKI | `VerifyGraceSkill._classify_card_status()` sudah implementasi |
| Grace date extraction (2 formats) | classifier.py:784 | YYYY-MM-DD dan DD-MM-YYYY | KEEP_SAIKI | `VerifyGraceSkill._extract_grace_date()` sudah implementasi |
| Days remaining calculation | classifier.py | 4 date format support | MERGE | SAIKI support DD/MM/YYYY dan YYYY-MM-DD. GOOD juga support DD-MM-YYYY dan YYYY/MM/DD. Perlu merge format support |
| Keyword detection (tenggang/hangus/aktif) | classifier.py:817-819 | Regex patterns | KEEP_SAIKI | Sudah ada di `VerifyGraceSkill._classify_card_status()` |

---

## 7. Business Outcome

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| SUCCESS: grace_changed AND after_status not HANGUS/UNKNOWN | outcome.py:844 | Outcome SUCCESS | KEEP_SAIKI | Logic sama |
| TENGGANG: no change + tenggang evidence | outcome.py:852 | Outcome TENGGANG | ADOPT_FROM_GOOD | SAIKI belum punya tenggang evidence check di outcome |
| FAILED: all other cases | outcome.py:856 | Outcome FAILED | KEEP_SAIKI | Logic sama |
| Grace date change detection | outcome.py:830 | Compare before/after dates | KEEP_SAIKI | Logic sama |

---

## 8. Reactivation Flow

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| Full flow: stabilize→nomor→classify→NIK→KK→inject→verify→outcome | full_flow.py | 8-step reactivation | KEEP_SAIKI | `reactivate_full` workflow sudah 6 steps. SAIKI sudah handle |
| Skip injection for AKTIF/TENGGANG | full_flow.py:1835 | Bypass atau record | KEEP_SAIKI | Logic di `AutomationEngine` via scheduler/policy |
| NIK required for HANGUS | full_flow.py:1850 | NIK wajib sebelum inject | KEEP_SAIKI | Sudah ada di `CekNikSkill` |
| KK lookup: NIK&NIK mode → local DB → Telegram | full_flow.py:1893 | KK source priority | ADOPT_FROM_GOOD | SAIKI belum punya NIK&NIK mode, local DB lookup, atau Telegram fallback |
| Power injection lock (BoundedSemaphore(2)) | injection.py | Limit concurrent injections | ADOPT_FROM_GOOD | SAIKI belum punya concurrency limit per injection |
| Mandatory verification (15s delay + 30s timeout) | verification.py | Post-inject verification | KEEP_SAIKI | Sudah ada di `reactivate_full` workflow (inject→verify) |
| Provisional success evaluation | injection.py:1916 | 9 conditions → provisional success/waiting/failure | ADOPT_FROM_GOOD | SAIKI belum punya provisional success evaluation |

---

## 9. Phone Cache

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| phone_cache[nomor] = {nik, kk, ...} | monolith:1851 | Cache nomor→NIK→KK | ADOPT_FROM_GOOD | SAIKI belum punya phone cache |
| Cache hit → skip NIK lookup | monolith:1851 | Avoid redundant USSD | ADOPT_FROM_GOOD | SAIKI belum punya cache |
| Cache miss → USSD NIK | monolith:1878 | Query NIK via USSD | KEEP_SAIKI | Sudah ada di `CekNikSkill` |

---

## 10. Telegram Gateway

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| mock_telegram_gateway_query(nik) | kk_flow.py:120 | Query KK via Telegram bot | REJECT | HR-012/HR-021: mock selalu return "DATA_TIDAK_DITEMUKAN". Belum functional. Implementasi nanti setelah real Telegram gateway |

---

## 11. Database

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| `panen_raya` table (nomor, nik, kk, timestamp) | monolith | Harvest records | MERGE | SAIKI punya `cards` table. Perlu harmonisasi schema |
| `status_kartu` table (nomor, kategori, masa_aktif) | monolith | Card status records | ADOPT_FROM_GOOD | SAIKI belum punya status_kartu table |
| `riwayat_reaktivasi` table | monolith | Reactivation audit log | ADOPT_FROM_GOOD | SAIKI belum punya audit log |
| Local DB lookup sebelum USSD | kk_flow.py:1896 | Cek KK di local DB dulu | ADOPT_FROM_GOOD | SAIKI `DbLookup` ada tapi belum terkoneksi |

---

## 12. Worker Run Loop Priority

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| Priority: reset > single > force_retry > auto_run > cpin_poll | monolith:1310 | 5-level priority queue | KEEP_SAIKI | SAIKI `PortWorker` punya priority loop yang mirip |

---

## 13. Auto-Run Gating

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| trigger_mode check | monolith:222 | "Auto-Run on Insert" vs "Manual" | KEEP_SAIKI | Sudah ada di `AutoRunConfig` |
| old_state != READY check | monolith:223 | Prevent re-trigger | KEEP_SAIKI | Sudah ada di `AutomationEngine.handle_trigger()` |
| awaiting_card_cycle check | monolith:224 | Block sampai physical cycle | KEEP_SAIKI | Sudah ada di `PortWorkerState` |

---

## 14. Card Cycle

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| SET on SUCCESS/AKTIF/TENGGANG | card_cycle.py | Require physical SIM cycle | KEEP_SAIKI | `PortWorkerState.require_card_cycle()` sudah ada |
| CLEAR only on PIN_REQUIRED/NOT_INSERTED | card_cycle.py | Hanya clear saat SIM dilepas | MERGE | SAIKI ada tapi belum teruji path clear-nya |
| Blocks auto-run | card_cycle.py:224 | Auto-run gate condition | KEEP_SAIKI | Sudah ada di `AutomationEngine` |

---

## 15. Status Update Guard

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| OFF→IDLE: only if NOT_INSERTED | status_guard.py:149 | Guard status transition | KEEP_SAIKI | Logic di `CpinRuntime._apply_stabilization()` |
| READY→IDLE: only if NOT_INSERTED | status_guard.py:155 | Guard status transition | KEEP_SAIKI | Logic sama |
| CHECKING overlay stuck fix (HR-017) | status_guard.py | READY re-detected from CHECKING → re-render | ADOPT_FROM_GOOD | SAIKI belum punya explicit handling |

---

## 16. Modem Reset

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| ATZ → AT+CFUN=1,1 sequence | reset.py:1091-1095 | Two-step reset | MERGE | SAIKI `ResetHardwareSkill` pakai close/reopen serial + ATZ. Perlu tambah AT+CFUN=1,1 |
| Clear flags on reset | reset.py:1068 | HR-010: clear force_retry/single/pending | KEEP_SAIKI | `PortWorkerState.request_reset()` sudah implementasi |
| Queue auto-run after reset | reset.py:1108 | Auto-run post-reset | KEEP_SAIKI | Sudah ada |

---

## 17. Baud Detection

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| Try [9600, 19200, 115200] | monolith:1282 | Sequential baud detection | MERGE | SAIKI `ModemDiscovery.probe()` pakai [115200, 9600, 57600, 38400, 19200, 4800]. Lebih lengkap. KEEP SAIKI |
| Baud cache untuk reappearing ports | discovery.py | Simpan baud rate per port | KEEP_SAIKI | SAIKI `ModemDiscovery._baud_cache` sudah ada |

---

## 18. Error Handling

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| Modem error → current_baud=None → re-detect | monolith:1473 | Auto recovery on error | KEEP_SAIKI | `PortWorker._run_loop()` sudah handle |
| Connection error → sleep 4s → retry | monolith:1478 | Backoff on error | KEEP_SAIKI | Logic sama |

---

## 19. Configuration

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| WorkerConfig class (all constants) | config.py | Centralized constants | KEEP_SAIKI | SAIKI punya `app/domain/constants.py` |
| global_settings dict | monolith:72 | Runtime settings | KEEP_SAIKI | SAIKI punya `saiki_config.json` + `SettingsDialog` |
| SECRET_SALT | monolith:32 | License salt | KEEP_SAIKI | SAIKI belum punya license system. Adopt nanti |
| abai_aktif/abai_tenggang bypass flags | global_settings | Skip injection for active/tenggang | ADOPT_FROM_GOOD | SAIKI belum punya bypass flags |
| format_mode: NIK & KK / NIK & NIK | global_settings | KK source mode | ADOPT_FROM_GOOD | SAIKI belum punya format mode |

---

## 20. UI Status Tags

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| Color coding: sukses/done/proses/idle/off/gagal | monolith:2622 | Row color tags | KEEP_SAIKI | `PortStatusTable` sudah punya tags |
| 100ms batch coalescing for UI updates | monolith:2639 | Burst coalescing | KEEP_SAIKI | SAIKI `UpdateQueue` sudah implementasi |

---

## 21. Hidden Rules

| Item | Source File (GOOD) | Description | Adopt | Reason |
|------|-------------------|-------------|-------|--------|
| HR-001: Implicit priority queue | monolith:1310 | reset > single > force > auto > cpin | KEEP_SAIKI | Sudah diimplementasi |
| HR-002: Force retry cleared before guard | monolith:1324 | force_retry=False sebelum READY check | KEEP_SAIKI | Sudah di `PortWorkerState.consume_force_retry()` |
| HR-003: Single action vs force retry race | monolith:1318 | single_action wins | KEEP_SAIKI | Sudah di run loop |
| HR-004: awaiting_card_cycle stuck true | card_cycle.py | Set on SUCCESS, clear on PIN/NOT_INSERTED only | MERGE | SAIKI ada tapi belum teruji clear path |
| HR-005/008: Prompt recovery clears auto-run | retry.py:1601 | _recover_from_prompt() clears pending_auto_run | ADOPT_FROM_GOOD | SAIKI belum punya prompt recovery handler |
| HR-006: Force retry on disabled ports | autorun.py | restart_all sets force_retry ALL workers | KEEP_SAIKI | Sudah ada |
| HR-009: CPIN_MAX_REMOVAL_CONFIRM not enforced | retry.py | Constant exists but not checked | KEEP_SAIKI | SAIKI `CpinRuntime` sudah enforce |
| HR-010: Reset clears all flags | reset.py:1068 | request_modem_reset clears everything | KEEP_SAIKI | Sudah ada di `PortWorkerState.request_reset()` |
| HR-011: Magic wait values | monolith | 13 undocumented timing constants | ADOPT_FROM_GOOD | SAIKI constants lebih sedikit. GOOD punya lebih detail |
| HR-012/021: Telegram mock always fails | kk_flow.py | mock_telegram_gateway_query() always returns not found | REJECT | Tidak functional |
| HR-013: NIK&NIK mode KK=NIK | full_flow.py:1893 | KK = NIK jika format_mode NIK&NIK | ADOPT_FROM_GOOD | SAIKI belum punya |
| HR-014: Grace date 2-format parsing | classifier.py | ISO YYYY-MM-DD dan DD-MM-YYYY | KEEP_SAIKI | SAIKI sudah support |
| HR-015: Power injection lock | injection.py | BoundedSemaphore(2) | ADOPT_FROM_GOOD | SAIKI belum punya |
| HR-016: Status update guard priority | status_guard.py | OFF→IDLE and READY→IDLE blocked | KEEP_SAIKI | Sudah ada |
| HR-017: CHECKING overlay stuck fix | status_guard.py | READY re-detected from CHECKING → re-render | ADOPT_FROM_GOOD | SAIKI belum punya |
| HR-018: CHECKING threshold | cpin.py | >=2 consecutive UNKNOWN | KEEP_SAIKI | Sudah ada |
| HR-019: Two CPIN failure counters | cpin.py | cpin_failure_count + unknown_failure_count | MERGE | SAIKI punya tapi perlu divalidasi |
| HR-020: NIK/KK validation only at cache write | kk_flow.py | No validation on extraction | KEEP_SAIKI | SAIKI belum punya cache |
| HR-021b: Telegram mock ignores NIK | kk_flow.py | Parameter not used | REJECT | Tidak functional |

---

## SUMMARY

| Decision | Count | % |
|----------|-------|---|
| KEEP_SAIKI | 42 | 53% |
| ADOPT_FROM_GOOD | 25 | 31% |
| MERGE | 10 | 13% |
| REJECT | 3 | 4% |
| **Total** | **80** | **100%** |

### Top ADOPT_FROM_GOOD Items (P0):
1. USSD 9-tier classification
2. USSD Intent classification
3. USSD Session Fence (complete logic)
4. Grace Read Window
5. Phone Cache
6. abai_aktif/abai_tenggang bypass flags
7. NIK&NIK format mode
8. Power injection lock
9. Provisional success evaluation
10. Local DB lookup sebelum USSD

### Top MERGE Items:
1. AT+CFUN=1,1 ke reset flow
2. Days remaining calculation (4 format support)
3. Card cycle clear path validation
4. CPIN failure counters validation
5. Baud detection (SAIKI already more comprehensive)
