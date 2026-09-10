"""Context Menu system — right-click menu for port actions.

All menu actions publish events to the Event Bus.
Zero business logic — only event dispatch.

Sprint 15S.1: Per-port context actions with [COMMAND CLICK] traces.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Optional

from .events import CommandEvent

logger = logging.getLogger("saiki.ui.context_menu")


class PortContextMenu:
    """Right-click context menu for port table.

    Menu items matching original application:
    1. On Port
    2. Off Port
    3. Restart Port
    4. Reset Port
    5. Reprocess
    ---
    6. Cek Nomor        → CEK_NOMOR (per-port)
    7. Cek NIK          → CEK_NIK (per-port)
    8. Cari / Ambil KK  → CARI_KK (per-port)
    9. Reaktivasi       → REACTIVATE (per-port)
    10. Cek Limit       → CEK_NOMOR (per-port, same as Cek Nomor)
    ---
    11. Lookup Database (submenu: NIK, KK)
    """

    MENU_ITEMS = [
        ("On Port", CommandEvent.PORT_ON),
        ("Off Port", CommandEvent.PORT_OFF),
        ("Restart Port", CommandEvent.RESTART_PORT),
        ("Reset Port", CommandEvent.RESET_MODEM),
        ("Reprocess", CommandEvent.FORCE_RETRY),
        None,  # separator
        ("Cek Nomor", CommandEvent.CEK_NOMOR),
        ("Cek Status SIM", CommandEvent.CEK_STATUS),
        ("Cek NIK", CommandEvent.CEK_NIK),
        ("Cari / Ambil KK", CommandEvent.CARI_KK),
        ("Reaktivasi", CommandEvent.REACTIVATE),
        ("Cek Limit", CommandEvent.CEK_LIMIT),
        None,  # separator
    ]

    def __init__(self, parent, event_bus):
        self._parent = parent
        self._event_bus = event_bus
        self._menu: Optional[tk.Menu] = None
        self._selected_port: Optional[str] = None

        self._build()

    def _build(self) -> None:
        """Build the context menu."""
        self._menu = tk.Menu(self._parent, tearoff=0)

        for item in self.MENU_ITEMS:
            if item is None:
                self._menu.add_separator()
            else:
                label, command = item
                self._menu.add_command(
                    label=label,
                    command=lambda cmd=command: self._on_menu_click(cmd),
                )

        # Lookup Database submenu
        self._menu.add_separator()
        lookup_menu = tk.Menu(self._menu, tearoff=0)
        lookup_menu.add_command(
            label="Lookup by NIK",
            command=lambda: self._on_lookup("nik"),
        )
        lookup_menu.add_command(
            label="Lookup by KK",
            command=lambda: self._on_lookup("kk"),
        )
        self._menu.add_cascade(label="Lookup Database", menu=lookup_menu)

    def _on_menu_click(self, command) -> None:
        """Publish command event with selected port."""
        import threading
        if self._selected_port:
            logger.info("[COMMAND CLICK] COMMAND=%s PORT=%s SOURCE=context_menu THREAD=%s",
                         command.value, self._selected_port, threading.current_thread().name)
            self._event_bus.publish(command.value, {
                "port": self._selected_port,
                "_event_name": command.value,
                "source": "context_menu",
            })

    def _on_lookup(self, lookup_type: str) -> None:
        """Publish database lookup event with selected port."""
        if self._selected_port:
            event = CommandEvent.DB_LOOKUP_NIK if lookup_type == "nik" else CommandEvent.DB_LOOKUP_KK
            self._event_bus.publish(event.value, {"port": self._selected_port})

    def show(self, port: str, x: int, y: int) -> None:
        """Show the context menu at the given position."""
        self._selected_port = port
        if self._menu:
            try:
                self._menu.post(x, y)
            except Exception:
                pass

    def hide(self) -> None:
        """Hide the context menu."""
        if self._menu:
            try:
                self._menu.grab_release()
            except Exception:
                pass

    @property
    def selected_port(self) -> Optional[str]:
        """Currently selected port."""
        return self._selected_port
