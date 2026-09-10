# SAIKI — Domain Rules

**Version**: 1.0  
**Date**: 2026-09-08  
**Status**: Single Source of Truth

---

## SIM State Rules

| ID | Rule | Source |
|----|------|--------|
| BR-001 | SIM state is determined by `AT+CPIN?` response | `classifier.py` |
| BR-002 | `+CPIN: READY` → CpinState.READY → SIM is operational | `classifier.py` |
| BR-003 | `+CME ERROR: 10` → CpinState.NOT_INSERTED → No SIM | `classifier.py` |
| BR-004 | `+CPIN: SIM PIN` → CpinState.PIN_REQUIRED → Needs PIN | `classifier.py` |
| BR-005 | `NOT READY` → CpinState.NOT_READY → SIM not ready | `classifier.py` |
| BR-006 | Any other response → CpinState.UNKNOWN | `classifier.py` |

## CPIN Polling Rules

| ID | Rule | Source |
|----|------|--------|
| BR-010 | CPIN poll interval: 1.0s normal, 3.0s stable, 0.5s transitional | `constants.py` |
| BR-011 | CPIN poll timeout: 3.0s per AT+CPIN? command | `constants.py` |
| BR-012 | Buffer flush before every CPIN query | `cpin_runtime.py` |
| BR-013 | UNKNOWN threshold: 3 consecutive UNKNOWN → treat as NOT_READY | `CPIN_UNKNOWN_THRESHOLD` |
| BR-014 | CHECKING threshold: 2 intermediate states → stay READY | `CPIN_CHECKING_THRESHOLD` |
| BR-015 | Removal confirmation: 2 consecutive NOT_INSERTED before confirming | `CPIN_MAX_REMOVAL_CONFIRM` |
| BR-016 | READY→NOT_READY: always confirm with second poll | `_check_confirmation_needed()` |
| BR-017 | READY→UNKNOWN: confirm only if unknown_count ≥ 3 | `_check_confirmation_needed()` |
| BR-018 | READY→NOT_INSERTED: confirm only if removal_count ≥ 2 | `_check_confirmation_needed()` |
| BR-019 | Same state: no change, no confirmation | `_check_confirmation_needed()` |
| BR-020 | Any→READY: reset all counters, accept immediately | `_apply_stabilization()` |

## USSD Rules

| ID | Rule | Source |
|----|------|--------|
| BR-025 | USSD cooldown: 4.0s between sessions | `DIAL_COOLDOWN_SECONDS` |
| BR-026 | USSD session fence: 0.75s quiet, 3.0s timeout | `constants.py` |
| BR-027 | USSD session close: `AT+CUSD=2` | `cleanup.py` |
| BR-028 | Buffer flush after every USSD operation | `cleanup.py` |
| BR-029 | Prompt recovery: max 2 retries on prompt response | `PROMPT_RECOVERY_MAX` |
| BR-030 | USSD code for NIK/KK/reactivation: `*185#` | Skills |
| BR-031 | USSD code for number check: configurable via settings | `cek_nomor.py` |

## Auto-Run Rules

| ID | Rule | Source |
|----|------|--------|
| DD-014 | Auto-run is OFF by default | `AutoRunConfig._auto_run_enabled = False` |
| AR-001 | Auto-run blocked if global toggle is OFF | `should_block_auto_run()` |
| AR-002 | Auto-run blocked if modem offline | `should_block_auto_run()` |
| AR-003 | Auto-run blocked if SIM NOT_INSERTED | `should_block_auto_run()` |
| AR-004 | Auto-run blocked if SIM PIN_REQUIRED | `should_block_auto_run()` |
| AR-005 | Auto-run blocked if awaiting card cycle | `should_block_auto_run()` |
| AR-006 | Auto-run blocked if CPIN unknown threshold reached | `should_block_auto_run()` |
| AR-007 | Auto-run steps: cek_nomor → cek_status → cek_nik → cek_kk → reaktivasi | `_execute_auto_run()` |
| AR-008 | Auto-run checks modem_online between each step | `_execute_auto_run()` |

