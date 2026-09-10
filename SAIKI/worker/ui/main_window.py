"""Main Application Window — top-level window with tab navigation.

Three tabs:
- HOME (Workspace): port table, action bar, context menu
- REPORT (Panen Monitor): harvest data table
- SETTING (Config): USSD, gateway, injection settings

All business logic delegated to Event Bus.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable, Dict, Optional

from .events import CommandEvent, UIEvent
from .context_menu import PortContextMenu
from .log_viewer import LogViewer
from .port_table import PortStatusTable
from .update_queue import TaskQueue, UpdateQueue
from .worker_monitor import WorkerMonitor

logger = logging.getLogger("saiki.ui")


class MainWindow:
    """Main application window with tab navigation.

    Architecture:
    - UI renders widgets
    - All actions publish events to Event Bus
    - Controller subscribes to events and orchestrates
    - No business logic in this class
    """

    def __init__(self, event_bus):
        self._event_bus = event_bus
        self._update_queue = UpdateQueue()
        self._task_queue = TaskQueue()
        self._settings: Dict[str, Any] = {}

        # UI heartbeat (Sprint 15P)
        from worker.ui.ui_heartbeat import UIHeartbeat
        self._heartbeat = UIHeartbeat(freeze_threshold=5.0)

        # Root window
        self._root: Optional[tk.Tk] = None
        self._active_tab: str = "HOME"

        # Tab buttons
        self._btn_home: Optional[tk.Button] = None
        self._btn_report: Optional[tk.Button] = None
        self._btn_setting: Optional[tk.Button] = None

        # Content area
        self._body: Optional[tk.Frame] = None
        self._footer: Optional[tk.Frame] = None

        # Components
        self._port_table: Optional[PortStatusTable] = None
        self._context_menu: Optional[PortContextMenu] = None
        self._log_viewer = LogViewer(self)
        self._worker_monitor: Optional[WorkerMonitor] = None
        self._settings_dialog = None

        # Persistent port data cache — survives tab switches
        self._port_data: Dict[str, Dict[str, str]] = {}

        # Panen (harvest) table
        self._panen_tree: Optional[ttk.Treeview] = None
        self._panen_menu: Optional[tk.Menu] = None

        # Filter
        self._filter_mode: str = "Tampilkan Semua Port"

        # Auto-run button (for toggling text)
        self._btn_auto_run: Optional[tk.Button] = None
        self._auto_run_enabled: bool = True

    def create(self) -> tk.Tk:
        """Create and configure the main window."""
        try:
            import customtkinter as ctk
            self._create_ctk(ctk)
        except ImportError:
            self._create_ttk()
        return self._root

    def _create_ctk(self, ctk) -> None:
        """Create window using CustomTkinter."""
        ctk.set_appearance_mode("Light")
        self._root = ctk.CTk()
        self._root.title("Kebun Reaktivasi Massal v2.2 - Light Commercial Edition")
        self._root.geometry("1150x700")
        self._root.configure(fg_color="#F5EFEB")

        # Tab bar
        tab_bar = ctk.CTkFrame(self._root, fg_color="#D9D9D9", height=40, corner_radius=0)
        tab_bar.pack(fill="x", side="top")

        self._btn_home = ctk.CTkButton(tab_bar, text="WORKSPACE", width=140, height=35, corner_radius=8,
                                        font=("Helvetica", 11, "bold"), command=lambda: self.switch_tab("HOME"))
        self._btn_home.pack(side="left", padx=(10, 2), pady=(5, 0))

        self._btn_report = ctk.CTkButton(tab_bar, text="PANEN MONITOR", width=140, height=35, corner_radius=8,
                                          font=("Helvetica", 11, "bold"), command=lambda: self.switch_tab("REPORT"))
        self._btn_report.pack(side="left", padx=2, pady=(5, 0))

        self._btn_setting = ctk.CTkButton(tab_bar, text="CONFIG", width=140, height=35, corner_radius=8,
                                           font=("Helvetica", 11, "bold"), command=lambda: self.switch_tab("SETTING"))
        self._btn_setting.pack(side="left", padx=2, pady=(5, 0))

        # Body
        self._body = ctk.CTkFrame(self._root, corner_radius=0, fg_color="transparent")
        self._body.pack(fill="both", expand=True, padx=10, pady=10)

        # Footer
        self._footer = ctk.CTkFrame(self._root, height=25, fg_color="transparent")
        self._footer.pack(fill="x", side="bottom", padx=15, pady=2)

        lbl_footer = ctk.CTkLabel(self._footer, text="SLOT ACTIVE PORT MONITOR: Initializing...",
                                   text_color="#2F4156", font=("Helvetica", 11, "bold"))
        lbl_footer.pack(side="left")
        self._worker_monitor = WorkerMonitor(self._footer, self._event_bus)
        self._worker_monitor._footer_label = lbl_footer

        # Log viewer
        self._log_viewer = LogViewer(self._root)

        # Default tab
        self.switch_tab("HOME")

        # Start heartbeat monitor (Sprint 15P)
        self._heartbeat.start()

        # Start drain loop
        self._root.after(100, self._drain_events)

    def _create_ttk(self) -> None:
        """Create window using pure ttk."""
        self._root = tk.Tk()
        self._root.title("Kebun Reaktivasi Massal v2.2 - Light Commercial Edition")
        self._root.geometry("1150x700")
        self._root.configure(bg="#F5EFEB")

        # Tab bar
        tab_bar = tk.Frame(self._root, bg="#D9D9D9", height=40)
        tab_bar.pack(fill="x", side="top")

        self._btn_home = tk.Button(tab_bar, text="WORKSPACE", width=15, command=lambda: self.switch_tab("HOME"))
        self._btn_home.pack(side="left", padx=(10, 2), pady=(5, 0))

        self._btn_report = tk.Button(tab_bar, text="PANEN MONITOR", width=15, command=lambda: self.switch_tab("REPORT"))
        self._btn_report.pack(side="left", padx=2, pady=(5, 0))

        self._btn_setting = tk.Button(tab_bar, text="CONFIG", width=15, command=lambda: self.switch_tab("SETTING"))
        self._btn_setting.pack(side="left", padx=2, pady=(5, 0))

        # Body
        self._body = tk.Frame(self._root, bg="#F5EFEB")
        self._body.pack(fill="both", expand=True, padx=10, pady=10)

        # Footer
        self._footer = tk.Frame(self._root, bg="#F5EFEB", height=25)
        self._footer.pack(fill="x", side="bottom", padx=15, pady=2)

        lbl_footer = tk.Label(self._footer, text="SLOT ACTIVE PORT MONITOR: Initializing...",
                              font=("Helvetica", 11, "bold"), fg="#2F4156", bg="#F5EFEB")
        lbl_footer.pack(side="left")
        self._worker_monitor = WorkerMonitor(self._footer, self._event_bus)
        self._worker_monitor._footer_label = lbl_footer

        self._log_viewer = LogViewer(self._root)
        self.switch_tab("HOME")
        self._root.after(100, self._drain_events)

    def switch_tab(self, target: str) -> None:
        """Switch the active tab."""
        self._active_tab = target
        if self._body:
            for widget in self._body.winfo_children():
                widget.destroy()

        color_active, color_inactive = "#F5EFEB", "#B0B0B0"
        text_active, text_inactive = "#2F4156", "#555555"

        for btn in [self._btn_home, self._btn_report, self._btn_setting]:
            if btn:
                try:
                    btn.configure(fg_color=color_inactive, text_color=text_inactive)
                except Exception:
                    btn.configure(bg=color_inactive)

        if target == "HOME":
            if self._btn_home:
                try:
                    self._btn_home.configure(fg_color=color_active, text_color=text_active)
                except Exception:
                    self._btn_home.configure(bg=color_active)
            self._render_home()
        elif target == "REPORT":
            if self._btn_report:
                try:
                    self._btn_report.configure(fg_color=color_active, text_color=text_active)
                except Exception:
                    self._btn_report.configure(bg=color_active)
            self._render_report()
        elif target == "SETTING":
            if self._btn_setting:
                try:
                    self._btn_setting.configure(fg_color=color_active, text_color=text_active)
                except Exception:
                    self._btn_setting.configure(bg=color_active)
            self._render_setting()

    def _render_home(self) -> None:
        """Render the Workspace tab."""
        try:
            import customtkinter as ctk
            action_bar = ctk.CTkFrame(self._body, fg_color="#FFFFFF", height=45, corner_radius=8)
        except ImportError:
            action_bar = tk.Frame(self._body, bg="#FFFFFF", height=45)
        action_bar.pack(fill="x", padx=5, pady=(0, 8))

        # Filter
        try:
            import customtkinter as ctk
            filter_label = ctk.CTkLabel(action_bar, text="Filter:", font=("Helvetica", 11, "bold"), text_color="#2F4156")
            filter_label.pack(side="left", padx=(10, 2))
            filter_menu = ctk.CTkOptionMenu(
                action_bar,
                values=["Tampilkan Semua Port", "Hanya Port Aktif (Menyala)", "Hanya Port Off (Mati)"],
                width=200, fg_color="#567C8D", button_color="#2F4156",
                command=self._on_filter_changed,
            )
            filter_menu.pack(side="left", padx=5, pady=7)
        except ImportError:
            tk.Label(action_bar, text="Filter:", bg="#FFFFFF").pack(side="left", padx=(10, 2))

        # Action buttons
        try:
            import customtkinter as ctk

            # Auto Run ON/OFF button
            self._btn_auto_run = ctk.CTkButton(
                action_bar, text="Auto Run: ON", fg_color="#2F4156", text_color="#FFFFFF", width=110,
                command=self._on_auto_run_toggle,
            )
            self._btn_auto_run.pack(side="left", padx=5, pady=7)

            ctk.CTkButton(action_bar, text="Reaktivasi Massal", fg_color="#567C8D", text_color="#FFFFFF", width=130,
                          command=self._on_mass_reaktivasi).pack(side="left", padx=5, pady=7)
            ctk.CTkButton(action_bar, text="Cek Nomor Massal", fg_color="#567C8D", text_color="#FFFFFF", width=130,
                          command=self._on_mass_cek_nomor).pack(side="left", padx=5, pady=7)
            ctk.CTkButton(action_bar, text="Restart All", fg_color="#2F4156", text_color="#FFFFFF", width=100,
                          command=self._on_restart_all).pack(side="left", padx=5, pady=7)
        except ImportError:
            tk.Button(action_bar, text="Restart All", command=self._on_restart_all).pack(side="left", padx=5)

        # Port table
        self._port_table = PortStatusTable(self._body, on_log_click=self._on_log_click)
        self._port_table.pack(fill="both", expand=True, padx=5, pady=2)

        # Repopulate from persistent cache (survives tab switches)
        # Sprint 15R.1: Sort numerically before inserting
        import re as _re
        def _num_key(port_name):
            m = _re.search(r'(\d+)', port_name)
            return int(m.group(1)) if m else 0

        for port in sorted(self._port_data.keys(), key=_num_key):
            data = self._port_data[port]
            raw_status = data.get("status", "IDLE")
            # Sprint 15R.1: Neutral states → IDLE, RESPON → "-"
            from worker.ui.port_table import _NEUTRAL_STATUSES
            norm_status = "IDLE" if raw_status in _NEUTRAL_STATUSES else raw_status
            norm_respon = "-" if raw_status in _NEUTRAL_STATUSES else data.get("respon", "-")
            values = [
                data.get("port_display", port),
                data.get("nomor", "-"),
                data.get("nik", "-"),
                data.get("kk", "-"),
                norm_status,
                norm_respon,
                data.get("masa_aktif", "-"),
                "LOG",
            ]
            self._port_table.insert_row(port, values)

        # Context menu
        self._context_menu = PortContextMenu(self._root, self._event_bus)
        self._port_table._tree.bind("<Button-3>", self._on_tree_right_click)

    def _render_report(self) -> None:
        """Render the Panen Monitor tab."""
        try:
            import customtkinter as ctk
            ctk.CTkLabel(self._body, text="RINGKASAN LIVE HASIL PANEN DATABASE",
                         font=("Helvetica", 13, "bold"), text_color="#2F4156").pack(pady=(5, 8))

            toolbar = ctk.CTkFrame(self._body, fg_color="#FFFFFF", corner_radius=8)
            toolbar.pack(fill="x", padx=15, pady=(0, 8))
            ctk.CTkButton(toolbar, text="Hapus Terpilih", fg_color="#A51D24", hover_color="#7A141A",
                          command=self._on_panen_delete_selected).pack(side="left", padx=8, pady=8)
            ctk.CTkButton(toolbar, text="Hapus Semua Data Panen", fg_color="#567C8D", hover_color="#2F4156",
                          command=self._on_panen_delete_all).pack(side="left", padx=(0, 8), pady=8)
            ctk.CTkButton(toolbar, text="Refresh", fg_color="#2F4156", hover_color="#1A2836",
                          command=self._on_panen_refresh).pack(side="left", padx=(0, 8), pady=8)
        except ImportError:
            tk.Label(self._body, text="PANEN MONITOR", font=("Helvetica", 13, "bold")).pack(pady=(5, 8))

        table_frame = ttk.Frame(self._body)
        table_frame.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self._panen_tree = ttk.Treeview(
            table_frame,
            columns=("no", "nomor", "nik", "kk", "timestamp"),
            show="headings", height=16,
        )
        self._panen_tree.heading("no", text="#")
        self._panen_tree.heading("nomor", text="NOMOR")
        self._panen_tree.heading("nik", text="NIK")
        self._panen_tree.heading("kk", text="KK")
        self._panen_tree.heading("timestamp", text="WAKTU")
        self._panen_tree.column("no", width=50, anchor=tk.CENTER)
        self._panen_tree.column("nomor", width=140, anchor=tk.CENTER)
        self._panen_tree.column("nik", width=170, anchor=tk.CENTER)
        self._panen_tree.column("kk", width=170, anchor=tk.CENTER)
        self._panen_tree.column("timestamp", width=190, anchor=tk.CENTER)
        self._panen_tree.pack(side="left", fill="both", expand=True)
        self._panen_tree.configure(selectmode="extended")

        self._panen_tree.bind("<Button-3>", self._on_panen_right_click)
        self._panen_tree.bind("<Control-a>", lambda e: self._panen_tree.selection_set(self._panen_tree.get_children()))

        self._panen_menu = tk.Menu(self._root, tearoff=0)
        self._panen_menu.add_command(label="Hapus baris terpilih", command=self._on_panen_delete_selected)
        self._panen_menu.add_command(label="Hapus semua data panen", command=self._on_panen_delete_all)

        sb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self._panen_tree.yview)
        self._panen_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def _render_setting(self) -> None:
        """Render the Config tab."""
        from .settings_dialog import SettingsDialog, load_config
        container = tk.Frame(self._body, bg="#F5EFEB")
        container.pack(fill="both", expand=True, padx=5, pady=5)

        # Load config from disk (or use defaults)
        self._settings = load_config()
        self._settings_dialog = SettingsDialog(container, self._event_bus, self._settings)
        self._settings_dialog.build(container)

    def _drain_events(self) -> None:
        """Main thread event drain loop. Runs every 100ms."""
        # Heartbeat tick (Sprint 15P)
        self._heartbeat.tick()

        # Execute tasks
        tasks = self._task_queue.drain()
        for task in tasks:
            try:
                task()
            except Exception:
                pass

        # Apply UI updates
        updates = self._update_queue.drain()
        if self._port_table:
            for port, column, value in updates:
                if column == "_delete":
                    self._port_table.delete_row(port)
                else:
                    self._port_table.update_cell(port, column, value)

        # Re-schedule
        if self._root:
            self._root.after(100, self._drain_events)

    def _on_tree_right_click(self, event) -> None:
        """Handle right-click on port table."""
        if self._port_table:
            self._port_table._on_right_click(event)
            port = self._port_table.get_selection()
            if port and self._context_menu:
                self._context_menu.show(port, event.x_root, event.y_root)

    def _on_log_click(self, port: str) -> None:
        """Handle left-click on LOG column."""
        if self._log_viewer:
            self._log_viewer.show(port)

    def _on_filter_changed(self, choice: str) -> None:
        """Handle filter change."""
        self._filter_mode = choice
        self._event_bus.publish(CommandEvent.PORT_ON.value, {"action": "filter_changed", "filter": choice})

    def _on_auto_run_toggle(self) -> None:
        """Toggle auto-run state."""
        self._auto_run_enabled = not self._auto_run_enabled
        if self._btn_auto_run:
            label = "Auto Run: ON" if self._auto_run_enabled else "Auto Run: OFF"
            color = "#2F4156" if self._auto_run_enabled else "#A51D24"
            try:
                self._btn_auto_run.configure(text=label, fg_color=color)
            except Exception:
                pass
        logger.info("[COMMAND CLICK] COMMAND=auto_run.toggle PORT=MASS SOURCE=workspace_button THREAD=%s",
                     threading.current_thread().name)
        self._event_bus.publish(CommandEvent.AUTO_RUN_TOGGLE.value, {"enabled": self._auto_run_enabled})

    def _on_mass_reaktivasi(self) -> None:
        """Publish mass reactivation event."""
        logger.info("[COMMAND CLICK] COMMAND=mass.reaktivasi PORT=MASS SOURCE=workspace_button THREAD=%s",
                     threading.current_thread().name)
        self._event_bus.publish(CommandEvent.MASS_REAKTIVASI.value, {
            "source": "workspace_button",
        })

    def _on_mass_cek_nomor(self) -> None:
        """Publish mass check number event."""
        logger.info("[COMMAND CLICK] COMMAND=mass.cek_nomor PORT=MASS SOURCE=workspace_button THREAD=%s",
                     threading.current_thread().name)
        self._event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {
            "source": "workspace_button",
        })

    def _on_restart_all(self) -> None:
        """Publish restart all event."""
        logger.info("[COMMAND CLICK] COMMAND=restart_all PORT=MASS SOURCE=workspace_button THREAD=%s",
                     threading.current_thread().name)
        self._event_bus.publish(CommandEvent.RESTART_ALL.value, {
            "source": "workspace_button",
        })

    def _on_panen_right_click(self, event) -> None:
        """Handle right-click on panen table."""
        try:
            item = self._panen_tree.identify_row(event.y)
            if item:
                self._panen_tree.selection_set(item)
                self._panen_menu.post(event.x_root, event.y_root)
        except Exception:
            pass

    def _on_panen_delete_selected(self) -> None:
        """Publish panen delete selected event."""
        self._event_bus.publish(UIEvent.MASS_COMPLETE.value, {"bulk": False})

    def _on_panen_delete_all(self) -> None:
        """Publish panen delete all event."""
        self._event_bus.publish(UIEvent.MASS_COMPLETE.value, {"bulk": True})

    def _on_panen_refresh(self) -> None:
        """Publish panen refresh event."""
        self._event_bus.publish(UIEvent.SCAN_COMPLETE.value, {})

    def update_port(self, port: str, column: str, value: Any) -> None:
        """Queue a port cell update. Thread-safe. Also caches in _port_data."""
        # Store in persistent cache
        if port not in self._port_data:
            self._port_data[port] = {}
        self._port_data[port][column] = str(value)

        # Queue for widget update
        self._update_queue.put(port, column, value)

    def remove_port(self, port: str) -> None:
        """Remove a port from persistent cache and queue table row deletion."""
        self._port_data.pop(port, None)
        self._update_queue.put(port, "_delete", "")

    def add_task(self, task: Callable) -> None:
        """Queue a task to run on main thread. Thread-safe."""
        self._task_queue.put(task)

    def set_settings(self, settings: Dict[str, Any]) -> None:
        """Update settings."""
        self._settings = settings

    def set_log_data(self, port: str, lines: list) -> None:
        """Store log data for a port."""
        if self._log_viewer:
            self._log_viewer.set_log_data(port, lines)

    def append_log_line(self, port: str, line: str) -> None:
        """Append a log line for a port (thread-safe via main thread)."""
        if self._log_viewer:
            self._log_viewer.append_line(port, line)

    def update_footer(self, total: int, active: int, off: int, excluded: int = 0) -> None:
        """Update footer label."""
        if self._worker_monitor:
            self._worker_monitor.update_footer(total, active, off, excluded)

    def set_auto_run_state(self, enabled: bool) -> None:
        """Update auto-run button state from controller."""
        self._auto_run_enabled = enabled
        if self._btn_auto_run:
            label = "Auto Run: ON" if enabled else "Auto Run: OFF"
            color = "#2F4156" if enabled else "#A51D24"
            try:
                self._btn_auto_run.configure(text=label, fg_color=color)
            except Exception:
                pass

    def get_root(self) -> Optional[tk.Tk]:
        """Get the root window."""
        return self._root

    def get_port_table(self) -> Optional[PortStatusTable]:
        """Get the port status table."""
        return self._port_table

    def mainloop(self) -> None:
        """Start the main event loop."""
        if self._root:
            self._root.mainloop()
