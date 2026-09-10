# SAIKI — Product Requirement Document (PRD)

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## 1. Product Vision

SAIKI is a desktop modem automation platform for mass SIM card reactivation and data management. It controls multiple USB modems simultaneously, performing AT-command-based operations: checking phone numbers, verifying NIK/KK registration, injecting reactivation commands, and monitoring SIM card status — all from a single GUI.

**Target users**: Small-scale SIM card resellers and reactivation operators managing 1–50 Quectel M26 modems.

---

## 2. User Goals

| # | Goal | Priority |
|---|------|----------|
| G-01 | View all connected modems and their SIM status in real time | P0 |
| G-02 | Check phone number (MSISDN) on one or all modems | P0 |
| G-03 | Check NIK registration on one or all modems | P0 |
| G-04 | Check KK (family card) registration on one or all modems | P0 |
| G-05 | Inject reactivation command on one or all modems | P0 |
| G-06 | Verify card status after reactivation (AKTIF/TENGGANG/HANGUS) | P0 |
| G-07 | Restart or reset modem hardware when unresponsive | P1 |
| G-08 | Enable auto-run so workflows trigger automatically on SIM ready | P1 |
| G-09 | Exclude problematic ports from automation | P1 |
| G-10 | View operation history and results | P2 |
| G-11 | Export data to Telegram or database | P2 |

---

## 3. Supported Modem Operations

### 3.1 Per-Port Operations (right-click context menu)

| Operation | Command | Skill |
|-----------|---------|-------|
| Cek Nomor | `AT+CNUM` → USSD fallback | `cek_nomor` |
| Cek Status SIM | `AT+CPIN?` | `cek_status` |
| Cek NIK | USSD `*185#` | `cek_nik` |
| Cari / Ambil KK | USSD `*185#` | `cek_kk` |
| Reaktivasi | USSD `*185#` | `inject_reaktivasi` |
| Cek Limit | `AT+CNUM` | `cek_nomor` (reuse) |
| Restart Port | `ATZ` | `restart_hardware` |
| Reset Port | Close → wait → reopen → detect SIM | `reset_hardware` |

### 3.2 Mass Operations (action bar buttons)

| Operation | Workflow | Trigger |
|-----------|----------|---------|
| Cek Nomor Massal | `check_number` on all ports | Button click |
| Reaktivasi Massal | `reactivate_full` on all ports | Button click |
| Restart All | `hardware_restart` on all ports | Button click |

---

## 4. Auto-Run Requirements

| # | Requirement | Rule |
|---|-------------|------|
| AR-01 | Auto-run is OFF by default | `AutoRunConfig._auto_run_enabled = False` |
| AR-02 | User toggles via "Auto Run: ON/OFF" button | `cmd.auto_run.toggle` |
| AR-03 | Auto-run blocked when: modem offline, SIM not inserted, PIN required, awaiting card cycle, CPIN unknown threshold reached | `should_block_auto_run()` in `rules.py` |
| AR-04 | Auto-run steps: cek_nomor → cek_status → cek_nik → cek_kk → reaktivasi | `_execute_auto_run()` in `port_worker.py` |
| AR-05 | Auto-run checks modem_online between each step | `_execute_auto_run()` |

---

## 5. Monitoring Requirements

| # | Requirement | Implementation |
|---|-------------|----------------|
| MON-01 | Port table shows 8 columns: PORT, NOMOR, NIK, KK, STATUS, RESPON, MASA AKTIF, LOG | `port_table.py` |
| MON-02 | Status color coding: green=sukses, blue=proses, gray=idle, red=gagal | `_apply_status_tag()` |
| MON-03 | Footer shows active/off/excluded counts | `update_footer()` |
| MON-04 | Log viewer per port (clickable LOG button) | `LogViewer` |
| MON-05 | Worker monitor shows per-port thread status | `WorkerMonitor` |

---

## 6. Failure Recovery Requirements

| # | Requirement | Rule |
|---|-------------|------|
| FR-01 | CPIN UNKNOWN threshold: after 3 consecutive UNKNOWN → treat as NOT_READY | `CPIN_UNKNOWN_THRESHOLD = 3` |
| FR-02 | CPIN confirmation poll: READY→NOT_READY always confirmed; READY→UNKNOWN confirmed after threshold | `_check_confirmation_needed()` |
| FR-03 | SIM removal confirmation: 2 consecutive NOT_INSERTED before confirming | `CPIN_MAX_REMOVAL_CONFIRM = 2` |
| FR-04 | Reset hardware: pause CPIN → close serial → wait 15s → reopen → resume CPIN → detect SIM | `ResetHardwareSkill` |
| FR-05 | Port excluded: cancels queued workflows, stops automation | `exclude_port()` |
| FR-06 | Modem offline: destroys worker, waits for scan revalidation | `_handle_modem_offline()` |
| FR-07 | Reactivation retry: max 1 retry if grace period unchanged | `ReactivateRetryPolicy` |
| FR-08 | Port cooldown: failed ports excluded from discovery for 30s | `DISCOVERY_RETRY_COOLDOWN = 30.0` |

---

## 7. Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Port scan interval | 3s | Background discovery |
| AT command timeout | 2s | `DEFAULT_AT_TIMEOUT` |
| USSD dial timeout | 30s | Per USSD operation |
| USSD cooldown | 4s | Between USSD sessions |
| CPIN poll interval | 1s normal, 3s stable, 0.5s transitional | Adaptive polling |
| Stabilization after reset | 15s | `STABILIZATION_SECONDS` |
| Max concurrent workflows | 2 | `WorkflowQueue.max_concurrent` |
| Max concurrent probes | 4 | `DISCOVERY_MAX_CONCURRENT` |
| Duplicate trigger window | 5s | Same port+trigger dedup |
| GUI update batch interval | 100ms | `_drain_events` |

---

## 8. Hardware Specification

| Component | Specification |
|-----------|---------------|
| Modem | Quectel M26 |
| Baud rate | 115200 (primary), 9600/19200 fallback |
| Interface | USB Serial (XR21V1414 USB UART bridge) |
| AT protocol | Standard 3GPP TS 27.007 |
| USSD | +CUSD command |
| SIM | Standard mini/micro SIM |

---

## 9. Data Model

### SQLite Schema (`kebun.db`)

```sql
CREATE TABLE cards (
    nomor TEXT PRIMARY KEY,
    nik TEXT,
    kk TEXT,
    masa_aktif TEXT,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Port State Model

Each port tracks:
- `nomor` — phone number
- `nik` — national ID
- `kk` — family card number
- `masa_aktif` — active period
- `status` — PortStatus enum
- `cpin_state` — CpinState enum
- `modem_online` — bool
