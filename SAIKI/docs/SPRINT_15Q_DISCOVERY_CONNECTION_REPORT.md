# Sprint 15Q — Modem Discovery & Connection Hardening

## Summary

Rebuilt the modem discovery and connection path to be reliable across Windows PCs with different COM numbering. Defaults to Quectel M26 baud rate 115200. Only starts a worker/CPIN runtime after a port is positively verified via AT → OK probe.

## Prior Scanner Weaknesses

1. **No metadata collection** — Enumerated ports but discarded description, manufacturer, VID, PID, HWID
2. **No candidate filtering** — Probed every COM port blindly (including printers, virtual ports)
3. **Multi-baud probing** — Tried 9600, 19200, 115200 — wasteful for Quectel M26 which defaults to 115200
4. **Synchronous validation** — Each port probed one-at-a-time (44 ports = 44 serial probes in sequence)
5. **No probe handle lifecycle tracking** — No explicit close guarantee on exception paths
6. **CPIN eligibility unclear** — No explicit guard against false-positive probes starting CPIN

## New Candidate → Probe → Verified-Worker Lifecycle

```
Stage 1: ENUMERATE
  serial.tools.list_ports.comports() → List[PortMetadata]
  Collects: PORT, DESCRIPTION, MANUFACTURER, VID, PID, HWID
  Trace: [DISCOVERY ENUMERATED] per port

Stage 2: FILTER
  Metadata match against: Quectel, XR21V1414, USB UART, USB Serial, AT Port, VID=2C7C
  Trace: [DISCOVERY CANDIDATE] / [DISCOVERY SKIPPED]

Stage 3: PROBE (bounded concurrency)
  Open temporary serial at 115200, send AT, require explicit OK
  Echoed AT without OK → rejected
  Trace: [DISCOVERY PROBE START] / [DISCOVERY PROBE RESULT]
  Always close probe handle (success, failure, exception)

Stage 4: VERIFIED HANDOFF
  Close probe handle → Create worker → Create worker-owned SerialAdapter
  Record baud as 115200 → Start CPIN only after connection succeeds
  Trace: [DISCOVERY VERIFIED] / [WORKER CONNECTED] / [CPIN START ELIGIBLE]

Rejection path:
  Trace: [DISCOVERY REJECTED] with reason (at_no_ok, no_response, exception)
```

## Concurrency Limit

| Parameter | Value |
|-----------|-------|
| `DISCOVERY_MAX_CONCURRENT` | 4 |
| Implementation | `ThreadPoolExecutor(max_workers=4)` |
| UI impact | Scan dispatch returns immediately |

## Valid Modem Criteria

A port is a valid modem when ALL are true:
1. Enumerated by Windows (`serial.tools.list_ports.comports()`)
2. Metadata matches candidate filter (Quectel, USB UART, etc.)
3. AT probe at 115200 receives explicit `OK` response
4. Worker connection succeeds
5. Worker-owned SerialAdapter is open

## CPIN Eligibility Proof

CPIN polling starts ONLY after:
1. Port enumerated by Windows ✓
2. AT probe passed with OK ✓
3. Worker created and connected ✓
4. Serial adapter open (`is_open` check in `PortWorker.connect()`) ✓

**Guard**: `PortWorker.connect()` checks `serial_adapter.is_open` before creating/starting `CpinRuntime`. If serial is not open, CPIN is not started and a warning is logged.

## Config Behavior

| Setting | Default | Location |
|---------|---------|----------|
| Default Baud Rate | 115200 | Config → Modem section |
| Fallback Baud Probing | OFF | Config → Modem checkbox |
| Detected Modems | {} | Config → Modem section (read-only display) |
| Baud in Home/Workspace | Not shown | Port table has no BAUD column |

## Files Changed

| File | Change |
|------|--------|
| `worker/modem_discovery.py` | **NEW** — ModemDiscovery pipeline: enumerate → filter → probe → verified |
| `app/domain/constants.py` | Added DISCOVERY_BAUD_RATE, DISCOVERY_PROBE_TIMEOUT, DISCOVERY_MAX_CONCURRENT, DISCOVERY_CANDIDATE_KEYWORDS |
| `worker/worker_manager.py` | Integrated ModemDiscovery, `_scan_with_discovery()` path, `[WORKER CONNECTED]`/`[CPIN START ELIGIBLE]` traces |
| `worker/system_bootstrap.py` | Wired ModemDiscovery into WorkerManager |
| `worker/port_worker.py` | CPIN eligibility guard: checks `serial_adapter.is_open` before starting CPIN |
| `worker/ui/settings_dialog.py` | Added default_baud_rate, fallback_baud_enabled, detected_modems fields |
| `tests/test_sprint15q_discovery.py` | **NEW** — 40 tests covering all 12 task categories |

## Test Results

| Metric | Count |
|--------|-------|
| Sprint 15Q tests | 40 |
| Sprint 15Q passed | 40 |
| Regression tests (15P+15Q+sprint) | 138 |
| Regression passed | 138 |

### Test Categories (12)
1. ✅ COM ports from Windows enumeration (incl. COM101, COM147)
2. ✅ No hard-coded COM range
3. ✅ 115200 as default probe baud
4. ✅ Echoed AT without OK is rejected
5. ✅ Response with OK is accepted
6. ✅ Failed probe → no worker/CPIN
7. ✅ Verified port → one worker-owned serial adapter
8. ✅ Probe handle closes on success/failure/exception
9. ✅ Probe concurrency capped at configured limit
10. ✅ Scan dispatch returns immediately (UI non-blocking)
11. ✅ Detected baud in Config only
12. ✅ Existing workflow/CPIN behavior compatible

## Real-Hardware Test Checklist

Using `main.py`:
1. ☐ Run Scan Modem
2. ☐ Confirm high-numbered COM ports can be enumerated
3. ☐ Confirm only `AT → OK` ports become connected workers
4. ☐ Confirm unrelated ports are skipped and never CPIN-polled
5. ☐ Confirm UI stays responsive during scan
6. ☐ Confirm Config shows each verified modem's detected baud as `115200`
7. ☐ Confirm Home/Workspace does not show baud details
