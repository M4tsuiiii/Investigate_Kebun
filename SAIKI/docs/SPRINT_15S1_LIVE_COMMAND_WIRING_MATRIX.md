# Sprint 15S.1 Live Command Wiring Matrix

Complete mapping of every GUI interactive control → callback → event → handler → workflow → result.

## Workspace Action Bar Buttons

| Label | Source File | Callback | CommandEvent | Controller Handler | Workflow | Eligibility | UI Feedback |
|---|---|---|---|---|---|---|---|
| Auto Run: ON/OFF | `main_window.py:405` | `_on_auto_run_toggle` | `cmd.auto_run.toggle` | `_handle_auto_run_toggle` | None (config toggle) | None | Button text/color toggle |
| Reaktivasi Massal | `main_window.py:417` | `_on_mass_reaktivasi` | `cmd.mass.reaktivasi` | `_handle_mass_reaktivasi` | `reactivate_full` | sim_ready | `[COMMAND RESULT]` |
| Cek Nomor Massal | `main_window.py:422` | `_on_mass_cek_nomor` | `cmd.mass.cek_nomor` | `_handle_mass_cek_nomor` | `check_number` | sim_ready | `[COMMAND RESULT]` |
| Restart All | `main_window.py:427` | `_on_restart_all` | `cmd.restart_all` | `_handle_restart_all` | `hardware_restart` | hw_ready | `[COMMAND RESULT]` |
| Reset Modem | `main_window.py:431` | `_on_reset_modem` | `cmd.reset_modem` | `_handle_reset_modem` | `hardware_reset` | hw_ready | `[COMMAND RESULT]` or feedback if no port |

## Per-Port Context Menu Actions

| Label | CommandEvent | Controller Handler | Workflow | Eligibility |
|---|---|---|---|---|
| On Port | `cmd.port.on` | `_handle_port_on` | None (direct start) | Worker exists |
| Off Port | `cmd.port.off` | `_handle_port_off` | None (direct stop) | Worker exists |
| Restart Port | `cmd.force_retry` | `_handle_force_retry` | None (direct retry) | Worker alive |
| Reset Port | `cmd.reset_modem` | `_handle_reset_modem` | `hardware_reset` | hw_ready |
| Reprocess | `cmd.force_retry` | `_handle_force_retry` | None (direct retry) | Worker alive |
| Cek Nomor | `cmd.cek_nomor` | `_handle_port_command` | `check_number` | sim_ready |
| Cek NIK | `cmd.cek_nik` | `_handle_port_command` | `check_nik` | sim_ready |
| Cari / Ambil KK | `cmd.cari_kk` | `_handle_port_command` | `check_kk` | sim_ready |
| Reaktivasi | `cmd.reactivate` | `_handle_port_command` | `reactivate_full` | sim_ready |
| Cek Limit | `cmd.cek_limit` | `_handle_port_command` | `check_number` | sim_ready |
| Lookup by NIK | `cmd.db.lookup_nik` | `_handle_db_lookup_nik` | None (DB only) | Worker exists |
| Lookup by KK | `cmd.db.lookup_kk` | `_handle_db_lookup_kk` | None (DB only) | Worker exists |

## Delivery Trace Sequence

Every command traverses this exact path:

```
GUI callback → [COMMAND CLICK]
  → EventBus.publish(CommandEvent)
    → Controller subscribed handler
      → [COMMAND DISPATCH]
      → eligibility check
        → if skipped: [COMMAND SKIPPED] + [COMMAND RESULT] OUTCOME=skipped
        → if eligible:
          → PORT_UPDATE STATUS=PROCESSING
          → AutomationEngine.enqueue_workflow(...)
          → [COMMAND ENQUEUED]
          → [COMMAND RESULT] OUTCOME=enqueued
          → (async) automation.completed → [COMMAND RESULT] OUTCOME=success
          → (async) automation.failed → [COMMAND RESULT] OUTCOME=failed
```

## Centralized Routing Table

Defined in `worker/ui/controller.py` as `COMMAND_ROUTES`:

```python
COMMAND_ROUTES = [
    # (event_name, command_name, workflow_or_action, scope, eligibility, ui_label)
    ("cmd.cek_nomor",       "cek_nomor",       "check_number",      "per_port", "sim_ready",  "Cek Nomor"),
    ("cmd.cek_nik",         "cek_nik",         "check_nik",         "per_port", "sim_ready",  "Cek NIK"),
    ("cmd.cari_kk",         "cari_kk",         "check_kk",          "per_port", "sim_ready",  "Cari KK"),
    ("cmd.cek_limit",       "cek_limit",       "check_number",      "per_port", "sim_ready",  "Cek Limit"),
    ("cmd.reactivate",      "reaktivasi",      "reactivate_full",   "per_port", "sim_ready",  "Reaktivasi"),
    ("cmd.reset_modem",     "reset_modem",     "hardware_reset",    "per_port", "hw_ready",   "Reset Modem"),
    ("cmd.force_retry",     "force_retry",     None,                "per_port", "worker_alive","Restart Port"),
    ("cmd.mass.cek_nomor",  "mass.cek_nomor",  "check_number",      "mass",     "sim_ready",  "Cek Nomor Massal"),
    ("cmd.mass.reaktivasi", "mass.reaktivasi", "reactivate_full",   "mass",     "sim_ready",  "Reaktivasi Massal"),
    ("cmd.restart_all",     "restart_all",     "hardware_restart",  "mass",     "hw_ready",   "Restart All"),
    ("cmd.stop_all",        "stop_all",        None,                "mass",     None,         "Stop All"),
    ("cmd.auto_run.toggle", "auto_run.toggle", None,                "global",   None,         "Auto Run Toggle"),
    ("cmd.port.on",         "port.on",         None,                "per_port", None,         "On Port"),
    ("cmd.port.off",        "port.off",        None,                "per_port", None,         "Off Port"),
    ("cmd.port.exclude",    "port.exclude",    None,                "per_port", None,         "Exclude Port"),
    ("cmd.port.include",    "port.include",    None,                "per_port", None,         "Include Port"),
    ("cmd.db.lookup_nik",   "db.lookup_nik",   None,                "per_port", None,         "Lookup NIK"),
    ("cmd.db.lookup_kk",    "db.lookup_kk",    None,                "per_port", None,         "Lookup KK"),
    ("cmd.save_config",     "save_config",     None,                "global",   None,         "Save Config"),
]
```

## Eligibility Rules

| Check | Applies To | Reason Code |
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

SIM-dependent: check_number, check_status, check_nik, check_kk, reactivate_full
HW commands: hardware_restart, hardware_reset
