"""GUI Entry Point — launches the SAIKI GUI application.

Uses CustomTkinter with ttk fallback.
All components consumed from SystemBootstrap — never created directly.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import tkinter as tk
from typing import Optional

SAIKI_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SAIKI_ROOT, "app"))

from worker.system_bootstrap import SystemBootstrap
from worker.ui.event_bus import EventBus
from worker.ui.events import CommandEvent, UIEvent
from worker.ui.main_window import MainWindow
from worker.ui.controller import UIController

logger = logging.getLogger(__name__)


class GUIApplication:
    """GUI application bootstrap.

    Consumes all components from SystemBootstrap.
    Never creates AutomationEngine, WorkflowRunner, WorkflowRegistry,
    or WorkerManager directly.
    """

    def __init__(self):
        self._bootstrap: Optional[SystemBootstrap] = None
        self._ui_controller: Optional[UIController] = None
        self._main_window: Optional[MainWindow] = None
        self._root: Optional[tk.Tk] = None

    def start(self) -> None:
        """Initialize and start the GUI application. GUI appears immediately."""
        launch_start = time.time()
        logger.info("[GUI] Starting SAIKI GUI application...")

        # Create all components via SystemBootstrap (single source of truth)
        self._bootstrap = SystemBootstrap()

        # Create main window with bootstrap's event bus
        self._main_window = MainWindow(self._bootstrap.event_bus)
        self._root = self._main_window.create()

        # Create UI controller (bridges UI events to backend)
        self._ui_controller = UIController(
            event_bus=self._bootstrap.event_bus,
            worker_manager=self._bootstrap.worker_manager,
            auto_run_config=self._bootstrap.auto_run_config,
            automation_engine=self._bootstrap.automation_engine,
            db_lookup=self._bootstrap.db_lookup,
        )

        # Subscribe to UI events for updating the window
        self._subscribe_ui_events()

        launch_duration = time.time() - launch_start
        logger.info("[GUI] Window created in %.2fs — launching mainloop", launch_duration)

        # Start bootstrap in background thread (non-blocking)
        def _start_backend():
            backend_start = time.time()
            self._bootstrap.start()
            backend_duration = time.time() - backend_start
            logger.info("[GUI] Backend started in %.2fs", backend_duration)
            # Publish initial footer update after first scan completes
            self._publish_footer_update()

        threading.Thread(target=_start_backend, daemon=True).start()

        # Mainloop — GUI appears immediately, ports appear progressively
        self._root.mainloop()

    def _subscribe_ui_events(self) -> None:
        """Subscribe to events that update the UI."""
        bus = self._bootstrap.event_bus
        bus.subscribe(UIEvent.PORT_DISCOVERED.value, self._on_port_discovered)
        bus.subscribe(UIEvent.PORT_UPDATE.value, self._on_port_update)
        bus.subscribe(UIEvent.PORT_REMOVED.value, self._on_port_removed)
        bus.subscribe(UIEvent.LOG_APPEND.value, self._on_log_append)
        bus.subscribe(UIEvent.FOOTER_UPDATE.value, self._on_footer_update)
        bus.subscribe(UIEvent.AUTO_RUN_CHANGED.value, self._on_auto_run_changed)
        bus.subscribe(UIEvent.MASS_PROGRESS.value, self._on_mass_progress)
        bus.subscribe(UIEvent.MASS_COMPLETE.value, self._on_mass_complete)
        # Scan complete triggers footer update
        bus.subscribe(UIEvent.SCAN_COMPLETE.value, self._on_scan_complete)
        # CPIN transitions → UI port status (Sprint 15D)
        bus.subscribe("cpin.transition", self._on_cpin_transition)

    def _on_port_discovered(self, payload: dict) -> None:
        """Handle port discovered — add row to table."""
        port = payload.get("port")
        if port and self._main_window:
            self._main_window.update_port(port, "port_display", port)
            self._main_window.update_port(port, "status", "IDLE")
            self._main_window.update_port(port, "respon", "Idle/Standby")

    def _on_port_update(self, payload: dict) -> None:
        """Handle port data update.

        PortWorker publishes: {"port": id, "status": val, "detail": str}
        Sprint 15U: Also handles nomor, nik, kk, masa_aktif from skill results.
        """
        port = payload.get("port")
        if not port or not self._main_window:
            return

        # Map PortWorker payload to table columns
        status = payload.get("status")
        detail = payload.get("detail")

        if status is not None:
            self._main_window.update_port(port, "status", str(status))
        if detail is not None:
            self._main_window.update_port(port, "respon", str(detail))

        # Sprint 15U: Skill result data columns
        for field in ("nomor", "nik", "kk", "masa_aktif"):
            value = payload.get(field)
            if value is not None and value != "-":
                self._main_window.update_port(port, field, str(value))

        # Sprint 15U: Direct respon field (from skill result, not just "detail")
        respon = payload.get("respon")
        if respon is not None:
            self._main_window.update_port(port, "respon", str(respon))

        # Refresh footer after status change
        self._publish_footer_update()

    def _on_port_removed(self, payload: dict) -> None:
        """Handle port removed."""
        port = payload.get("port")
        if port and self._main_window:
            self._main_window.remove_port(port)
            self._publish_footer_update()

    def _on_log_append(self, payload: dict) -> None:
        """Handle log append — append line, don't replace."""
        port = payload.get("port")
        line = payload.get("line")
        if port and line and self._main_window:
            self._main_window.append_log_line(port, line)

    def _on_footer_update(self, payload: dict) -> None:
        """Handle footer update."""
        total = payload.get("total", 0)
        active = payload.get("active", 0)
        off = payload.get("off", 0)
        excluded = payload.get("excluded", 0)
        if self._main_window:
            self._main_window.update_footer(total, active, off, excluded)

    def _on_auto_run_changed(self, payload: dict) -> None:
        """Handle auto-run state change."""
        enabled = payload.get("enabled", True)
        if self._main_window:
            self._main_window.set_auto_run_state(enabled)

    def _on_mass_progress(self, payload: dict) -> None:
        """Handle mass action progress."""
        message = payload.get("message", "")
        logger.info(f"[GUI] Mass progress: {message}")

    def _on_mass_complete(self, payload: dict) -> None:
        """Handle mass action complete."""
        logger.info("[GUI] Mass action completed")

    def _on_scan_complete(self, payload: dict) -> None:
        """Handle scan complete — refresh footer."""
        self._publish_footer_update()

    def _on_cpin_transition(self, payload: dict) -> None:
        """Handle CPIN state transition — update UI status and respon (Sprint 15H-A).

        Sprint 15R.1: Neutral states (NOT_INSERTED/NOT_READY/UNKNOWN/PIN_REQUIRED/STANDBY/IDLE)
                      display as IDLE with RESPON = "-".
                      Internal domain state is NOT changed.
        """
        port = payload.get("port")
        new_state = payload.get("new", "")
        if not port or not self._main_window:
            return

        logger.info("[UI TRACE] EVENT: cpin.transition PORT=%s STATE=%s", port, new_state)

        # Neutral/non-operational CPIN states → IDLE presentation
        _NEUTRAL_CPIN = {"NOT_INSERTED", "NOT_READY", "UNKNOWN", "PIN_REQUIRED", "IDLE", "STANDBY"}

        if new_state == "READY":
            port_status = "READY"
            display_text = "SIM Inserted"
        elif new_state in _NEUTRAL_CPIN:
            port_status = "IDLE"
            display_text = "-"
        else:
            # Unknown/new state — treat as neutral
            port_status = "IDLE"
            display_text = "-"

        # Update port status and respon columns
        logger.info("[STATUS WRITE] PORT=%s OLD=? NEW=%s SOURCE=cpin_transition", port, port_status)
        self._main_window.update_port(port, "status", port_status)
        self._main_window.update_port(port, "respon", display_text)

        # Append CPIN log line
        if display_text and display_text != "-":
            self._main_window.append_log_line(port, f"[CPIN] SIM state: {display_text}")

        logger.info("[GUI] %s: CPIN transition → %s (status=%s)", port, display_text, port_status)

    def _publish_footer_update(self) -> None:
        """Compute and publish footer update from WorkerManager state."""
        if not self._bootstrap:
            return
        wm = self._bootstrap.worker_manager
        port_states = wm.get_all_port_states()
        validation = wm.get_validation_results()

        total = len(port_states) + len([v for v in validation.values()
                                         if v.status.value != "VALID_MODEM"])
        active = sum(1 for s in port_states.values() if s.value == "ACTIVE")
        excluded = sum(1 for s in port_states.values() if s.value == "EXCLUDED")
        off = total - active - excluded

        self._bootstrap.event_bus.publish(UIEvent.FOOTER_UPDATE.value, {
            "total": total,
            "active": active,
            "off": max(0, off),
            "excluded": excluded,
        })


def main():
    """Main entry point for GUI mode."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    app = GUIApplication()
    app.start()


if __name__ == "__main__":
    main()
