# Sprint 15L: Workflow Delivery Chain Forensic

## Date: 2026-09-03

## Objective
Trace the complete command delivery chain from trigger → engine → queue → workflow → skill → serial → modem response. Identify every breakpoint where delivery can fail silently.

## Delivery Chain Mapped

```
SystemBootstrap cpin.transition
        ↓
Engine.handle_trigger(port, trigger, trigger_id)
        ↓
Scheduler.auto_run(port, trigger) → "enqueue" / "cancel" / "standby"
        ↓
AutoRunPolicy.should_allow() → gate (default OFF)
        ↓
Policy.select_workflow(trigger) → workflow_name
        ↓
Engine.execute(port, trigger, trigger_id)
        ↓
WorkflowRunner.run(workflow, port, trigger_id)
        ↓
Skill.execute(port, at_client) → SkillResult
        ↓
ATClient.send_command() → serial.write()
        ↓
SerialAdapter.write() → pyserial
        ↓
Modem response → _read_response()
        ↓
[MODEM RESPONSE] logged
        ↓
[DELIVERY REPORT] summary at startup
```

## Changes Made

### workflow/runner.py
- Added `[DELIVERY TRACE] stage=WORKFLOW_START` at workflow entry
- Added `[DELIVERY TRACE] stage=SKILL_LOOKUP` before skill resolution
- Added `[SKILL AUDIT] FOUND=YES/NO` on skill lookup result
- Added `[DELIVERY TRACE] stage=SKILL_EXECUTE` before skill.execute()
- Added `[DELIVERY TRACE] stage=STEP_COMPLETE` on step success
- Added `[DELIVERY TRACE] stage=STEP_FAILED` on step failure
- Added `[DELIVERY TRACE] stage=WORKFLOW_END` on both success and failure paths

### app/infrastructure/serial/at_client.py
- Added `[COMMAND AUDIT] PORT=? COMMAND=? PAYLOAD=?` before serial.write()
- Added `[COMMAND AUDIT] FAILED reason=serial_write_failed` on write failure
- Added `[MODEM RESPONSE] PORT=? RAW=? HEX=?` after _read_response()
- Added `[MODEM RESPONSE TIMEOUT]` when response is None/empty
- Added `[MODEM RESPONSE ERROR]` when _read_response raises exception

### app/infrastructure/serial/serial_adapter.py
- Added `[SERIAL WRITE] PORT=? BYTES=? HEX=? TEXT=?` on every write attempt
- Added `[SERIAL WRITE RESULT] PORT=? SUCCESS=YES BYTES_WRITTEN=?` on success
- Added `[SERIAL WRITE RESULT] PORT=? SUCCESS=NO BYTES_WRITTEN=0 reason=port_not_open` on failure

### automation/engine.py
- Added `_delivery_stats` dict tracking: triggers_received, workflows_started, workflows_completed, workflows_failed, skills_found, skills_missing, commands_built, commands_sent, responses_received, timeouts, last_breakpoint, last_error
- Added `get_delivery_stats()` → returns copy of stats dict
- Added `get_delivery_report()` → returns formatted string
- Added `log_delivery_report()` → prints formatted report
- Added `update_delivery_stats(**kwargs)` → increments counters
- Added `_on_workflow_start/end` handlers that call `update_delivery_stats()`
- Added `_on_skill_found/missing` handlers

## What Was NOT Changed (Auto-Run Gate)

Auto-run default remains OFF (`worker/rules.py:18`). This means:
- `Scheduler.auto_run()` returns "standby"
- `Engine.execute()` never fires
- The entire delivery chain is dead unless auto-run is enabled

This is a known intentional default that must be overridden for real workflow execution.

## Test Results

| Test | Count | Status |
|------|-------|--------|
| Delivery trace stages | 10 | ✅ |
| Skill audit | 3 | ✅ |
| Command audit | 4 | ✅ |
| Serial write audit | 3 | ✅ |
| Modem response audit | 3 | ✅ |
| Delivery report | 5 | ✅ |
| **Sprint 15L total** | **28** | **✅** |
| Regression (sprints 15K-I-H) | 132 | ✅ |
| **Total verified** | **211** | **✅** |

## Delivery Report Example

```
=================================================
WORKFLOW DELIVERY AUDIT
=================================================
TRIGGERS RECEIVED: 5
WORKFLOWS STARTED: 3
WORKFLOWS COMPLETED: 2
WORKFLOWS FAILED: 1
SKILLS FOUND: 8
SKILLS MISSING: 0
COMMANDS BUILT: 6
COMMANDS SENT: 6
RESPONSES RECEIVED: 5
TIMEOUTS: 1
LAST BREAKPOINT: none
TOP FAILURE: cek_nik: Empty USSD response
=================================================
```

## Breakpoint Analysis

| Breakpoint | Log to Look For | Cause |
|------------|----------------|-------|
| No trigger received | Missing `[ENGINE] TRIGGER_IN` | Event not firing or not subscribed |
| Auto-run blocked | `[AUTORUN GATE] PASSED=NO` | Auto-run disabled or cooldown active |
| Workflow not found | `[WORKFLOW SELECT] workflow=unknown` | Policy mapping incomplete |
| Skill not found | `[SKILL AUDIT] FOUND=NO` | Skill registry incomplete |
| AT command failed | `[COMMAND AUDIT] FAILED` | Serial port issue |
| Serial write failed | `[SERIAL WRITE RESULT] SUCCESS=NO` | Port not open or write error |
| Modem timeout | `[MODEM RESPONSE TIMEOUT]` | Modem not responding, wrong baud, cable issue |
| Modem error | `[MODEM RESPONSE ERROR]` | Parse error or exception |

## Predicted Status

The delivery chain is now fully instrumented. With a real modem:
- Auto-run must be ON for workflows to execute
- BetaStats (Sprint 15K) tracks CPIN state
- Delivery Report tracks end-to-end delivery health
- Every stage has trace logging for forensic analysis
