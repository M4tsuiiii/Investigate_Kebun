# Sprint 15S Command Matrix

Complete mapping: UI Action → CommandEvent → Controller Handler → Workflow → Skills → Eligibility.

## Per-Port Context Menu Actions

| UI Menu Item | CommandEvent | Event Name | Workflow | Skill(s) | Eligibility |
|---|---|---|---|---|---|
| On Port | `PORT_ON` | `cmd.port.on` | N/A | N/A | Worker exists |
| Off Port | `PORT_OFF` | `cmd.port.off` | N/A | N/A | Worker exists |
| Restart Port | `FORCE_RETRY` | `cmd.force_retry` | N/A (direct) | N/A | Worker alive |
| Reset Port | `RESET_MODEM` | `cmd.reset_modem` | `hardware_reset` | `reset_hardware` | alive, modem_online, serial connected |
| Reprocess | `FORCE_RETRY` | `cmd.force_retry` | N/A (direct) | N/A | Worker alive |
| **Cek Nomor** | `CEK_NOMOR` | `cmd.cek_nomor` | `check_number` | `cek_nomor` | alive, modem_online, CPIN READY |
| **Cek NIK** | `CEK_NIK` | `cmd.cek_nik` | `check_nik` | `cek_nik` | alive, modem_online, CPIN READY |
| **Cari / Ambil KK** | `CARI_KK` | `cmd.cari_kk` | `check_kk` | `cek_kk` | alive, modem_online, CPIN READY |
| **Reaktivasi** | `REAKTIVASI` | `cmd.reaktivasi` | `reactivate_full` | cek_nomor, cek_status, cek_nik, cek_kk, inject_reaktivasi, verify_grace | alive, modem_online, CPIN READY |
| **Cek Limit** | `CEK_LIMIT` | `cmd.cek_limit` | `check_number` | `cek_nomor` | alive, modem_online, CPIN READY |
| Lookup by NIK | `DB_LOOKUP_NIK` | `cmd.db.lookup_nik` | N/A (DB only) | N/A | Worker exists |
| Lookup by KK | `DB_LOOKUP_KK` | `cmd.db.lookup_kk` | N/A (DB only) | N/A | Worker exists |

## Mass Actions (Toolbar)

| UI Button | CommandEvent | Workflow | Skill(s) | Thread |
|---|---|---|---|---|
| **Cek Nomor Massal** | `cmd.mass.cek_nomor` | `check_number` | `cek_nomor` | `MassDispatch-check_number-{id}` |
| **Reaktivasi Massal** | `cmd.mass.reaktivasi` | `reactivate_full` | cek_nomor, cek_status, cek_nik, cek_kk, inject_reaktivasi, verify_grace | `MassDispatch-reaktivasi-{id}` |
| Restart All | `cmd.restart_all` | `hardware_restart` | `restart_hardware` | caller thread |
| Stop All | `cmd.stop_all` | N/A | N/A | caller thread |

## AutomationEngine Triggers

| Event | Trigger | Source |
|---|---|---|
| `modem.online` | `Trigger.MODEM_ONLINE` | Controller |
| `modem.offline` | `Trigger.MODEM_OFFLINE` | Controller |
| `cpin.transition` (READY) | `Trigger.CPIN_READY` | Controller |
| `cpin.transition` (PIN_REQUIRED/NOT_READY) | `Trigger.CPIN_REQUIRED` | Controller |

## Eligibility Rules (per-port)

A port is **skipped** (with `[COMMAND SKIPPED]` trace) when:

| Check | Applies To | Reason |
|---|---|---|
| No worker | All | `no_worker` |
| Port excluded | All | `excluded` |
| Worker not alive | All | `worker_not_alive` |
| Modem offline | All | `modem_offline` |
| CPIN NOT_INSERTED | SIM-dependent | `sim_not_inserted` |
| CPIN NOT_READY | SIM-dependent | `not_ready` |
| CPIN UNKNOWN | SIM-dependent | `unknown_state` |
| CPIN PIN_REQUIRED | SIM-dependent | `pin_required` |
| Serial not connected | HW commands | `disconnected` |

**SIM-dependent commands**: `check_number`, `check_status`, `check_nik`, `check_kk`, `reactivate_full`
**HW commands**: `hardware_restart`, `hardware_reset`

## Delivery Traces

```
[COMMAND CLICK]    ID=N COMMAND=<name> PORT=<port> WORKFLOW=<wf> SOURCE=<src>
[COMMAND DISPATCH] ID=N COMMAND=<name> PORT=<port> WORKFLOW=<wf>
[COMMAND ENQUEUED] ID=N PORT=<port> WORKFLOW=<wf>
[COMMAND SKIPPED]  ID=N PORT=<port> COMMAND=<name> REASON=<reason>
[COMMAND RESULT]   ID=N COMMAND=<name> enqueued=<count>
```

## Workflow Registry (Sprint 15S additions)

| Workflow Name | Steps | Type |
|---|---|---|
| `check_number` | `cek_nomor` | Atomic |
| `check_status` | `cek_status` | Atomic |
| `check_nik` | `cek_nik` | Atomic |
| `check_kk` | `cek_kk` | Atomic |
| `check_data` | `cek_nomor` → `cek_nik` → `cek_kk` | Composite |
| `reactivate_fast` | `inject_reaktivasi` → `verify_grace` | Composite |
| `reactivate_full` | `cek_nomor` → `cek_status` → `cek_nik` → `cek_kk` → `inject_reaktivasi` → `verify_grace` | Composite |
| `hardware_restart` | `restart_hardware` | Atomic |
| `hardware_reset` | `reset_hardware` | Atomic |

## Critical Bug Fix (Sprint 15S)

**Before**: "Cek Nomor Massal" button → `_handle_mass_cek_nomor` → `enqueue_workflow("check_data")` → runs `cek_nomor→cek_nik→cek_kk` (3-step composite)

**After**: "Cek Nomor Massal" button → `_handle_mass_cek_nomor` → `enqueue_workflow("check_number")` → runs `cek_nomor` only (atomic)
