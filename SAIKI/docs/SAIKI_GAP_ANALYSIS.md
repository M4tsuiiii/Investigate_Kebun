# SAIKI — Gap Analysis

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## Summary

| Category | Implemented | Partial | Missing |
|----------|-------------|---------|---------|
| Core workflows | 9 | 0 | 0 |
| Skills | 8 | 0 | 0 |
| GUI | 85% | 10% | 5% |
| Automation | 90% | 5% | 5% |
| Data persistence | 30% | 20% | 50% |
| Business logic | 70% | 15% | 15% |

---

## P0 — Critical (Blocks product usage)

### GAP-001: Auto-run Default OFF

| Field | Value |
|-------|-------|
| Priority | P0 |
| File | `worker/rules.py:18` |
| Current | `_auto_run_enabled = False` |
| Required | Should be configurable and persist across restarts |
| Impact | User must manually toggle auto-run every launch |
| Fix | Persist auto-run state in `saiki_config.json` |

### GAP-002: Auto-Run State Not Persisted

| Field | Value |
|-------|-------|
| Priority | P0 |
| File | `settings_dialog.py` |
| Current | `auto_run` checkbox saved to config but NOT loaded on startup |
| Required | Auto-run state restored from config on launch |
| Impact | Auto-run always starts OFF regardless of saved setting |
| Fix | Load `modem.auto_run` from config in `SystemBootstrap.__init__()` |

### GAP-003: Cek Nomor Massal → Wrong Workflow

| Field | Value |
|-------|-------|
| Priority | P0 |
| File | `controller.py:443` |
| Current | Mass cek nomor dispatches `check_number` (atomic: cek_nomor only) |
| Required | Should dispatch `check_data` (composite: cek_nomor + cek_nik + cek_kk) |
| Impact | "Cek Nomor Massal" button only checks phone number, not NIK/KK |
| Fix | Change workflow from `check_number` to `check_data` |

### GAP-004: NIK/KK Results Not Saved to UI

| Field | Value |
|-------|-------|
| Priority | P0 |
| File | Skills return data, but no `on_step_complete` callback updates UI |
| Current | Workflow completes but NOMOR/NIK/KK columns remain "-" |
| Required | After each skill, update port table columns |
| Impact | User sees no results despite successful execution |
| Fix | Wire `on_step_complete` callback in controller to publish `ui.port.update` |

### GAP-005: MASA AKTIF Not Populated

| Field | Value |
|-------|-------|
| Priority | P0 |
| File | No skill writes masa_aktif to UI |
| Current | MASA AKTIF column always shows "-" |
| Required | After verify_grace, populate MASA AKTIF with grace_date |
| Impact | User cannot see card expiry information |
| Fix | Add masa_aktif extraction to verify_grace result handling |

### GAP-006: RESPON Column Not Updated

| Field | Value |
|-------|-------|
| Priority | P0 |
| File | No skill writes to RESPON column |
| Current | RESPON always shows "-" |
| Required | Show operation result summary (e.g., "Nomor: 081234567890") |
| Impact | User has no feedback on operation result |
| Fix | Add RESPON update to workflow completion handler |

---

## P1 — Important (Degrades product quality)

### GAP-007: Database Lookups Not Connected to Workflow

| Field | Value |
|-------|-------|
| Priority | P1 |
| File | `db_lookup.py` exists but not used by any skill |
| Current | NIK/KK looked up via USSD only |
| Required | Local DB lookup before USSD to save modem airtime |
| Impact | Wasted USSD charges for cards already in database |
| Fix | Create DB-first skills or add DB lookup step before USSD |

### GAP-008: Telegram Gateway Not Connected

| Field | Value |
|-------|-------|
| Priority | P1 |
| File | Settings has telegram config but no integration |
| Current | Telegram settings saved but never used |
| Required | Send notifications on workflow completion |
| Impact | No remote monitoring capability |
| Fix | Implement Telegram notification on MASS_COMPLETE events |

### GAP-009: Report Tab Empty

| Field | Value |
|-------|-------|
| Priority | P1 |
| File | `main_window.py` renders REPORT tab |
| Current | Report tab has UI (panen tree, buttons) but no data source |
| Required | Show history of operations per card |
| Impact | User cannot review past operations |
| Fix | Save workflow results to SQLite, display in REPORT tab |

