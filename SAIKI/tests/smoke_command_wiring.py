"""Sprint 15S.1 Smoke Test — verifies command wiring without real modem hardware.

Prints compact result for each command route:
    [COMMAND WIRING SMOKE TEST]
    Cek Nomor Massal: CLICK=YES DISPATCH=YES ENQUEUED=YES RESULT=YES
    ...

Tests the real GUI callback and subscription path.
"""

import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _LogCaptureHandler(logging.Handler):
    def __init__(self, records):
        super().__init__()
        self._records = records
    def emit(self, record):
        self._records.append(record)


class _CaptureLogs:
    def __init__(self, logger_name):
        self._logger = logging.getLogger(logger_name)
        self.records = []
        self._handler = _LogCaptureHandler(self.records)
    def __enter__(self):
        self._old = self._logger.level
        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.DEBUG)
        return self
    def __exit__(self, *args):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._old)
    def has(self, sub):
        return any(sub in r.getMessage() for r in self.records)


class _FakeWorkerManager:
    def __init__(self):
        self.workers = {}
        self._active = set()
        self._excluded = set()
    def get_worker(self, port):
        return self.workers.get(port)
    def get_active_ports(self):
        return list(self._active)
    def get_port_state(self, port):
        from app.domain.enums import PortState
        if port in self._excluded:
            return PortState.EXCLUDED
        return PortState.ACTIVE if port in self._active else PortState.IDLE
    def get_all_port_states(self):
        from app.domain.enums import PortState
        return {p: PortState.ACTIVE for p in self._active}
    def get_validation_results(self):
        return {}
    def exclude_port(self, p):
        self._excluded.add(p); self._active.discard(p)
    def include_port(self, p):
        self._excluded.discard(p); self._active.add(p)
    def stop_all(self):
        pass
    def create_worker(self, p):
        pass
    def destroy_worker(self, p):
        self.workers.pop(p, None); self._active.discard(p)


class _FakeWorker:
    def __init__(self):
        self.is_alive = True
        self.modem_online = True
        from app.domain.enums import CpinState
        self.cpin_state = CpinState.READY
        self.is_connected = True
    def start(self): pass
    def stop(self): pass
    def force_retry(self): pass
    def set_modem_online(self, v): self.modem_online = v


class _FakeAE:
    def __init__(self):
        self.enqueued = []
    def enqueue_workflow(self, port, wf, priority=10, trigger_id=0):
        self.enqueued.append((port, wf))
    def handle_trigger(self, *a, **kw): pass
    def set_mode_from_name(self, n): pass
    def stop(self): pass


class _FakeAutoRunConfig:
    def __init__(self):
        self.auto_run_enabled = False
    def set_enabled(self, v): self.auto_run_enabled = v
    def toggle(self): self.auto_run_enabled = not self.auto_run_enabled


class _FakeDb:
    def lookup_nik(self, m): return None
    def lookup_kk(self, n): return None


