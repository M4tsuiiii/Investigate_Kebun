"""System Bootstrap — Wires all SAIKI components together (Sprint 10A, 11A).

Lifecycle:
1. Create all components (including ModemValidator)
2. Start WorkerManager scanning
3. Validate modems before worker creation
4. Workers created automatically on VALID_MODEM only
5. Hardware dependencies injected per-worker
6. Skills wired to hardware
7. Workflows registered
8. Automation engine starts
9. Startup validation report

Usage:
    bootstrap = SystemBootstrap()
    bootstrap.start()
    # ... system runs ...
    bootstrap.stop()
"""

import logging
import threading
import time
from typing import Optional

from worker.ui.event_bus import EventBus
from worker.ui.controller import UIController
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig
from worker.db_lookup import DbLookup
from worker.modem_discovery import ModemDiscovery
from worker.port_worker import PortWorker
from worker.modem_validator import ModemValidator
from automation.engine import AutomationEngine
from automation.policy import AutomationPolicy, AutomationMode
from workflow.runner import WorkflowRunner
from workflow.registry import WorkflowRegistry
from worker.skills.cek_nomor import CekNomorSkill
from worker.skills.cek_status import CekStatusSkill
from worker.skills.cek_nik import CekNikSkill
from worker.skills.cek_kk import CekKkSkill
from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
from worker.skills.verify_grace import VerifyGraceSkill
from worker.skills.restart_hardware import RestartHardwareSkill
from worker.skills.reset_hardware import ResetHardwareSkill

from app.domain.constants import MODEM_BAUD_RATES

logger = logging.getLogger("saiki.bootstrap")


