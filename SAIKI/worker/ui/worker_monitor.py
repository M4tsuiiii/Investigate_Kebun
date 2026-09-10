"""Worker Monitor panel — displays worker status and provides controls.

Shows a summary of all active workers with their current state.
Provides action buttons for bulk operations.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, Optional


class WorkerMonitor:
    """Worker monitoring panel.

    Zero business logic. Pure UI:
    - Displays worker count and status summary
    - Provides action buttons (restart all, reset modem)
    - Updates footer label with port scan results
    """

    def __init__(self, parent: tk.Widget, event_bus=None):
        self._parent = parent
        self._event_bus = event_bus
        self._frame: Optional[ttk.Frame] = None
        self._footer_label: Optional[tk.Label] = None
        self._worker_count = 0
        self._active_count = 0
        self._off_count = 0
        self._excluded_count = 0

    def build(self, parent: tk.Widget) -> None:
        """Build the worker monitor panel."""
        self._footer_label = tk.Label(
            parent,
            text="SLOT ACTIVE PORT MONITOR: Initializing...",
            font=("Helvetica", 11, "bold"),
            fg="#2F4156",
            bg="#F5EFEB",
        )
        self._footer_label.pack(side="left")

    def update_footer(self, total: int, active: int, off: int, excluded: int = 0) -> None:
        """Update the footer label with port counts."""
        self._worker_count = total
        self._active_count = active
        self._off_count = off
        self._excluded_count = excluded
        if self._footer_label:
            if excluded > 0:
                self._footer_label.configure(
                    text=f"SLOT ACTIVE PORT MONITOR: {total} Slot COM Terdeteksi ({active} Aktif | {off} Mati | {excluded} Excluded)"
                )
            else:
                self._footer_label.configure(
                    text=f"SLOT ACTIVE PORT MONITOR: {total} Slot COM Terdeteksi ({active} Menyala | {off} Mati)"
                )

    def set_initializing(self) -> None:
        """Set footer to initializing state."""
        if self._footer_label:
            self._footer_label.configure(text="SLOT ACTIVE PORT MONITOR: Initializing...")

    def get_counts(self) -> Dict[str, int]:
        """Get current port counts."""
        return {
            "total": self._worker_count,
            "active": self._active_count,
            "off": self._off_count,
            "excluded": self._excluded_count,
        }