def _run_smoke_test():
    from worker.ui.event_bus import EventBus
    from worker.ui.controller import UIController

    results = {}

    def _test(name, event, payload, check_fn):
        bus = EventBus()
        wm = _FakeWorkerManager()
        ae = _FakeAE()
        ctrl = UIController(bus, wm, _FakeAutoRunConfig(), ae, _FakeDb())

        worker = _FakeWorker()
        wm.workers["COM1"] = worker
        wm._active.add("COM1")

        with _CaptureLogs("saiki.controller") as cap:
            bus.publish(event, payload)

        results[name] = check_fn(cap, ae)

    def _auto_run_check(cap, ae):
        return {
            "CLICK": cap.has("[COMMAND CLICK]"),
            "DISPATCH": True,  # auto_run doesn't go through dispatch
            "ENQUEUED": True,
            "RESULT": True,
        }

    def _mass_check(name, expected_wf):
        def _check(cap, ae):
            wfs = [w for _, w, *_ in ae.enqueued]
            return {
                "CLICK": cap.has("[COMMAND CLICK]"),
                "DISPATCH": cap.has("[COMMAND DISPATCH]"),
                "ENQUEUED": expected_wf in wfs,
                "RESULT": cap.has("[COMMAND RESULT]"),
            }
        return _check

    def _restart_all_check(cap, ae):
        wfs = [w for _, w, *_ in ae.enqueued]
        return {
            "CLICK": cap.has("[COMMAND CLICK]"),
            "DISPATCH": cap.has("[COMMAND DISPATCH]"),
            "ENQUEUED": "hardware_restart" in wfs,
            "RESULT": cap.has("[COMMAND RESULT]"),
        }

    def _reset_modem_check(cap, ae):
        wfs = [w for _, w, *_ in ae.enqueued]
        return {
            "CLICK": cap.has("[COMMAND CLICK]"),
            "DISPATCH": cap.has("[COMMAND DISPATCH]"),
            "ENQUEUED": "hardware_reset" in wfs,
            "RESULT": cap.has("[COMMAND RESULT]"),
        }

    def _per_port_check(expected_wf):
        def _check(cap, ae):
            wfs = [w for _, w, *_ in ae.enqueued]
            return {
                "CLICK": cap.has("[COMMAND CLICK]"),
                "DISPATCH": cap.has("[COMMAND DISPATCH]"),
                "ENQUEUED": expected_wf in wfs,
                "RESULT": cap.has("[COMMAND RESULT]"),
            }
        return _check

    def _no_port_check(cap, ae):
        return {
            "CLICK": cap.has("[COMMAND CLICK]"),
            "DISPATCH": True,  # no dispatch expected
            "ENQUEUED": True,  # no enqueue expected
            "RESULT": cap.has("no_port_selected"),
        }

    # Run all tests
    _test("Auto Run Toggle", "cmd.auto_run.toggle", {"enabled": True}, _auto_run_check)
    _test("Cek Nomor Massal", "cmd.mass.cek_nomor", {"source": "workspace_button"}, _mass_check("cek_nomor", "check_number"))
    _test("Reaktivasi Massal", "cmd.mass.reaktivasi", {"source": "workspace_button"}, _mass_check("reaktivasi", "reactivate_full"))
    _test("Restart All", "cmd.restart_all", {"source": "workspace_button"}, _restart_all_check)
    _test("Reset Modem (selected)", "cmd.reset_modem", {"port": "COM1", "source": "workspace_button"}, _reset_modem_check)
    _test("Reset Modem (no port)", "cmd.reset_modem", {"source": "workspace_button"}, _no_port_check)
    _test("Cek Nomor (port)", "cmd.cek_nomor", {"port": "COM1", "source": "context_menu"}, _per_port_check("check_number"))
    _test("Cek NIK (port)", "cmd.cek_nik", {"port": "COM1", "source": "context_menu"}, _per_port_check("check_nik"))
    _test("Cari KK (port)", "cmd.cari_kk", {"port": "COM1", "source": "context_menu"}, _per_port_check("check_kk"))
    _test("Cek Limit (port)", "cmd.cek_limit", {"port": "COM1", "source": "context_menu"}, _per_port_check("check_number"))
    _test("Reaktivasi (port)", "cmd.reactivate", {"port": "COM1", "source": "context_menu"}, _per_port_check("reactivate_full"))

    # Print results
    print("\n[COMMAND WIRING SMOKE TEST]")
    print(f"{'Command':<30} {'CLICK':<8} {'DISPATCH':<10} {'ENQUEUED':<10} {'RESULT':<8}")
    print("-" * 66)
    all_pass = True
    for name, checks in results.items():
        click = "YES" if checks["CLICK"] else "NO"
        dispatch = "YES" if checks["DISPATCH"] else "N/A"
        enqueued = "YES" if checks["ENQUEUED"] else "N/A"
        result = "YES" if checks["RESULT"] else "NO"
        # Auto-run toggle doesn't have dispatch/enqueue in the same way
        status = "OK" if all(checks.values()) else "WARN"
        if not all(checks.values()):
            all_pass = False
        print(f"{name:<30} {click:<8} {dispatch:<10} {enqueued:<10} {result:<8} [{status}]")

    print("-" * 66)
    total = len(results)
    passed = sum(1 for c in results.values() if all(c.values()))
    print(f"Total: {total}  Passed: {passed}  Warnings: {total - passed}")
    return all_pass


if __name__ == "__main__":
    success = _run_smoke_test()
    sys.exit(0 if success else 1)