### GAP-010: Log Viewer Not Populated

| Field | Value |
|-------|-------|
| Priority | P1 |
| File | `log_viewer.py` exists but `append_log_line` rarely called |
| Current | LOG button opens empty viewer |
| Required | Show per-port operation logs |
| Impact | User cannot debug per-port issues |
| Fix | Route skill logs to per-port log buffer |

### GAP-011: Cek Limit Uses Wrong Skill

| Field | Value |
|-------|-------|
| Priority | P1 |
| File | `controller.py` routes `cmd.cek_limit` to `check_number` |
| Current | "Cek Limit" runs AT+CNUM (same as Cek Nomor) |
| Required | Should check pulsa/quota via USSD (different code) |
| Impact | "Cek Limit" doesn't show credit/quota information |
| Fix | Create `cek_limit` skill with specific USSD code |

### GAP-012: No Confirmation Dialog for Destructive Actions

| Field | Value |
|-------|-------|
| Priority | P1 |
| File | `main_window.py`, `context_menu.py` |
| Current | Reset Modem, Restart All execute immediately |
| Required | Confirmation dialog for mass operations |
| Impact | Accidental click triggers operations on all ports |
| Fix | Add `messagebox.askyesno()` before mass commands |

---

## P2 — Nice to Have (Enhancements)

### GAP-013: No Batch Size Limit for Mass Operations

| Field | Value |
|-------|-------|
| Priority | P2 |
| File | `controller.py` mass handlers |
| Current | Mass operations dispatch to ALL active ports |
| Required | Configurable batch size (e.g., 10 at a time) |
| Impact | 50+ modems may overwhelm USB hub |
| Fix | Add batch_size config, dispatch in groups |

### GAP-014: No Export Functionality

| Field | Value |
|-------|-------|
| Priority | P2 |
| File | None |
| Current | No CSV/Excel export |
| Required | Export card data to CSV |
| Impact | Manual data entry for external systems |
| Fix | Add export button to REPORT tab

### GAP-015: No Modem Health Dashboard

| Field | Value |
|-------|-------|
| Priority | P2 |
| File | None |
| Current | Only basic status (IDLE/READY/OFF) |
| Required | Signal quality, temperature, uptime |
| Impact | Cannot monitor modem health |
| Fix | Add AT+CSQ, AT+CMEE queries

### GAP-016: No Workflow Timeout Configuration

| Field | Value |
|-------|-------|
| Priority | P2 |
| File | Skills use hardcoded timeouts |
| Current | AT=2s, USSD=30s, not configurable |
| Required | Per-workflow timeout in settings |
| Impact | Slow networks may cause premature timeouts |
| Fix | Add timeout settings per workflow type

### GAP-017: No Per-Port Settings Override

| Field | Value |
|-------|-------|
| Priority | P2 |
| File | Settings are global |
| Current | All ports share same USSD code, timeouts |
| Required | Per-port USSD code override |
| Impact | Different SIM providers need different codes |
| Fix | Add port-level settings in UI

---

## Current State Assessment

### What Works End-to-End
1. **Port discovery** — USB plugged in → COM detected → worker created
2. **SIM monitoring** — CpinRuntime polls → state transitions → UI updates
3. **Manual per-port commands** — Right-click → skill executes → result logged
4. **Mass commands (partial)** — Button click → dispatch → workflow runs
5. **Hardware reset** — Close serial → wait → reopen → detect SIM
6. **Port exclusion** — Right-click → exclude → automation skipped

### What Doesn't Work End-to-End
1. **Results don't reach UI** — Skills return data but columns stay "-"
2. **Auto-run doesn't persist** — Always starts OFF
3. **Cek Nomor Massal is incomplete** — Only checks number, not NIK/KK
4. **Report tab is empty** — No data source
5. **Log viewer is empty** — No log routing
6. **Database not connected** — No DB-first lookup
7. **Telegram not connected** — Settings exist but no integration

### First Real-World Breakpoint
The **first breakpoint** when running on real hardware: **GAP-004** — Results don't reach the UI. The workflow executes successfully but the user sees no data in the port table columns. This makes the product appear broken even though the backend works correctly.
