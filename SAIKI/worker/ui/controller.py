"""UIController — Bridges EventBus events to worker actions and Automation Engine (Sprint 9).

Sprint 15S.1: Centralized routing table, COMMAND ROUTER READY, COMMAND DELIVERY FAILED,
              workflow completion → COMMAND RESULT wiring, selected-port Reset Modem.
"""

import logging
import threading
from typing import Dict, Any, List, Tuple, Optional
from worker.ui.events import CommandEvent, UIEvent
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig
from worker.db_lookup import DbLookup
from automation.engine import AutomationEngine
from automation.triggers import Trigger

logger = logging.getLogger("saiki.controller")


# ======================================================================
# Centralized Command Routing Table (Sprint 15S.1 Task 6)
# ======================================================================

COMMAND_ROUTES = [
    # (event_name, command_name, workflow_or_action, scope, eligibility, ui_label)
    ("cmd.cek_nomor",       "cek_nomor",       "check_number",      "per_port", "sim_ready",  "Cek Nomor"),
    ("cmd.cek_status",      "cek_status",      "check_status",      "per_port", "sim_ready",  "Cek Status SIM"),
    ("cmd.cek_nik",         "cek_nik",         "check_nik",         "per_port", "sim_ready",  "Cek NIK"),
    ("cmd.cari_kk",         "cari_kk",         "check_kk",          "per_port", "sim_ready",  "Cari KK"),
    ("cmd.cek_limit",       "cek_limit",       "check_number",      "per_port", "sim_ready",  "Cek Limit"),
    ("cmd.reactivate",      "reaktivasi",      "reactivate_full",   "per_port", "sim_ready",  "Reaktivasi"),
    ("cmd.reset_modem",     "reset_modem",     "hardware_reset",    "per_port", "hw_ready",   "Reset Modem"),
    ("cmd.restart_port",    "restart_port",    "hardware_restart",  "per_port", "hw_ready",   "Restart Port"),
    ("cmd.force_retry",     "force_retry",     None,                "per_port", "worker_alive","Reprocess"),
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

ROUTE_BY_EVENT = {r[0]: r for r in COMMAND_ROUTES}

# Per-port command event → workflow (for _handle_port_command)
PER_PORT_COMMAND_MAP = {
    "cmd.cek_nomor":      "check_number",
    "cmd.cek_status":     "check_status",
    "cmd.cek_nik":        "check_nik",
    "cmd.cari_kk":        "check_kk",
    "cmd.cek_limit":      "check_number",
    "cmd.reactivate":     "reactivate_full",
    "cmd.reset_modem":    "hardware_reset",
    "cmd.restart_port":   "hardware_restart",
    "cmd.force_retry":    None,  # handled directly
}


class UIController:
    """Bridges EventBus events to WorkerManager and AutomationEngine.

    Responsibilities:
    - Receive command events from UI
    - Route port actions to WorkerManager
    - Route mass actions to AutomationEngine
    - Route per-port skill commands through AutomationEngine
    - Forward modem events to AutomationEngine as triggers
    - Forward automation events to UI for display
    - Manage global auto-run toggle (DD-014)
    - Handle database lookups
    - Handle port exclude/include (Sprint 11A/12)
    - Eligibility checks before enqueueing
    - Full delivery tracing: CLICK → DISPATCH → ENQUEUED → RESULT
    """

    def __init__(
        self,
        event_bus,
        worker_manager: WorkerManager,
        auto_run_config: AutoRunConfig,
        automation_engine: AutomationEngine,
        db_lookup: DbLookup,
    ):
        self._event_bus = event_bus
        self._worker_manager = worker_manager
        self._auto_run_config = auto_run_config
        self._automation_engine = automation_engine
        self._db_lookup = db_lookup
        self._settings: Dict[str, Any] = {}
        self._command_counter: int = 0
        self._command_map: Dict[int, Dict[str, Any]] = {}  # command_id → metadata

        self._subscribe_events()
        self._subscribe_completion()
        self._log_router_ready()

    def _next_command_id(self) -> int:
        self._command_counter += 1
        return self._command_counter

    # ==================================================================
    # TASK 3: COMMAND ROUTER READY at startup
    # ==================================================================

    def _log_router_ready(self):
        """Log one concise command-router report for every subscribed command event."""
        for event_name, command_name, workflow, scope, eligibility, ui_label in COMMAND_ROUTES:
            logger.info("[COMMAND ROUTER READY] EVENT=%s HANDLER=%s WORKFLOW=%s SCOPE=%s",
                        event_name, command_name, workflow or "direct", scope)

    # ==================================================================
    # Event subscriptions
    # ==================================================================

    def _subscribe_events(self):
        """Subscribe to all command events."""
        # Port actions
        self._event_bus.subscribe(CommandEvent.PORT_ON.value, self._handle_port_on)
        self._event_bus.subscribe(CommandEvent.PORT_OFF.value, self._handle_port_off)
        self._event_bus.subscribe(CommandEvent.PORT_EXCLUDE.value, self._handle_port_exclude)
        self._event_bus.subscribe(CommandEvent.PORT_INCLUDE.value, self._handle_port_include)
        self._event_bus.subscribe(CommandEvent.RESTART_ALL.value, self._handle_restart_all)
        self._event_bus.subscribe(CommandEvent.STOP_ALL.value, self._handle_stop_all)
        self._event_bus.subscribe(CommandEvent.RESET_MODEM.value, self._handle_reset_modem)
        self._event_bus.subscribe(CommandEvent.FORCE_RETRY.value, self._handle_force_retry)

        # Auto-run toggle
        self._event_bus.subscribe(CommandEvent.AUTO_RUN_TOGGLE.value, self._handle_auto_run_toggle)

        # Mass actions
        self._event_bus.subscribe(CommandEvent.MASS_CEK_NOMOR.value, self._handle_mass_cek_nomor)
        self._event_bus.subscribe(CommandEvent.MASS_REAKTIVASI.value, self._handle_mass_reaktivasi)

        # Per-port skill commands — closures capture event name
        for evt_name in ("cmd.cek_nomor", "cmd.cek_status", "cmd.cek_nik", "cmd.cari_kk",
                         "cmd.cek_limit", "cmd.reactivate", "cmd.restart_port"):
            self._event_bus.subscribe(evt_name, self._make_port_command_handler(evt_name))

        # Database lookups
        self._event_bus.subscribe(CommandEvent.DB_LOOKUP_NIK.value, self._handle_db_lookup_nik)
        self._event_bus.subscribe(CommandEvent.DB_LOOKUP_KK.value, self._handle_db_lookup_kk)

        # Modem events → AutomationEngine triggers
        self._event_bus.subscribe("modem.online", self._handle_modem_online)
        self._event_bus.subscribe("modem.offline", self._handle_modem_offline)
        self._event_bus.subscribe("modem.appeared", self._handle_modem_appeared)
        self._event_bus.subscribe("modem.disappeared", self._handle_modem_disappeared)
        self._event_bus.subscribe("cpin.transition", self._handle_cpin_changed)

        # Settings
        self._event_bus.subscribe(CommandEvent.SAVE_CONFIG.value, self._handle_save_config)

    def _subscribe_completion(self):
        """Subscribe to automation completion/failure for COMMAND RESULT traces."""
        self._event_bus.subscribe("automation.completed", self._on_workflow_completed)
        self._event_bus.subscribe("automation.failed", self._on_workflow_failed)
        self._event_bus.subscribe("port.data.updated", self._on_port_data_updated)

    # ==================================================================
    # TASK 5: Workflow completion → COMMAND RESULT
    # ==================================================================

    def _on_workflow_completed(self, payload: dict):
        port = payload.get("port", "?")
        workflow = payload.get("workflow", "?")
        trigger = payload.get("trigger", "?")
        duration = payload.get("duration", 0)

        # Find the command_id that originated this workflow
        command_id = self._find_command_id(port, workflow)

        logger.info("[COMMAND RESULT] COMMAND_ID=%s PORT=%s WORKFLOW=%s OUTCOME=success MESSAGE=completed in %.1fs",
                     command_id or "N/A", port, workflow, duration)

        # Sprint 15U: Don't overwrite data columns — only set status to IDLE.
        # Data columns (nomor/nik/kk/masa_aktif/respon) were already set by
        # port.data.updated events from step callbacks.
        self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
            "port": port, "status": "IDLE",
        })

    def _on_workflow_failed(self, payload: dict):
        port = payload.get("port", "?")
        workflow = payload.get("workflow", "?")
        error = payload.get("error", "unknown")

        command_id = self._find_command_id(port, workflow)

        logger.info("[COMMAND RESULT] COMMAND_ID=%s PORT=%s WORKFLOW=%s OUTCOME=failed MESSAGE=%s",
                     command_id or "N/A", port, workflow, error)

        # Update UI row
        self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
            "port": port, "status": "IDLE", "detail": f"Error: {error[:30]}",
        })

    # ==================================================================
    # Sprint 15U: Skill result → UI data wiring
    # ==================================================================

    def _on_port_data_updated(self, payload: dict) -> None:
        """Forward port.data.updated to PORT_UPDATE with all data fields."""
        port = payload.get("port")
        if not port:
            return

        update: dict = {"port": port}

        # Forward all data fields present in payload
        for field in ("nomor", "nik", "kk", "status", "respon", "masa_aktif"):
            value = payload.get(field)
            if value is not None:
                update[field] = str(value)

        # Map status → detail for RESPON if not already set
        if "respon" not in update and "status" in update:
            update["detail"] = update["status"]

        logger.info(
            "[PORT DATA WIRED] PORT=%s NOMOR=%s NIK=%s KK=%s STATUS=%s RESPON=%s MASA_AKTIF=%s",
            port,
            update.get("nomor", "-"),
            update.get("nik", "-"),
            update.get("kk", "-"),
            update.get("status", "-"),
            update.get("respon", "-"),
            update.get("masa_aktif", "-"),
        )

        self._event_bus.publish(UIEvent.PORT_UPDATE.value, update)

    def _find_command_id(self, port: str, workflow: str) -> Optional[int]:
        """Find the most recent command_id for a given port+workflow."""
        for cid in reversed(sorted(self._command_map.keys())):
            entry = self._command_map[cid]
            if entry.get("port") == port and entry.get("workflow") == workflow:
                return cid
        return None

    # ==================================================================
    # Eligibility
    # ==================================================================

    def _check_port_eligibility(self, port_id: str, command: str) -> Tuple[bool, str]:
        from app.domain.enums import CpinState, PortState

        worker = self._worker_manager.get_worker(port_id)
        if worker is None:
            return False, "no_worker"

        state = self._worker_manager.get_port_state(port_id)
        if state == PortState.EXCLUDED:
            return False, "excluded"

        if not worker.is_alive:
            return False, "worker_not_alive"

        if not worker.modem_online:
            return False, "modem_offline"

        sim_dependent = {"check_number", "check_status", "check_nik", "check_kk", "reactivate_full"}
        if command in sim_dependent:
            cpin = worker.cpin_state
            if cpin == CpinState.NOT_INSERTED:
                return False, "sim_not_inserted"
            if cpin == CpinState.NOT_READY:
                return False, "not_ready"
            if cpin == CpinState.UNKNOWN:
                return False, "unknown_state"
            if cpin == CpinState.PIN_REQUIRED:
                return False, "pin_required"

        hw_commands = {"hardware_restart", "hardware_reset"}
        if command in hw_commands:
            if not worker.is_connected:
                return False, "disconnected"

        return True, "ok"

    # ==================================================================
    # Port Actions
    # ==================================================================

    def _handle_port_on(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if port_id:
            worker = self._worker_manager.get_worker(port_id)
            if worker:
                worker.start()

    def _handle_port_off(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if port_id:
            worker = self._worker_manager.get_worker(port_id)
            if worker:
                worker.stop()

    def _handle_port_exclude(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if port_id:
            self._worker_manager.exclude_port(port_id)
            self._event_bus.publish(UIEvent.PORT_EXCLUDED.value, {"port": port_id})

    def _handle_port_include(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if port_id:
            self._worker_manager.include_port(port_id)
            self._event_bus.publish(UIEvent.PORT_INCLUDED.value, {"port": port_id})

    def _handle_restart_all(self, payload: Dict[str, Any]):
        command_id = self._next_command_id()
        thread_name = threading.current_thread().name
        logger.info("[COMMAND CLICK] COMMAND_ID=%d COMMAND=restart_all PORT=MASS SOURCE=workspace_button THREAD=%s",
                     command_id, thread_name)
        logger.info("[COMMAND DISPATCH] COMMAND_ID=%d COMMAND=restart_all PORT=MASS WORKFLOW=hardware_restart SOURCE=workspace_button THREAD=%s",
                     command_id, thread_name)

        eligible_count = 0
        skipped_count = 0
        for port_id, worker in self._worker_manager.workers.items():
            ok, reason = self._check_port_eligibility(port_id, "hardware_restart")
            if ok:
                logger.info("[COMMAND ENQUEUED] COMMAND_ID=%d PORT=%s WORKFLOW=hardware_restart", command_id, port_id)
                self._automation_engine.enqueue_workflow(port_id, "hardware_restart", priority=5)
                eligible_count += 1
            else:
                logger.info("[COMMAND SKIPPED] COMMAND_ID=%d PORT=%s COMMAND=restart_all REASON=%s", command_id, port_id, reason)
                skipped_count += 1

        logger.info("[COMMAND ACCEPTED] COMMAND_ID=%d COMMAND=restart_all MESSAGE=eligible=%d skipped=%d",
                     command_id, eligible_count, skipped_count)

    def _handle_stop_all(self, payload: Dict[str, Any]):
        self._worker_manager.stop_all()
        self._automation_engine.stop()

    def _handle_reset_modem(self, payload: Dict[str, Any]):
        """Reset modem for selected port. If no port selected, log feedback."""
        from automation.trigger_id import next_trigger_id
        port_id = payload.get("port")

        command_id = self._next_command_id()
        thread_name = threading.current_thread().name

        if not port_id:
            logger.info("[COMMAND CLICK] COMMAND_ID=%d COMMAND=reset_modem PORT=NONE SOURCE=workspace_button THREAD=%s",
                         command_id, thread_name)
            logger.info("[COMMAND RESULT] COMMAND_ID=%d COMMAND=reset_modem OUTCOME=skipped MESSAGE=no_port_selected",
                         command_id)
            self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
                "message": "Pilih port terlebih dahulu (klik baris port, lalu Reset Modem)",
            })
            return

        logger.info("[COMMAND CLICK] COMMAND_ID=%d COMMAND=reset_modem PORT=%s SOURCE=workspace_button THREAD=%s",
                     command_id, port_id, thread_name)
        logger.info("[COMMAND DISPATCH] COMMAND_ID=%d COMMAND=reset_modem PORT=%s WORKFLOW=hardware_reset SOURCE=workspace_button",
                     command_id, port_id)

        ok, reason = self._check_port_eligibility(port_id, "hardware_reset")
        if not ok:
            logger.info("[COMMAND SKIPPED] COMMAND_ID=%d PORT=%s COMMAND=reset_modem REASON=%s", command_id, port_id, reason)
            logger.info("[COMMAND RESULT] COMMAND_ID=%d COMMAND=reset_modem PORT=%s OUTCOME=skipped MESSAGE=%s",
                         command_id, port_id, reason)
            return

        tid = next_trigger_id()
        self._automation_engine.handle_trigger(Trigger.MODEM_OFFLINE, port_id, "Reset requested")
        self._automation_engine.enqueue_workflow(port_id, "hardware_reset", priority=5)
        logger.info("[COMMAND ENQUEUED] COMMAND_ID=%d PORT=%s WORKFLOW=hardware_reset", command_id, port_id)
        logger.info("[COMMAND ACCEPTED] COMMAND_ID=%d PORT=%s WORKFLOW=hardware_reset",
                     command_id, port_id)

    def _handle_force_retry(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if port_id:
            worker = self._worker_manager.get_worker(port_id)
            if worker:
                worker.force_retry()

    # ==================================================================
    # Auto-Run Toggle
    # ==================================================================

    def _handle_auto_run_toggle(self, payload: Dict[str, Any]):
        enabled = payload.get("enabled")
        command_id = self._next_command_id()
        logger.info("[COMMAND CLICK] COMMAND_ID=%d COMMAND=auto_run.toggle PORT=MASS SOURCE=%s THREAD=%s",
                     command_id, payload.get("source", "workspace_button"), threading.current_thread().name)

        if enabled is not None:
            self._auto_run_config.set_enabled(bool(enabled))
        else:
            self._auto_run_config.toggle()

        self._event_bus.publish(UIEvent.AUTO_RUN_CHANGED.value, {
            "enabled": self._auto_run_config.auto_run_enabled
        })
        logger.info("[COMMAND RESULT] COMMAND_ID=%d COMMAND=auto_run.toggle OUTCOME=success MESSAGE=enabled=%s",
                     command_id, self._auto_run_config.auto_run_enabled)

    # ==================================================================
    # Per-Port Skill Commands
    # ==================================================================

    def _make_port_command_handler(self, event_name: str):
        def _handler(payload: Dict[str, Any]):
            self._handle_port_command(payload, event_name)
        return _handler

    def _handle_port_command(self, payload: Dict[str, Any], event_name: str):
        port_id = payload.get("port")
        if not port_id:
            return

        workflow = PER_PORT_COMMAND_MAP.get(event_name)
        if not workflow:
            logger.warning("[COMMAND UNKNOWN] event=%s", event_name)
            return

        command_id = self._next_command_id()
        thread_name = threading.current_thread().name
        source = payload.get("source", "workspace_context_menu")

        logger.info("[COMMAND CLICK] COMMAND_ID=%d COMMAND=%s PORT=%s WORKFLOW=%s SOURCE=%s THREAD=%s",
                     command_id, event_name, port_id, workflow, source, thread_name)

        # Eligibility check
        ok, reason = self._check_port_eligibility(port_id, workflow)
        if not ok:
            logger.info("[COMMAND SKIPPED] COMMAND_ID=%d PORT=%s COMMAND=%s REASON=%s", command_id, port_id, event_name, reason)
            self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
                "message": f"Skipped {port_id}: {reason}",
            })
            return

        logger.info("[COMMAND DISPATCH] COMMAND_ID=%d COMMAND=%s PORT=%s WORKFLOW=%s SOURCE=%s",
                     command_id, event_name, port_id, workflow, source)

        # UI: show processing
        self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
            "port": port_id, "status": "PROCESSING", "detail": f"Running {workflow}...",
        })

        # Track command for result wiring
        self._command_map[command_id] = {
            "port": port_id,
            "workflow": workflow,
            "command": event_name,
        }

        # Enqueue
        self._automation_engine.enqueue_workflow(port_id, workflow, priority=5, trigger_id=command_id)
        logger.info("[COMMAND ENQUEUED] COMMAND_ID=%d PORT=%s WORKFLOW=%s", command_id, port_id, workflow)
        logger.info("[COMMAND ACCEPTED] COMMAND_ID=%d PORT=%s WORKFLOW=%s",
                     command_id, port_id, workflow)

    # ==================================================================
    # Mass Actions
    # ==================================================================

    def _handle_mass_cek_nomor(self, payload: Dict[str, Any]):
        import threading as _threading
        command_id = self._next_command_id()
        _tname = _threading.current_thread().name
        logger.info("[COMMAND CLICK] COMMAND_ID=%d COMMAND=mass.cek_nomor PORT=MASS SOURCE=workspace_button THREAD=%s",
                     command_id, _tname)

        def _dispatch():
            _dt = _threading.current_thread().name
            logger.info("[COMMAND DISPATCH] COMMAND_ID=%d COMMAND=mass.cek_nomor PORT=MASS WORKFLOW=check_number THREAD=%s",
                         command_id, _dt)
            self._automation_engine.set_mode_from_name("CHECK_DATA")

            eligible, skipped = self._get_mass_targets(command_id, "check_number")
            logger.info("[MASS COMMAND] COMMAND_ID=%d PORTS_SELECTED=%d WORKFLOW=check_number TOTAL_PORTS=%d",
                         command_id, len(eligible), len(eligible) + len(skipped))
            for port_id in eligible:
                port_cmd_id = self._next_command_id()
                self._command_map[port_cmd_id] = {
                    "port": port_id, "workflow": "check_number", "command": "mass.cek_nomor",
                }
                logger.info("[MASS COMMAND DISPATCH] COMMAND_ID=%d PORT=%s WORKFLOW=check_number", port_cmd_id, port_id)
                logger.info("[COMMAND ENQUEUED] COMMAND_ID=%d PORT=%s WORKFLOW=check_number", port_cmd_id, port_id)
                self._automation_engine.enqueue_workflow(port_id, "check_number", priority=10, trigger_id=port_cmd_id)

            for port_id, reason in skipped:
                logger.info("[COMMAND SKIPPED] COMMAND_ID=%d PORT=%s COMMAND=mass.cek_nomor REASON=%s", command_id, port_id, reason)

            self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
                "message": f"Mass check number started on {len(eligible)} ports",
                "total": len(eligible),
            })
            logger.info("[COMMAND ACCEPTED] COMMAND_ID=%d COMMAND=mass.cek_nomor MESSAGE=enqueued=%d skipped=%d",
                         command_id, len(eligible), len(skipped))

        _threading.Thread(target=_dispatch, name=f"MassDispatch-check_number-{command_id}", daemon=True).start()

    def _handle_mass_reaktivasi(self, payload: Dict[str, Any]):
        import threading as _threading
        command_id = self._next_command_id()
        _tname = _threading.current_thread().name
        logger.info("[COMMAND CLICK] COMMAND_ID=%d COMMAND=mass.reaktivasi PORT=MASS SOURCE=workspace_button THREAD=%s",
                     command_id, _tname)

        def _dispatch():
            _dt = _threading.current_thread().name
            logger.info("[COMMAND DISPATCH] COMMAND_ID=%d COMMAND=mass.reaktivasi PORT=MASS WORKFLOW=reactivate_full THREAD=%s",
                         command_id, _dt)
            self._automation_engine.set_mode_from_name("REACTIVATE_FULL")

            eligible, skipped = self._get_mass_targets(command_id, "reactivate_full")
            logger.info("[MASS COMMAND] COMMAND_ID=%d PORTS_SELECTED=%d WORKFLOW=reactivate_full TOTAL_PORTS=%d",
                         command_id, len(eligible), len(eligible) + len(skipped))
            for port_id in eligible:
                port_cmd_id = self._next_command_id()
                self._command_map[port_cmd_id] = {
                    "port": port_id, "workflow": "reactivate_full", "command": "mass.reaktivasi",
                }
                logger.info("[MASS COMMAND DISPATCH] COMMAND_ID=%d PORT=%s WORKFLOW=reactivate_full", port_cmd_id, port_id)
                logger.info("[COMMAND ENQUEUED] COMMAND_ID=%d PORT=%s WORKFLOW=reactivate_full", port_cmd_id, port_id)
                self._automation_engine.enqueue_workflow(port_id, "reactivate_full", priority=10, trigger_id=port_cmd_id)

            for port_id, reason in skipped:
                logger.info("[COMMAND SKIPPED] COMMAND_ID=%d PORT=%s COMMAND=mass.reaktivasi REASON=%s", command_id, port_id, reason)

            self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
                "message": f"Mass reactivation started on {len(eligible)} ports",
                "total": len(eligible),
            })
            logger.info("[COMMAND ACCEPTED] COMMAND_ID=%d COMMAND=mass.reaktivasi MESSAGE=enqueued=%d skipped=%d",
                         command_id, len(eligible), len(skipped))

        _threading.Thread(target=_dispatch, name=f"MassDispatch-reaktivasi-{command_id}", daemon=True).start()

    def _get_mass_targets(self, command_id: int, workflow: str) -> Tuple[List[str], List[Tuple[str, str]]]:
        eligible = []
        skipped = []
        active_ports = self._worker_manager.get_active_ports()

        for port_id in active_ports:
            ok, reason = self._check_port_eligibility(port_id, workflow)
            if ok:
                eligible.append(port_id)
            else:
                skipped.append((port_id, reason))

        return eligible, skipped

    # ==================================================================
    # Modem Events → AutomationEngine Triggers
    # ==================================================================

    def _handle_modem_online(self, payload: Dict[str, Any]):
        from automation.trigger_id import next_trigger_id
        port_id = payload.get("port")
        if port_id:
            tid = next_trigger_id()
            logger.info("[TRIGGER SOURCE] ID=%d SOURCE=CONTROLLER TRIGGER=MODEM_ONLINE PORT=%s", tid, port_id)
            worker = self._worker_manager.get_worker(port_id)
            if worker:
                worker.set_modem_online(True)
            self._automation_engine.handle_trigger(Trigger.MODEM_ONLINE, port_id, trigger_id=tid, source="CONTROLLER")

    def _handle_modem_offline(self, payload: Dict[str, Any]):
        from automation.trigger_id import next_trigger_id
        port_id = payload.get("port")
        if port_id:
            tid = next_trigger_id()
            logger.info("[TRIGGER SOURCE] ID=%d SOURCE=CONTROLLER TRIGGER=MODEM_OFFLINE PORT=%s", tid, port_id)
            worker = self._worker_manager.get_worker(port_id)
            if worker:
                worker.set_modem_online(False)
            self._automation_engine.handle_trigger(Trigger.MODEM_OFFLINE, port_id, trigger_id=tid, source="CONTROLLER")

    def _handle_modem_appeared(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if port_id:
            self._worker_manager.create_worker(port_id)

    def _handle_modem_disappeared(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if port_id:
            logger.info("[WORKFLOW CANCELLED] PORT=%s REASON=worker_destroyed", port_id)
            self._worker_manager.destroy_worker(port_id)

    def _handle_cpin_changed(self, payload: Dict[str, Any]):
        from automation.trigger_id import next_trigger_id
        port_id = payload.get("port")
        new_state = payload.get("new", "")
        if port_id:
            if new_state == "READY":
                tid = next_trigger_id()
                logger.info("[TRIGGER SOURCE] ID=%d SOURCE=CONTROLLER TRIGGER=CPIN_READY PORT=%s", tid, port_id)
                self._automation_engine.handle_trigger(Trigger.CPIN_READY, port_id, trigger_id=tid, source="CONTROLLER")
            elif new_state in ("PIN_REQUIRED", "NOT_READY"):
                tid = next_trigger_id()
                logger.info("[TRIGGER SOURCE] ID=%d SOURCE=CONTROLLER TRIGGER=CPIN_REQUIRED PORT=%s", tid, port_id)
                self._automation_engine.handle_trigger(Trigger.CPIN_REQUIRED, port_id, trigger_id=tid, source="CONTROLLER")

    # ==================================================================
    # Database Lookups
    # ==================================================================

    def _handle_db_lookup_nik(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        msisdn = payload.get("msisdn")
        if not port_id or not msisdn:
            return
        result = self._db_lookup.lookup_nik(msisdn)
        self._event_bus.publish(UIEvent.DB_LOOKUP_RESULT.value, {
            "port": port_id, "lookup_type": "nik", "msisdn": msisdn, "result": result,
        })

    def _handle_db_lookup_kk(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        nik = payload.get("nik")
        if not port_id or not nik:
            return
        result = self._db_lookup.lookup_kk(nik)
        self._event_bus.publish(UIEvent.DB_LOOKUP_RESULT.value, {
            "port": port_id, "lookup_type": "kk", "nik": nik, "result": result,
        })

    # ==================================================================
    # Settings
    # ==================================================================

    def _handle_save_config(self, payload: Dict[str, Any]):
        settings = payload.get("settings", payload)
        self._settings.update(settings)
        modem = settings.get("modem", {})
        if "auto_run" in modem:
            self._auto_run_config.set_enabled(bool(modem["auto_run"]))
        self._event_bus.publish(UIEvent.SETTINGS_CHANGED.value, settings)

    def get_settings(self) -> Dict[str, Any]:
        return dict(self._settings)
