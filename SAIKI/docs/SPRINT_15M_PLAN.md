# Sprint 15M: Real Hardware Beta Validation

## Objective
Run the SAIKI app with a real modem for 30+ minutes. Collect BetaStats + Delivery Report data. Prove end-to-end command delivery works.

## Prerequisites
1. Physical modem connected to a COM port (e.g., COM3)
2. SIM card inserted in modem
3. SAIIKI app can detect the modem

## How to Run

### Step 1: Enable Auto-Run
Auto-run is OFF by default. You must enable it before starting:

**Option A: Via GUI**
- Open the app
- Go to Settings → Auto-Run → Enable

**Option B: Via Script**
```bash
cd SAIKI
python -m beta_test
```

### Step 2: Run the Beta Test Script
```bash
cd SAIKI
python -m beta_test --duration 1800 --port COM3
```

Arguments:
- `--duration`: Test duration in seconds (default: 1800 = 30 min)
- `--port`: COM port (default: auto-detect)
- `--output`: Log file path (default: beta_test_log.txt)

### Step 3: Monitor Output
The script will print:
- `[BETA TEST] Starting...`
- `[BETA TEST] Duration: 1800s (30.0 min)`
- `[BETA TEST] Port: COM3`
- `[BETA TEST] Elapsed: 60s (remaining: 1740s)`
- `[BETA TEST] Triggers received: 5`
- `[BETA TEST] Workflows started: 3`
- ...
- `[BETA TEST] COMPLETE`
- `[DELIVERY REPORT]`
- `[BETA STATS]`

### Step 4: Analyze Results
After the test completes, check:
1. `beta_test_log.txt` — full log output
2. Console output — Delivery Report + BetaStats

## Expected Output (Good Case)

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

BetaStats:
  cpin_checks: 15
  cpin_ready: 12
  cpin_transitions: 3
  state_flips: 2
  stabilization_events: 1
  average_cpin_time: 1.23s
```

## What We're Looking For

### Success Criteria
1. [ ] Modem detected on startup
2. [ ] CPIN transitions from UNKNOWN → READY
3. [ ] Triggers received (cpin.transition or modem.online)
4. [ ] Workflows started
5. [ ] AT commands sent (COMMAND AUDIT logs)
6. [ ] Serial writes succeeded (SERIAL WRITE RESULT SUCCESS=YES)
7. [ ] Modem responses received (MODEM RESPONSE RAW=...)
8. [ ] Workflows completed
9. [ ] Delivery Report shows non-zero completion count

### Failure Scenarios to Watch For

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| No triggers received | Event not subscribed | Check SystemBootstrap subscriptions |
| Auto-run blocked | Gate condition | Check should_block_auto_run() |
| Skill not found | Registry incomplete | Check skill_map in WorkflowRunner |
| Serial write failed | Port not open | Check port state |
| Modem timeout | Wrong baud/cable | Check 115200 baud, cable |
| CPIN never READY | SIM issue | Check SIM, PIN, network |

## Files Modified in This Sprint
- `docs/SPRINT_15M_PLAN.md` — this file
- `beta_test.py` — NEW: automated validation script

## Next Steps After 15M
1. If all success criteria pass → Sprint 15N (P2 rule transplant)
2. If failures found → diagnose, fix, re-run