## Port Lifecycle Rules

| ID | Rule | Source |
|----|------|--------|
| PL-001 | Port states: DISCOVERED → VALID_MODEM → ACTIVE → EXCLUDED/OFFLINE/REMOVED | `PortState` |
| PL-002 | EXCLUDED ports skip all automation | `AutomationEngine` |
| PL-003 | EXCLUDED ports cancel queued workflows | `_on_port_excluded()` |
| PL-004 | OFFLINE ports destroy worker, await revalidation | `_handle_modem_offline()` |
| PL-005 | Port cooldown: 30s after failure before retry | `DISCOVERY_RETRY_COOLDOWN` |
| PL-006 | Numeric port sorting: COM9 before COM10 | `sort_com_ports()` |
| PL-007 | Candidate filter priority: HWID/VID > high-priority keywords > generic | `filter_candidates()` |
| PL-008 | Generic "USB Serial" rejected without HWID/VID match | `filter_candidates()` |

## Workflow Execution Rules

| ID | Rule | Source |
|----|------|--------|
| WF-001 | Steps execute in list order, strictly sequential | `runner.py` |
| WF-002 | First failure stops workflow | `runner.py` |
| WF-003 | No inter-skill calls | Architecture rule |
| WF-004 | Cleanup between non-final steps | `runner.py` |
| WF-005 | Each workflow in own thread | `engine.py` |
| WF-006 | Max 2 concurrent workflows | `WorkflowQueue.max_concurrent` |
| WF-007 | Duplicate trigger: same port+trigger within 5s → skip | `engine.py` |
| WF-008 | Reactivation retry: max 1 retry if grace unchanged | `ReactivateRetryPolicy` |

## Reset Rules

| ID | Rule | Source |
|----|------|--------|
| RS-001 | Reset pauses CpinRuntime before closing serial | `ResetHardwareSkill` |
| RS-002 | Reset waits 15s for modem stabilization | `STABILIZATION_SECONDS` |
| RS-003 | Reset resumes CpinRuntime after reopening | `ResetHardwareSkill` |
| RS-004 | Reset detects SIM state after reopen | `ResetHardwareSkill` |
| RS-005 | Reset clears all pending actions | `PortWorkerState.request_reset()` |

## Eligibility Rules

| ID | Rule | Source |
|----|------|--------|
| EL-001 | No worker → skip | `_check_port_eligibility()` |
| EL-002 | Port EXCLUDED → skip | `_check_port_eligibility()` |
| EL-003 | Worker not alive → skip | `_check_port_eligibility()` |
| EL-004 | Modem offline → skip | `_check_port_eligibility()` |
| EL-005 | SIM-dependent command + NOT_INSERTED → skip | `_check_port_eligibility()` |
| EL-006 | SIM-dependent command + NOT_READY → skip | `_check_port_eligibility()` |
| EL-007 | SIM-dependent command + UNKNOWN → skip | `_check_port_eligibility()` |
| EL-008 | SIM-dependent command + PIN_REQUIRED → skip | `_check_port_eligibility()` |
| EL-009 | HW command + not connected → skip | `_check_port_eligibility()` |

## Serial Ownership Rules

| ID | Rule | Source |
|----|------|--------|
| SO-001 | One owner per serial at a time | `_modem_lock` in PortWorker |
| SO-002 | CPIN runtime stops before reset | `ResetHardwareSkill` |
| SO-003 | CPIN runtime resumes after reset | `ResetHardwareSkill` |
| SO-004 | AT+CPIN? not sent while serial owned by reset | `_modem_lock` |

## Skill Dependency Rules

| ID | Rule | Source |
|----|------|--------|
| SD-001 | Skills resolved per-port via SkillDependencyResolver | `dependency_resolver.py` |
| SD-002 | Factory pattern: skill instances created at execution time | `system_bootstrap.py` |
| SD-003 | No global skill-map overwrite | Architecture rule |
| SD-004 | Each skill gets its port's ATClient/UssdRuntime | `dependency_resolver.py` |
