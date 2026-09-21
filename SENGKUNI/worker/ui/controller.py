"""UIController — Bridges EventBus events to worker actions.

Simplified from SAIKI's 671-line controller to ~200 lines.
No AutomationEngine, no routing table, no eligibility checks.
Direct event → action routing.
"""

import logging
import threading
from typing import Dict, Any
from worker.ui.events import CommandEvent, UIEvent
from worker.worker_manager import WorkerManager
from worker.rules import AutoRunConfig

logger = logging.getLogger("sengkuni.controller")


# Per-port command event -> skill workflow mapping
PER_PORT_SKILLS = {
    "cmd.cek_nomor":      ["cek_nomor"],
    "cmd.cek_nik":        ["cek_nik"],
    "cmd.cari_kk":        ["cek_kk"],
    "cmd.cek_limit":      ["cek_nomor"],
    "cmd.reactivate":     ["inject_reaktivasi"],
}


class UIController:
    """Bridges EventBus events to WorkerManager.

    Responsibilities:
    - Receive command events from UI
    - Route port actions to workers
    - Route mass actions to all workers
    - Manage global auto-run toggle
    - Forward port data to UI
    """

    def __init__(
        self,
        event_bus,
        worker_manager: WorkerManager,
        auto_run_config: AutoRunConfig,
    ):
        self._event_bus = event_bus
        self._worker_manager = worker_manager
        self._auto_run_config = auto_run_config
        self._settings: Dict[str, Any] = {}

        self._subscribe_events()

    # ==================================================================
    # Event subscriptions
    # ==================================================================

    def _subscribe_events(self):
        """Subscribe to all command events."""
        # Port actions
        self._event_bus.subscribe(CommandEvent.PORT_ON.value, self._handle_port_on)
        self._event_bus.subscribe(CommandEvent.PORT_OFF.value, self._handle_port_off)
        self._event_bus.subscribe(CommandEvent.RESTART_ALL.value, self._handle_restart_all)
        self._event_bus.subscribe(CommandEvent.STOP_ALL.value, self._handle_stop_all)
        self._event_bus.subscribe(CommandEvent.FORCE_RETRY.value, self._handle_force_retry)

        # Auto-run toggle
        self._event_bus.subscribe(CommandEvent.AUTO_RUN_TOGGLE.value, self._handle_auto_run_toggle)

        # Mass actions
        self._event_bus.subscribe(CommandEvent.MASS_CEK_NOMOR.value, self._handle_mass_cek_nomor)
        self._event_bus.subscribe(CommandEvent.MASS_REAKTIVASI.value, self._handle_mass_reaktivasi)

        # Per-port skill commands
        for evt_name in PER_PORT_SKILLS:
            self._event_bus.subscribe(evt_name, self._make_port_command_handler(evt_name))

        # Connect/Disconnect (user-initiated)
        self._event_bus.subscribe("cmd.connect.port", self._handle_connect_port)
        self._event_bus.subscribe("cmd.connect.all", self._handle_connect_all)
        self._event_bus.subscribe("cmd.disconnect.port", self._handle_disconnect_port)
        self._event_bus.subscribe("cmd.disconnect.all", self._handle_disconnect_all)

        # Settings
        self._event_bus.subscribe(CommandEvent.SAVE_CONFIG.value, self._handle_save_config)

        # Port data updates
        self._event_bus.subscribe("port.data.updated", self._on_port_data_updated)

        # Health monitoring events
        self._event_bus.subscribe("port.worker.stale", self._on_worker_stale)
        self._event_bus.subscribe("port.worker.health", self._on_worker_health)

    # ==================================================================
    # Port Actions
    # ==================================================================

    def _handle_port_on(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if not port_id:
            return
        logger.info("[COMMAND CLICK] COMMAND=port.on PORT=%s", port_id)
        worker = self._worker_manager.get_worker(port_id)
        if worker:
            if not worker.is_alive:
                worker.start()
            self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                "port": port_id, "status": "IDLE", "respon": "Menyala",
            })

    def _handle_port_off(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if not port_id:
            return
        logger.info("[COMMAND CLICK] COMMAND=port.off PORT=%s", port_id)
        worker = self._worker_manager.get_worker(port_id)
        if worker:
            worker.stop()
            self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                "port": port_id, "status": "OFF", "respon": "Dihentikan",
            })

    def _handle_restart_all(self, payload: Dict[str, Any]):
        logger.info("[COMMAND CLICK] COMMAND=restart_all PORT=MASS SOURCE=workspace_button")
        for port_id, worker in self._worker_manager.get_all_workers().items():
            try:
                self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                    "port": port_id, "status": "PROSES", "respon": "Restarting...",
                })
                worker.restart_hardware()
            except Exception as e:
                logger.warning("[COMMAND SKIPPED] PORT=%s REASON=%s", port_id, e)

    def _handle_stop_all(self, payload: Dict[str, Any]):
        logger.info("[COMMAND CLICK] COMMAND=stop_all PORT=MASS")
        self._worker_manager.stop_all()
        self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
            "message": "All ports stopped",
        })

    def _handle_force_retry(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if not port_id:
            return
        logger.info("[COMMAND CLICK] COMMAND=force_retry PORT=%s", port_id)
        worker = self._worker_manager.get_worker(port_id)
        if worker:
            worker.force_retry()
            self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                "port": port_id, "status": "PROSES", "respon": "Retrying...",
            })

    # ==================================================================
    # Connect/Disconnect (User-Initiated)
    # ==================================================================

    def _handle_connect_port(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if not port_id:
            return
        logger.info("[COMMAND CLICK] COMMAND=connect.port PORT=%s", port_id)
        self._worker_manager._create_and_start_worker(port_id)
        self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
            "port": port_id, "status": "IDLE", "respon": "Menyala",
        })

    def _handle_connect_all(self, payload: Dict[str, Any]):
        logger.info("[COMMAND CLICK] COMMAND=connect.all PORT=MASS")
        detected = self._worker_manager.scan_ports()
        for port_id in detected:
            if not self._worker_manager.get_worker(port_id):
                self._worker_manager._create_and_start_worker(port_id)
        self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
            "message": f"Connected {len(detected)} ports",
        })

    def _handle_disconnect_port(self, payload: Dict[str, Any]):
        port_id = payload.get("port")
        if not port_id:
            return
        logger.info("[COMMAND CLICK] COMMAND=disconnect.port PORT=%s", port_id)
        worker = self._worker_manager.get_worker(port_id)
        if worker:
            worker.stop()
        self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
            "port": port_id, "status": "OFF", "respon": "Disconnected",
        })

    def _handle_disconnect_all(self, payload: Dict[str, Any]):
        logger.info("[COMMAND CLICK] COMMAND=disconnect.all PORT=MASS")
        self._worker_manager.stop_all()
        self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
            "message": "All ports disconnected",
        })

    # ==================================================================
    # Auto-Run Toggle
    # ==================================================================

    def _handle_auto_run_toggle(self, payload: Dict[str, Any]):
        enabled = payload.get("enabled")
        if enabled is not None:
            self._auto_run_config.set_enabled(bool(enabled))
        else:
            self._auto_run_config.toggle()

        self._event_bus.publish(UIEvent.AUTO_RUN_CHANGED.value, {
            "enabled": self._auto_run_config.enabled
        })
        logger.info("[COMMAND RESULT] COMMAND=auto_run.toggle OUTCOME=success MESSAGE=enabled=%s",
                     self._auto_run_config.enabled)

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

        skills = PER_PORT_SKILLS.get(event_name)
        if not skills:
            logger.warning("[COMMAND UNKNOWN] event=%s", event_name)
            return

        source = payload.get("source", "workspace_context_menu")
        logger.info("[COMMAND CLICK] COMMAND=%s PORT=%s SOURCE=%s", event_name, port_id, source)

        worker = self._worker_manager.get_worker(port_id)
        if worker is None:
            logger.info("[COMMAND SKIPPED] PORT=%s REASON=no_worker", port_id)
            return

        if not worker.is_alive:
            logger.info("[COMMAND SKIPPED] PORT=%s REASON=worker_not_alive", port_id)
            return

        # UI: show processing
        self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
            "port": port_id, "status": "PROSES", "respon": f"Running {event_name}...",
        })

        # Run skills via port_worker
        worker.run_skills(skills)
        logger.info("[COMMAND ACCEPTED] PORT=%s SKILLS=%s", port_id, skills)

    # ==================================================================
    # Mass Actions
    # ==================================================================

    def _handle_mass_cek_nomor(self, payload: Dict[str, Any]):
        logger.info("[COMMAND CLICK] COMMAND=mass.cek_nomor PORT=MASS")
        workers = list(self._worker_manager.get_all_workers().values())
        eligible = 0
        for worker in workers:
            if worker.is_alive and worker.cpin_ready:
                self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                    "port": worker.port_id, "status": "PROSES", "respon": "Cek Nomor...",
                })
                worker.run_skills(["cek_nomor"])
                eligible += 1
        self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
            "message": f"Mass check number started on {eligible} ports",
            "total": eligible,
        })

    def _handle_mass_reaktivasi(self, payload: Dict[str, Any]):
        logger.info("[COMMAND CLICK] COMMAND=mass.reaktivasi PORT=MASS")
        workers = list(self._worker_manager.get_all_workers().values())
        eligible = 0
        for worker in workers:
            if worker.is_alive and worker.cpin_ready:
                self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                    "port": worker.port_id, "status": "PROSES", "respon": "Reaktivasi...",
                })
                worker.run_skills(["inject_reaktivasi"])
                eligible += 1
        self._event_bus.publish(UIEvent.MASS_PROGRESS.value, {
            "message": f"Mass reactivation started on {eligible} ports",
            "total": eligible,
        })

    # ==================================================================
    # Port Data Wiring
    # ==================================================================

    def _on_port_data_updated(self, payload: dict) -> None:
        """Forward port.data.updated to PORT_UPDATE with all data fields."""
        port = payload.get("port")
        if not port:
            return

        update: dict = {"port": port}
        for field in ("nomor", "nik", "kk", "status", "respon", "masa_aktif"):
            value = payload.get(field)
            if value is not None:
                update[field] = str(value)

        if "respon" not in update and "status" in update:
            update["respon"] = update["status"]

        self._event_bus.publish(UIEvent.PORT_UPDATE.value, update)

    # ==================================================================
    # Health Monitoring
    # ==================================================================

    def _on_worker_stale(self, payload: dict) -> None:
        """Handle worker stale event — worker thread not responding."""
        port = payload.get("port")
        stale_seconds = payload.get("stale_seconds", 0)
        if port:
            logger.warning("[HEALTH] PORT=%s STALE=%.0fs — worker may be stuck", port, stale_seconds)
            self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                "port": port,
                "status": "WARNING",
                "respon": f"Worker stale {stale_seconds:.0f}s",
            })

    def _on_worker_health(self, payload: dict) -> None:
        """Handle worker health event — periodic status update."""
        port = payload.get("port")
        cpin_state = payload.get("cpin_state")
        uptime = payload.get("uptime")
        if port:
            detail = f"CPIN={cpin_state}"
            if uptime:
                detail += f" uptime={uptime:.0f}s"
            self._event_bus.publish(UIEvent.PORT_UPDATE.value, {
                "port": port,
                "status": cpin_state or "UNKNOWN",
                "respon": detail,
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