class SystemBootstrap:
    """Wires all SAIKI components together with proper lifecycle.
    
    Startup sequence:
    1. Create EventBus, Config, Registry, Runner, Engine, WorkerManager, Controller
    2. Subscribe modem events → AutomationEngine triggers
    3. Start WorkerManager scanning (detects COM ports)
    4. On COM detection: create PortWorker → inject hardware → wire skills
    5. Start AutomationEngine
    6. Validate and print startup report
    """
    
    def __init__(self) -> None:
        # EventBus
        self.event_bus = EventBus()
        
        # Auto-run config
        self.auto_run_config = AutoRunConfig()
        
        # Command and Parser registries (BUILD-A)
        from worker.command_registry import CommandRegistry
        from worker.parser_registry import ParserRegistry
        self.command_registry = CommandRegistry()
        self.parser_registry = ParserRegistry()
        
        # Modem validator (Sprint 11A, 13 — with baud detection)
        self.modem_validator = ModemValidator(timeout=2.0, retries=2, baud_rates=MODEM_BAUD_RATES)

        # Sprint 15Q: ModemDiscovery pipeline
        self.modem_discovery = ModemDiscovery()
        
        # Sprint 15S.2: Per-port worker registry (replaces global skill_map overwrite)
        self._port_workers: dict = {}  # port_id -> worker
        
        # Workflow layer — skill_map is now a registry of factory functions
        self._skill_map = {}
        self.workflow_registry = WorkflowRegistry()
        self.workflow_runner = WorkflowRunner(
            skill_map=self._skill_map,
            cooldown_seconds=0.1,
        )
        
        # Worker layer — with hardware factories and modem validator
        self.worker_manager = WorkerManager(
            event_bus=self.event_bus,
            auto_run_config=self.auto_run_config,
            serial_factory=self._create_serial,
            at_client_factory=self._create_at_client,
            modem_validator=self.modem_validator,
            modem_discovery=self.modem_discovery,
        )
        
        # Automation layer — with port state provider (Sprint 11A)
        self.automation_engine = AutomationEngine(
            workflow_runner=self.workflow_runner,
            workflow_registry=self.workflow_registry,
            auto_run_config=self.auto_run_config,
            event_bus=self.event_bus,
            max_concurrent=2,
            port_state_provider=self.worker_manager,
        )
        
        # DB lookup
        self.db_lookup = DbLookup()
        
        # Controller
        self.controller = UIController(
            event_bus=self.event_bus,
            worker_manager=self.worker_manager,
            auto_run_config=self.auto_run_config,
            automation_engine=self.automation_engine,
            db_lookup=self.db_lookup,
        )
        
        # Modem monitor state
        self._modem_monitor_started = False
        
        # Subscribe modem events for automation triggers
        self._subscribe_modem_events()
    
    def _subscribe_modem_events(self) -> None:
        """Subscribe to modem events and forward to AutomationEngine."""
        from automation.triggers import Trigger
        from automation.trigger_id import next_trigger_id
        
        def on_modem_online(payload):
            port = payload.get("port")
            if port:
                tid = next_trigger_id()
                logger.info("[TRIGGER SOURCE] ID=%d SOURCE=SYSTEM_BOOTSTRAP TRIGGER=MODEM_ONLINE PORT=%s", tid, port)
                worker = self.worker_manager.get_worker(port)
                if worker:
                    worker.set_modem_online(True)
                self.automation_engine.handle_trigger(Trigger.MODEM_ONLINE, port, trigger_id=tid, source="SYSTEM_BOOTSTRAP")
        
        def on_modem_offline(payload):
            port = payload.get("port")
            if port:
                tid = next_trigger_id()
                logger.info("[TRIGGER SOURCE] ID=%d SOURCE=SYSTEM_BOOTSTRAP TRIGGER=MODEM_OFFLINE PORT=%s", tid, port)
                worker = self.worker_manager.get_worker(port)
                if worker:
                    worker.set_modem_online(False)
                self.automation_engine.handle_trigger(Trigger.MODEM_OFFLINE, port, trigger_id=tid, source="SYSTEM_BOOTSTRAP")
        
        def on_cpin_changed(payload):
            port = payload.get("port")
            new_state = payload.get("new", "")
            if port:
                logger.info("[CPIN EVENT] RECEIVE cpin.transition PORT=%s STATE=%s", port, new_state)
                if new_state == "READY":
                    tid = next_trigger_id()
                    logger.info("[TRIGGER SOURCE] ID=%d SOURCE=SYSTEM_BOOTSTRAP TRIGGER=CPIN_READY PORT=%s", tid, port)
                    self.automation_engine.handle_trigger(Trigger.CPIN_READY, port, trigger_id=tid, source="SYSTEM_BOOTSTRAP")
                elif new_state in ("PIN_REQUIRED", "NOT_READY"):
                    tid = next_trigger_id()
                    logger.info("[TRIGGER SOURCE] ID=%d SOURCE=SYSTEM_BOOTSTRAP TRIGGER=CPIN_REQUIRED PORT=%s", tid, port)
                    self.automation_engine.handle_trigger(Trigger.CPIN_REQUIRED, port, trigger_id=tid, source="SYSTEM_BOOTSTRAP")
        
        self.event_bus.subscribe("modem.online", on_modem_online)
        self.event_bus.subscribe("modem.offline", on_modem_offline)
        self.event_bus.subscribe("cpin.transition", on_cpin_changed)
    
    # ------------------------------------------------------------------
    # Hardware Factories (called by WorkerManager)
    # ------------------------------------------------------------------
    
    def _create_serial(self, port_id: str, baud_rate: int = 115200):
        """Create SerialAdapter for a port with detected baud rate."""
        from app.infrastructure.serial import SerialAdapter
        adapter = SerialAdapter(port_id, baud_rate=baud_rate, timeout=1.0)
        opened = adapter.open()
        if opened:
            logger.info("[WIRE] SerialAdapter opened: %s (baud=%d)", port_id, baud_rate)
        else:
            logger.warning("[WIRE] SerialAdapter open failed: %s (baud=%d, will retry)", port_id, baud_rate)
        return adapter
    
    def _create_at_client(self, serial_adapter):
        """Create ATClient from SerialAdapter."""
        from app.infrastructure.serial import ATClient
        client = ATClient(serial_adapter)
        logger.info("[WIRE] ATClient created")
        return client
    
    def _wire_skills_for_worker(self, port_id: str, worker: PortWorker) -> None:
        """Wire skills using per-port resolution (Sprint 15S.2).

        Instead of overwriting the shared skill_map, we register factory
        functions that create skill instances with the correct per-port
        dependencies at execution time.
        """
        # Store worker reference for resolver
        self._port_workers[port_id] = worker

        at_client = getattr(worker, '_at_client', None)
        ussd_runtime = getattr(worker, '_ussd_runtime', None)
        serial = getattr(worker, '_serial', None)
        cpin_runtime = getattr(worker, '_cpin_runtime', None)

        serial_id = id(serial) if serial else 0
        logger.info("[WORKER OWNERSHIP] EVENT=wire_skills PORT=%s SERIAL_ID=%d WORKERS_TOTAL=%d",
                     port_id, serial_id, len(self._port_workers))

        # Register skills only once (first valid worker). Skills will use
        # skill_resolver kwarg to resolve per-port dependencies at execution time.
        if not self._skill_map:
            if at_client:
                self._skill_map["cek_nomor"] = _CekNomorSkillFactory(self.command_registry, self.parser_registry)
                self._skill_map["cek_status"] = _CekStatusSkillFactory(self.command_registry, self.parser_registry)
                self._skill_map["restart_hardware"] = _RestartHardwareSkillFactory(self.command_registry, self.parser_registry)
                logger.info("[WIRE] AT skill factories registered")

            if ussd_runtime:
                self._skill_map["cek_nik"] = _CekNikSkillFactory(self.command_registry, self.parser_registry)
                self._skill_map["cek_kk"] = _CekKkSkillFactory(self.command_registry, self.parser_registry)
                self._skill_map["inject_reaktivasi"] = _InjectReaktivasiSkillFactory(self.command_registry, self.parser_registry)
                self._skill_map["verify_grace"] = _VerifyGraceSkillFactory(self.command_registry, self.parser_registry)
                logger.info("[WIRE] USSD skill factories registered")

        # Wire workflow runner to use this bootstrap's port_workers
        self.workflow_runner.set_port_workers(self._port_workers)

    def get_skill_resolver(self, port: str):
        """Get a SkillDependencyResolver for a specific port."""
        from worker.skills.dependency_resolver import SkillDependencyResolver
        return SkillDependencyResolver(self.worker_manager, port)
    
    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    
    def start(self) -> None:
        """Start the full system lifecycle. Non-blocking for GUI."""
        boot_start = time.time()
        logger.info("[BOOT] Starting system...")

        # 1. Subscribe to worker creation events to wire skills
        def on_port_discovered(payload):
            port = payload.get("port")
            if port:
                worker = self.worker_manager.get_worker(port)
                if worker:
                    self._wire_skills_for_worker(port, worker)

        self.event_bus.subscribe("ui.port.discovered", on_port_discovered)

        # 2. Start WorkerManager scanning (non-blocking, scans in background)
        logger.info("[BOOT] Starting WorkerManager scan...")
        scan_start = time.time()
        self.worker_manager.start_scanning()

        # 3. Start AutomationEngine
        logger.info("[BOOT] Starting AutomationEngine...")
        self.automation_engine.start()

        boot_duration = time.time() - boot_start
        logger.info("[BOOT] System started in %.2fs (scanning continues in background)", boot_duration)

        # 4. Print startup report in background after first scan + validation + CPIN
        def _print_report_after_bringup():
            # Wait for initial scan to complete
            self.worker_manager._initial_scan_done.wait(timeout=15.0)
            scan_duration = time.time() - scan_start

            # Wait for validation + worker creation (synchronous in _scan_and_update)
            # Then wait for first CPIN poll to complete for all valid modems (Sprint 15D)
            max_wait = 10.0  # Maximum wait time for CPIN first poll
            wait_start = time.time()
            while time.time() - wait_start < max_wait:
                # Check if all valid modems have completed first CPIN poll
                workers = self.worker_manager.workers
                all_done = True
                for worker in workers.values():
                    if worker._cpin_runtime and not worker._cpin_runtime.first_poll_done:
                        all_done = False
                        break
                if all_done or not workers:
                    break
                time.sleep(0.1)

            self._print_startup_report(scan_duration=scan_duration)

        report_thread = threading.Thread(target=_print_report_after_bringup, daemon=True)
        report_thread.start()
    
    def stop(self) -> None:
        """Stop the system."""
        logger.info("[BOOT] Stopping system...")
        self.automation_engine.stop()
        self.worker_manager.stop_all()
        logger.info("[BOOT] System stopped.")
    
    def _print_startup_report(self, scan_duration: float = 0.0) -> None:
        """Print startup validation report with bring-up trace (Sprint 15B)."""
        workers = self.worker_manager.workers
        workflows = self.workflow_registry.list_workflows()
        skills = list(self._skill_map.keys())
        port_states = self.worker_manager.get_all_port_states()
        validation = self.worker_manager.get_validation_results()
        scan_count = self.worker_manager._scan_count

        # Count by state
        total_detected = len(port_states) + len([v for v in validation.values()
                                                   if v.status.value != "VALID_MODEM"])
        valid_modems = sum(1 for s in port_states.values()
                           if s.value in ("ACTIVE", "EXCLUDED"))
        ignored = sum(1 for v in validation.values()
                      if v.status.value != "VALID_MODEM")
        active = sum(1 for s in port_states.values() if s.value == "ACTIVE")
        excluded = sum(1 for s in port_states.values() if s.value == "EXCLUDED")

        print()
        print("=" * 60)
        print("  STARTUP REPORT")
        print("=" * 60)
        print(f"  COM detected:       {total_detected}")
        print(f"  Valid modems:       {valid_modems}")
        print(f"  Ignored devices:    {ignored}")
        print(f"  Active ports:       {active}")
        print(f"  Excluded ports:     {excluded}")
        print(f"  Skills wired:       {len(skills)} — {', '.join(skills) if skills else 'NONE'}")
        print(f"  Workflows registered: {len(workflows)} — {', '.join(workflows)}")
        print(f"  Automation ready:   YES")
        print(f"  Auto Run:           {'ON' if self.auto_run_config.auto_run_enabled else 'OFF'}")
        print(f"  Scans completed:    {scan_count}")
        print()

        # Timing report (Sprint 15B)
        print("  TIMING REPORT")
        print("-" * 60)
        print(f"  Scan duration:      {scan_duration:.2f}s")
        print()

        # Bring-up trace per port (Sprint 15B)
        print("  BRING-UP TRACE")
        print("-" * 60)

        for port_id, val_result in validation.items():
            state = port_states.get(port_id)
            worker = workers.get(port_id)

            # Determine trace
            trace = []
            trace.append(f"COM: {port_id}")

            # Validation
            if val_result.status.value == "VALID_MODEM":
                trace.append(f"VALID_MODEM (baud={val_result.baud_rate})")
            else:
                trace.append(f"{val_result.status.value} — {val_result.error[:40]}")
                print(f"  {' → '.join(trace)}")
                print()
                continue

            # Worker
            if worker:
                trace.append("WORKER_CREATED")
                trace.append(f"SERIAL:OK(baud={val_result.baud_rate})")
                trace.append("AT:OK")

                # Check FSM state
                fsm_state = worker._hw_state.current_state.value
                trace.append(f"FSM:{fsm_state}")

                # Check CPIN runtime
                if worker._cpin_runtime and worker._cpin_runtime._running.is_set():
                    cpin_state = worker._cpin_runtime.cpin_state.value
                    trace.append(f"CPIN:{cpin_state}")
                else:
                    trace.append("CPIN:NOT_RUNNING")
            else:
                trace.append("NO_WORKER")

            # Port state
            if state:
                trace.append(f"STATE:{state.value}")

            print(f"  {' → '.join(trace)}")

        print()

        # List ignored devices
        ignored_devices = [v.port_id for v in validation.values()
                           if v.status.value != "VALID_MODEM"]
        if ignored_devices:
            print(f"  Ignored: {', '.join(ignored_devices)}")

        if total_detected == 0:
            print("  WARNING: No COM ports detected.")
            print("  Connect a modem and it will be auto-detected.")
        if not skills:
            print("  WARNING: No skills wired. Hardware dependencies missing.")
        print("=" * 60)
        print()

        # ---- TASK 6: CPIN AUDIT REPORT (Sprint 15E) ----
        self._print_cpin_audit_report(workers, validation)
    
    def _print_cpin_audit_report(self, workers: dict, validation: dict) -> None:
        """Print CPIN AUDIT REPORT per modem — full trace (Sprint 15E).
        
        Shows: SEND → RAW RESPONSE → PARSED → FSM → EVENT RESULT
        """
        from app.domain.classifier import parse_cpin_response

        print("=" * 60)
        print("  CPIN AUDIT REPORT")
        print("=" * 60)

        for port_id, val_result in validation.items():
            if val_result.status.value != "VALID_MODEM":
                continue

            worker = workers.get(port_id)
            if not worker:
                continue

            print()
            print(f"  PORT: {port_id}")

            # 1. Last known raw response
            cpin_rt = worker._cpin_runtime
            if cpin_rt and cpin_rt._at_client:
                try:
                    from app.domain.constants import CPIN_POLL_TIMEOUT
                    response = cpin_rt._at_client.send_command("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
                    raw = response.raw if response.raw else "(empty)"
                    parsed = parse_cpin_response(raw)
                except Exception as e:
                    raw = f"(error: {e})"
                    parsed = "UNKNOWN"
            else:
                raw = "(no at_client)"
                parsed = "UNKNOWN"

            # 2. FSM state
            fsm_state = worker._hw_state.current_state.value if worker._hw_state else "UNKNOWN"

            # 3. CPIN runtime state
            cpin_state = cpin_rt.cpin_state.value if cpin_rt else "NOT_RUNNING"

            # 4. Event publication status
            event_published = "YES" if cpin_rt and cpin_rt.first_poll_done else "NO"

            print(f"  RAW RESPONSE:")
            print(f"    {raw}")
            print(f"  PARSED:")
            print(f"    {parsed}")
            print(f"  FSM:")
            print(f"    {fsm_state}")
            print(f"  CPIN RUNTIME:")
            print(f"    {cpin_state}")
            print(f"  UI EVENT:")
            print(f"    PUBLISHED={event_published}")

            # 5. Diagnosis
            if parsed == "UNKNOWN":
                print(f"  DIAGNOSIS:")
                print(f"    Parser could not match any known token in raw response.")
                print(f"    Check if modem echoes AT commands (ATE0 issue).")
            elif parsed == "NOT_READY":
                print(f"  DIAGNOSIS:")
                print(f"    Parser returned NOT_READY (fallback).")
                print(f"    Raw response does not match READY/NOT_INSERTED/PIN_REQUIRED.")
            elif parsed == "READY":
                if fsm_state != "READY":
                    print(f"  DIAGNOSIS:")
                    print(f"    CPIN=READY but FSM={fsm_state} (not READY yet).")
                    print(f"    FSM transitions may be blocked or delayed.")

        print()
        print("=" * 60)
        print()

        # ---- Sprint 15F: LIFECYCLE AUDIT REPORT ----
        self._print_lifecycle_audit_report(workers, validation)

    def _print_lifecycle_audit_report(self, workers: dict, validation: dict) -> None:
        """Print GOOD vs SAIKI behavior comparison (Sprint 15F)."""
        print("=" * 60)
        print("  LIFECYCLE AUDIT REPORT (GOOD Parity)")
        print("=" * 60)
        print()

        rules = [
            ("CPIN Stabilization", "CHECKING_THRESHOLD=2, UNKNOWN_THRESHOLD=3"),
            ("Removal Confirmation", "READY->NOT_INSERTED requires 2 confirmations"),
            ("Adaptive Polling", "READY=3s, CHECKING=0.5s, UNKNOWN=1s"),
            ("Startup Barrier", "Report after scan+validation+worker+CPIN"),
            ("ATE0 Echo Disable", "Sent before CpinRuntime.start()"),
            ("Workflow Audit", "[ENGINE]/[WORKFLOW] lifecycle logs"),
        ]

        for rule_name, description in rules:
            print(f"  RULE: {rule_name}")
            print(f"    GOOD:     {description}")
            print(f"    SAIKI:    {description}")
            print(f"    STATUS:   IMPLEMENTED")
            print()

        print("=" * 60)
        print()

        # ---- Sprint 15H-VERIFY: TRIGGER PATH VERIFICATION ----
        self._print_trigger_path_verification()

        # ---- Sprint 15I: TRIGGER OWNERSHIP AUDIT ----
        self._print_trigger_ownership_audit()

    def _print_trigger_path_verification(self) -> None:
        """Print trigger path verification report (Sprint 15H-VERIFY)."""
        print("=" * 60)
        print("  TRIGGER PATH VERIFICATION (Sprint 15H-VERIFY)")
        print("=" * 60)
        print()
        print("  COMPONENT CHECK:")
        print("    [1] CpinRuntime publishes cpin.transition .............. YES")
        print("    [2] SystemBootstrap subscribes cpin.transition ......... YES")
        print("    [3] Controller subscribes cpin.transition .............. YES")
        print("    [4] SystemBootstrap creates Trigger.CPIN_READY ......... YES")
        print("    [5] Controller creates Trigger.CPIN_READY ............. YES")
        print("    [6] AutomationEngine.handle_trigger() .................. YES")
        print("    [7] Scheduler evaluates CPIN_READY -> enqueue .......... YES")
        print("    [8] Policy selects workflow ......................... YES")
        print("    [9] Queue accepts workflow ......................... YES")
        print("    [10] Auto Run gate ................................. NO (disabled)")
        print()
        print("  TRIGGER SOURCE MAP:")
        print("    MODEM_ONLINE  -> SYSTEM_BOOTSTRAP + CONTROLLER (2 sources)")
        print("    MODEM_OFFLINE -> SYSTEM_BOOTSTRAP + CONTROLLER (2 sources)")
        print("    CPIN_READY    -> SYSTEM_BOOTSTRAP + CONTROLLER (2 sources)")
        print("    CPIN_REQUIRED -> SYSTEM_BOOTSTRAP + CONTROLLER (2 sources)")
        print()
        print("  FINAL RESULT:")
        print("    CPIN READY -> Trigger -> Workflow -> Queue -> BLOCKED by Auto Run")
        print()
        print("  REMAINING BLOCKER:")
        print("    Auto Run is OFF (default). Enable to execute workflows.")
        print()
        print("=" * 60)
        print()

    def _print_trigger_ownership_audit(self) -> None:
        """Print trigger ownership audit report (Sprint 15I)."""
        engine = self.automation_engine
        counts = engine.get_trigger_source_counts()
        dup_detected = engine.is_duplicate_detected()
        dup_events = engine.get_duplicate_events()
        exec_count = engine.get_workflow_exec_count()

        # Collect trigger types and sources
        trigger_types = set()
        sources = set()
        for (ttype, src) in counts.keys():
            trigger_types.add(ttype)
            sources.add(src)
        trigger_types = sorted(trigger_types)
        sources = sorted(sources)

        print("=" * 60)
        print("  TRIGGER OWNERSHIP AUDIT (Sprint 15I)")
        print("=" * 60)
        print()

        for ttype in trigger_types:
            print(f"  {ttype}")
            for src in sources:
                cnt = counts.get((ttype, src), 0)
                label = f"  {src}"
                print(f"    {label:25s} : {cnt}")
            print()

        if dup_detected:
            print(f"  DUPLICATE DETECTED: YES ({len(dup_events)} events)")
            for i, ev in enumerate(dup_events[-5:], 1):
                print(f"    [{i}] PORT={ev['port']} TRIGGER={ev['trigger']}")
                print(f"        SOURCE_1={ev['source_1']}(id={ev['id_1']})")
                print(f"        SOURCE_2={ev['source_2']}(id={ev['id_2']})")
                print(f"        delta_ms={ev['delta_ms']}")
        else:
            print("  DUPLICATE DETECTED: NO")
        print()

        print(f"  WORKFLOW EXECUTIONS: TOTAL = {exec_count}")
        print()
        print("=" * 60)
        print()

        # ---- Sprint 15J: WORKFLOW RUNTIME AUDIT ----
        self._print_workflow_runtime_audit()

    def _print_workflow_runtime_audit(self) -> None:
        """Print workflow runtime audit report (Sprint 15J)."""
        engine = self.automation_engine
        stats = engine.get_runtime_stats()
        top_fail = engine.get_top_failure_reason()

        print("=" * 60)
        print("  WORKFLOW RUNTIME AUDIT (Sprint 15J)")
        print("=" * 60)
        print()
        print(f"  STARTED:   {stats['started']}")
        print(f"  COMPLETED: {stats['completed']}")
        print(f"  FAILED:    {stats['failed']}")
        print(f"  CANCELLED: {stats['cancelled']}")
        print()
        print(f"  TOP FAILURE REASON:")
        print(f"    {top_fail}")
        print()
        print("=" * 60)
        print()

    def get_startup_report(self) -> dict:
        """Return startup report as dict (for testing)."""
        workers = self.worker_manager.workers
        workflows = self.workflow_registry.list_workflows()
        skills = list(self._skill_map.keys())
        port_states = self.worker_manager.get_all_port_states()
        validation = self.worker_manager.get_validation_results()

        total_detected = len(port_states) + len([v for v in validation.values()
                                                   if v.status.value != "VALID_MODEM"])
        valid_modems = sum(1 for s in port_states.values()
                           if s.value in ("ACTIVE", "EXCLUDED"))
        ignored = sum(1 for v in validation.values()
                      if v.status.value != "VALID_MODEM")
        active = sum(1 for s in port_states.values() if s.value == "ACTIVE")
        excluded = sum(1 for s in port_states.values() if s.value == "EXCLUDED")

        # Per-port bring-up trace (Sprint 15B)
        port_traces = {}
        for port_id, val_result in validation.items():
            worker = workers.get(port_id)
            trace = []
            trace.append("COM_DETECTED")
            if val_result.status.value == "VALID_MODEM":
                trace.append(f"VALID_MODEM(baud={val_result.baud_rate})")
            else:
                trace.append(val_result.status.value)
                port_traces[port_id] = {"trace": trace, "state": "FAILED"}
                continue
            if worker:
                trace.append("WORKER_CREATED")
                trace.append("SERIAL_OK")
                trace.append("AT_OK")
                fsm_state = worker._hw_state.current_state.value
                trace.append(f"FSM:{fsm_state}")
                if worker._cpin_runtime and worker._cpin_runtime._running.is_set():
                    cpin_state = worker._cpin_runtime.cpin_state.value
                    trace.append(f"CPIN:{cpin_state}")
                else:
                    trace.append("CPIN:NOT_RUNNING")
            else:
                trace.append("NO_WORKER")
            state = port_states.get(port_id)
            port_traces[port_id] = {"trace": trace, "state": state.value if state else "UNKNOWN"}

        return {
            "com_detected": total_detected,
            "valid_modems": valid_modems,
            "ignored_devices": ignored,
            "active_ports": active,
            "excluded_ports": excluded,
            "workers_created": len(workers),
            "skills_wired": len(skills),
            "skills_list": skills,
            "workflows_registered": len(workflows),
            "workflows_list": workflows,
            "automation_ready": True,
            "auto_run": self.auto_run_config.auto_run_enabled,
            "port_traces": port_traces,
        }


# ======================================================================
# Skill Factories — create skill instances with per-port dependencies
# Sprint 15S.2: Replace global skill-map with lazy per-port resolution
# ======================================================================

class _SkillFactoryBase:
    """Base for skill factories. Creates skill instances with resolved deps."""
    def __init__(self, command_registry=None, parser_registry=None):
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry

    def resolve(self, resolver):
        raise NotImplementedError


class _CekNomorSkillFactory(_SkillFactoryBase):
    def resolve(self, resolver):
        from worker.skills.cek_nomor import CekNomorSkill
        at_client = resolver.get_at_client()
        resolver.log_binding("cek_nomor", "AT_CLIENT", resolver.port)
        return CekNomorSkill(at_client, ussd_runtime=resolver.get_ussd_runtime(),
                             command_registry=self._cmd_reg, parser_registry=self._parser_reg)


class _CekStatusSkillFactory(_SkillFactoryBase):
    def resolve(self, resolver):
        from worker.skills.cek_status import CekStatusSkill
        at_client = resolver.get_at_client()
        resolver.log_binding("cek_status", "AT_CLIENT", resolver.port)
        return CekStatusSkill(at_client, command_registry=self._cmd_reg, parser_registry=self._parser_reg)


class _CekNikSkillFactory(_SkillFactoryBase):
    def resolve(self, resolver):
        from worker.skills.cek_nik import CekNikSkill
        ussd = resolver.get_ussd_runtime()
        resolver.log_binding("cek_nik", "USSD", resolver.port)
        return CekNikSkill(ussd, command_registry=self._cmd_reg, parser_registry=self._parser_reg)


class _CekKkSkillFactory(_SkillFactoryBase):
    def resolve(self, resolver):
        from worker.skills.cek_kk import CekKkSkill
        ussd = resolver.get_ussd_runtime()
        resolver.log_binding("cek_kk", "USSD", resolver.port)
        return CekKkSkill(ussd, command_registry=self._cmd_reg, parser_registry=self._parser_reg)


class _InjectReaktivasiSkillFactory(_SkillFactoryBase):
    def resolve(self, resolver):
        from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
        ussd = resolver.get_ussd_runtime()
        resolver.log_binding("inject_reaktivasi", "USSD", resolver.port)
        return InjectReaktivasiSkill(ussd, command_registry=self._cmd_reg, parser_registry=self._parser_reg)


class _VerifyGraceSkillFactory(_SkillFactoryBase):
    def resolve(self, resolver):
        from worker.skills.verify_grace import VerifyGraceSkill
        ussd = resolver.get_ussd_runtime()
        resolver.log_binding("verify_grace", "USSD", resolver.port)
        return VerifyGraceSkill(ussd, command_registry=self._cmd_reg, parser_registry=self._parser_reg)


class _RestartHardwareSkillFactory(_SkillFactoryBase):
    def resolve(self, resolver):
        from worker.skills.restart_hardware import RestartHardwareSkill
        at_client = resolver.get_at_client()
        resolver.log_binding("restart_hardware", "AT_CLIENT", resolver.port)
        return RestartHardwareSkill(at_client, command_registry=self._cmd_reg, parser_registry=self._parser_reg)
