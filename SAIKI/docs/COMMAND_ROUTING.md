# SAIKI — Command Routing Specification

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## 1. GUI Buttons → Controller Events

### Action Bar Buttons

| Button | Event | Workflow | Scope |
|--------|-------|----------|-------|
| "Cek Nomor Massal" | `cmd.mass.cek_nomor` | `check_number` | mass |
| "Reaktivasi Massal" | `cmd.mass.reaktivasi` | `reactivate_full` | mass |
| "Restart All" | `cmd.restart_all` | `hardware_restart` | mass |
| "Reset Modem" (selected port) | `cmd.reset_modem` | `hardware_reset` | per_port |
| "Auto Run: ON/OFF" | `cmd.auto_run.toggle` | toggle config | global |

### Context Menu (right-click per port)

| Menu Item | Event | Workflow | Eligibility |
|-----------|-------|----------|-------------|
| On Port | `cmd.port.on` | direct | none |
| Off Port | `cmd.port.off` | direct | none |
| Restart Port | `cmd.restart_port` | `hardware_restart` | hw_ready |
| Reset Port | `cmd.reset_modem` | `hardware_reset` | hw_ready |
| Reprocess | `cmd.force_retry` | direct | worker_alive |
| Cek Nomor | `cmd.cek_nomor` | `check_number` | sim_ready |
| Cek Status SIM | `cmd.cek_status` | `check_status` | sim_ready |
| Cek NIK | `cmd.cek_nik` | `check_nik` | sim_ready |
| Cari / Ambil KK | `cmd.cari_kk` | `check_kk` | sim_ready |
| Reaktivasi | `cmd.reactivate` | `reactivate_full` | sim_ready |
| Cek Limit | `cmd.cek_limit` | `check_number` | sim_ready |

---

## 2. Controller → Engine Routing

### COMMAND_ROUTES Table (21 entries)

| Event | Command Name | Workflow | Scope | Eligibility | UI Label |
|-------|-------------|----------|-------|-------------|----------|
| `cmd.cek_nomor` | `cek_nomor` | `check_number` | per_port | sim_ready | Cek Nomor |
| `cmd.cek_status` | `cek_status` | `check_status` | per_port | sim_ready | Cek Status SIM |
| `cmd.cek_nik` | `cek_nik` | `check_nik` | per_port | sim_ready | Cek NIK |
| `cmd.cari_kk` | `cari_kk` | `check_kk` | per_port | sim_ready | Cari KK |
| `cmd.cek_limit` | `cek_limit` | `check_number` | per_port | sim_ready | Cek Limit |
| `cmd.reactivate` | `reaktivasi` | `reactivate_full` | per_port | sim_ready | Reaktivasi |
| `cmd.reset_modem` | `reset_modem` | `hardware_reset` | per_port | hw_ready | Reset Modem |
| `cmd.restart_port` | `restart_port` | `hardware_restart` | per_port | hw_ready | Restart Port |
| `cmd.force_retry` | `force_retry` | direct | per_port | worker_alive | Reprocess |
| `cmd.mass.cek_nomor` | `mass.cek_nomor` | `check_number` | mass | sim_ready | Cek Nomor Massal |
| `cmd.mass.reaktivasi` | `mass.reaktivasi` | `reactivate_full` | mass | sim_ready | Reaktivasi Massal |
| `cmd.restart_all` | `restart_all` | `hardware_restart` | mass | hw_ready | Restart All |
| `cmd.stop_all` | `stop_all` | direct | mass | none | Stop All |
| `cmd.auto_run.toggle` | `auto_run.toggle` | direct | global | none | Auto Run Toggle |
| `cmd.port.on` | `port.on` | direct | per_port | none | On Port |
| `cmd.port.off` | `port.off` | direct | per_port | none | Off Port |
| `cmd.port.exclude` | `port.exclude` | direct | per_port | none | Exclude Port |
| `cmd.port.include` | `port.include` | direct | per_port | none | Include Port |
| `cmd.db.lookup_nik` | `db.lookup_nik` | direct | per_port | none | Lookup NIK |
| `cmd.db.lookup_kk` | `db.lookup_kk` | direct | per_port | none | Lookup KK |
| `cmd.save_config` | `save_config` | direct | global | none | Save Config |

---

## 3. Engine → Runner → Skill

### AutomationEngine Flow
```
handle_trigger(trigger, port)
  → scheduler.evaluate_trigger() → action
  → policy.select_workflow() → workflow_name
  → _enqueue(port, workflow_name, trigger)
    → WorkflowQueue.enqueue(QueueItem)
      → _worker_loop() dequeues
        → _execute_workflow(item)
          → runner.run(workflow, port, trigger_id)
```

### WorkflowRunner Flow
```
run(workflow, port, trigger_id)
  → for each step_name in workflow.steps:
      → skill_entry = skill_map[step_name]
      → if hasattr(skill_entry, 'resolve'):
          skill = skill_entry.resolve(resolver)  # factory pattern
        else:
          skill = skill_entry
      → skill_result = skill.execute(port, skill_resolver=resolver, command_id=trigger_id)
      → if not skill_result.success: return FAILED
  → return SUCCESS
```

---

## 4. Skill → AT Command Mapping

| Skill | Primary Command | Fallback | Response Parser |
|-------|----------------|----------|-----------------|
| `cek_nomor` | `AT+CNUM` | USSD (configurable) | `_parse_cnum()` |
| `cek_status` | `AT+CPIN?` | none | `parse_cpin_response()` |
| `cek_nik` | USSD `*185#` | none | raw passthrough |
| `cek_kk` | USSD `*185#` | none | raw passthrough |
| `inject_reaktivasi` | USSD `*185#` | none | raw passthrough |
| `verify_grace` | USSD `*185#` | none | `_classify_card_status()` |
| `restart_hardware` | `ATZ` | none | `check_modem()` |
| `reset_hardware` | serial close/reopen + `AT+CPIN?` | none | `parse_cpin_response()` |

---

## 5. Event → UI Update Mapping

| Backend Event | UI Update |
|---------------|-----------|
| `ui.port.update` | Single cell update in port table |
| `ui.port.discovered` | New row in port table |
| `ui.port.removed` | Row removed from port table |
| `ui.log.append` | Line appended to log viewer |
| `ui.mass.progress` | Status message in footer |
| `ui.footer.update` | Footer counts update |
| `automation.started` | Status → PROCESSING |
| `automation.completed` | Status → IDLE |
| `automation.failed` | Status → IDLE, error in RESPON |
