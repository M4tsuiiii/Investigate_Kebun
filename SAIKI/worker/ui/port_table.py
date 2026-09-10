"""Port Status Table — treeview widget for port monitoring.

Renders port data in a table with 8 columns:
PORT, NOMOR, NIK, KK, STATUS, RESPON, MASA AKTIF, LOG

Thread-safe: worker threads enqueue updates, main thread applies.

Sprint 15R.1: All rows sorted numerically after every mutation.
Sprint 15R.1: Neutral states (NOT_INSERTED/NOT_READY/UNKNOWN/CHECKING/IDLE/STANDBY)
              display as IDLE with RESPON = "-".
"""

from __future__ import annotations

import re as _re
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional

from .update_queue import UpdateQueue


def _com_sort_key(port_name: str) -> int:
    """Extract numeric COM number for sorting. COM9 < COM10 < COM101."""
    m = _re.search(r'(\d+)', str(port_name))
    return int(m.group(1)) if m else 0


# Neutral/non-operational states → IDLE presentation
_NEUTRAL_STATUSES = frozenset({
    "IDLE", "STANDBY", "NOT_INSERTED", "NOT_READY",
    "UNKNOWN", "CHECKING", "OFF",
})


class PortStatusTable:
    """Treeview-based port status table.

    Zero business logic. Pure rendering:
    - Receives data via update queue
    - Applies column updates with deduplication
    - Handles row coloring based on status
    - Always maintains numeric COM port order
    - Exposes selection for context menu
    """

    COLUMNS = ("port", "nomor", "nik", "kk", "status", "respon", "masa_aktif", "log")
    HEADINGS = {
        "port": "PORT",
        "nomor": "NOMOR",
        "nik": "NIK",
        "kk": "KK",
        "status": "STATUS",
        "respon": "RESPON",
        "masa_aktif": "MASA AKTIF",
        "log": "LOG",
    }
    COLUMN_WIDTHS = {
        "port": (88, 80, False),
        "nomor": (100, 100, False),
        "nik": (120, 120, False),
        "kk": (120, 120, False),
        "status": (92, 80, False),
        "respon": (380, 200, True),
        "masa_aktif": (90, 90, False),
        "log": (56, 50, False),
    }
    COL_MAP = {"port_display": 0, "nomor": 1, "nik": 2, "kk": 3, "status": 4, "respon": 5, "masa_aktif": 6}

    STATUS_TAGS = {
        "sukses": ("sukses", "#E2F0D9", "#276A3C"),
        "done": ("done", "#E2F0D9", "#276A3C"),
        "proses": ("proses", "#D9E1F2", "#1F4E78"),
        "ready": ("proses", "#D9E1F2", "#1F4E78"),
        "stabilisasi": ("proses", "#D9E1F2", "#1F4E78"),
        "idle": ("idle", "#F5F5F5", "#666666"),
        "off": ("off", "#F0F0F0", "#555555"),
        "gagal": ("gagal", "#FCE4D6", "#A51D24"),
        "disabled": ("disabled", "#E0E0E0", "#999999"),
    }

    DEFAULT_ROW = ["-", "-", "-", "-", "IDLE", "-", "-", "LOG"]

    def __init__(self, parent: tk.Widget, on_log_click: Optional[Callable[[str], None]] = None):
        self._parent = parent
        self._on_log_click = on_log_click
        self._row_cache: Dict[str, List[str]] = {}
        self._selected_port: Optional[str] = None

        self._frame = ttk.Frame(parent)
        self._tree: Optional[ttk.Treeview] = None
        self._scrollbar: Optional[ttk.Scrollbar] = None

        self._build()

    def _build(self) -> None:
        """Build the treeview widget."""
        self._tree = ttk.Treeview(
            self._frame,
            columns=self.COLUMNS,
            show="headings",
        )

        for col in self.COLUMNS:
            heading = self.HEADINGS[col]
            self._tree.heading(col, text=heading)
            w, min_w, stretch = self.COLUMN_WIDTHS[col]
            anchor = tk.CENTER if col != "respon" else tk.W
            self._tree.column(col, width=w, minwidth=min_w, stretch=stretch, anchor=anchor)

        self._tree.tag_configure("sukses", background="#E2F0D9", foreground="#276A3C")
        self._tree.tag_configure("done", background="#E2F0D9", foreground="#276A3C")
        self._tree.tag_configure("proses", background="#D9E1F2", foreground="#1F4E78")
        self._tree.tag_configure("gagal", background="#FCE4D6", foreground="#A51D24")
        self._tree.tag_configure("idle", background="#F5F5F5", foreground="#666666")
        self._tree.tag_configure("off", background="#F0F0F0", foreground="#555555")
        self._tree.tag_configure("disabled", background="#E0E0E0", foreground="#999999")

        self._scrollbar = ttk.Scrollbar(self._frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=self._scrollbar.set)

        self._tree.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")

        self._tree.bind("<Button-1>", self._on_left_click)
        self._tree.bind("<Button-3>", self._on_right_click)

    @property
    def widget(self) -> ttk.Treeview:
        """The underlying treeview widget."""
        return self._tree

    @property
    def frame(self) -> ttk.Frame:
        """The container frame."""
        return self._frame

    @property
    def selected_port(self) -> Optional[str]:
        """Currently selected port name."""
        return self._selected_port

    def pack(self, **kwargs) -> None:
        """Pack the table frame."""
        self._frame.pack(**kwargs)

    def grid(self, **kwargs) -> None:
        """Grid the table frame."""
        self._frame.grid(**kwargs)

    # ------------------------------------------------------------------
    # Task 3: Neutral state presentation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_status(status: str) -> str:
        """Map neutral/non-operational states to IDLE for display.

        READY, PROCESSING, workflow-specific progress, SUCCESS, FAILED,
        and genuine connection errors retain their existing presentation.
        """
        if status in _NEUTRAL_STATUSES:
            return "IDLE"
        return status

    @staticmethod
    def _normalize_respon(status: str, respon: str) -> str:
        """Set RESPON = '-' for neutral states. Preserve actual results otherwise."""
        if status in _NEUTRAL_STATUSES:
            return "-"
        return respon

    # ------------------------------------------------------------------
    # Task 1: Numeric reorder
    # ------------------------------------------------------------------

    def _reorder_treeview(self) -> None:
        """Reorder all Treeview rows to numeric COM-port ascending order.

        Non-destructive: uses tree.move() to reposition items.
        Preserves row values, tags, selection, scroll position.
        """
        if not self._tree or not self._tree.winfo_exists():
            return

        children = list(self._tree.get_children())
        if len(children) <= 1:
            return

        sorted_children = sorted(children, key=_com_sort_key)
        if children == sorted_children:
            return  # Already in correct order

        # Preserve selection
        try:
            sel = self._tree.selection()
        except Exception:
            sel = ()

        for index, iid in enumerate(sorted_children):
            try:
                self._tree.move(iid, "", index)
            except Exception:
                pass

        # Restore selection
        if sel:
            try:
                self._tree.selection_set(sel)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Row operations
    # ------------------------------------------------------------------

    def insert_row(self, port: str, values: List[str]) -> None:
        """Insert a new row. Main thread only.

        Sprint 15R.1: Normalizes neutral states and reorders numerically.
        """
        if not self._tree or not self._tree.winfo_exists():
            return
        if self._tree.exists(port):
            return

        # Normalize neutral states
        status = values[4] if len(values) > 4 else "IDLE"
        respon = values[5] if len(values) > 5 else "-"
        norm_status = self._normalize_status(status)
        norm_respon = self._normalize_respon(status, respon)
        values = list(values)
        values[4] = norm_status
        values[5] = norm_respon

        self._row_cache[port] = list(values)
        self._tree.insert("", tk.END, iid=port, values=values)
        self._apply_row_tag(port, norm_status)
        self._reorder_treeview()

    def update_cell(self, port: str, column: str, value: Any) -> None:
        """Update a single cell. Main thread only.

        Sprint 15R.1: Normalizes neutral states, reorders if new row inserted.
        """
        if not self._tree or not self._tree.winfo_exists():
            return

        col_idx = self.COL_MAP.get(column)
        if col_idx is None:
            return

        # Normalize neutral states for status column
        if column == "status":
            value = self._normalize_status(str(value))
        elif column == "respon":
            # Check current status to decide if respon should be normalized
            cached = self._row_cache.get(port, list(self.DEFAULT_ROW))
            current_status = cached[4] if len(cached) > 4 else "IDLE"
            if current_status in _NEUTRAL_STATUSES or value in ("Idle/Standby", "SIM Not Inserted", "SIM Not Ready", "Detecting SIM"):
                value = self._normalize_respon(current_status, str(value))

        cached = self._row_cache.get(port, list(self.DEFAULT_ROW))
        while len(cached) < 7:
            cached.append("-")
        cached[col_idx] = str(value)
        self._row_cache[port] = cached

        existed = self._tree.exists(port)
        try:
            if not existed:
                self._tree.insert("", tk.END, iid=port, values=cached)
                self._apply_row_tag(port, cached[4])
                self._reorder_treeview()
                return
            self._tree.item(port, values=cached)
            if column == "status":
                self._apply_row_tag(port, str(value))
        except Exception:
            pass

    def delete_row(self, port: str) -> None:
        """Delete a row. Main thread only."""
        if not self._tree or not self._tree.winfo_exists():
            return
        self._row_cache.pop(port, None)
        try:
            if self._tree.exists(port):
                self._tree.delete(port)
        except Exception:
            pass

    def restore_from_cache(self, port_states: Dict[str, Dict[str, Any]], filter_fn: Optional[Callable[[str], bool]] = None) -> None:
        """Redraw all rows from cached state. Main thread only.

        Sprint 15R.1: Always sorts numerically. Normalizes neutral states.
        """
        if not self._tree or not self._tree.winfo_exists():
            return
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._row_cache.clear()

        for port in sorted(port_states, key=_com_sort_key):
            if filter_fn and not filter_fn(port):
                continue
            state = port_states[port]
            raw_status = state.get("status", "IDLE")
            norm_status = self._normalize_status(raw_status)
            norm_respon = self._normalize_respon(raw_status, state.get("respon", "-"))
            values = [
                state.get("port_display", "-"),
                state.get("nomor", "-"),
                state.get("nik", "-"),
                state.get("kk", "-"),
                norm_status,
                norm_respon,
                state.get("masa_aktif", "-"),
                "LOG",
            ]
            self.insert_row(port, values)

    def _apply_row_tag(self, port: str, status_text: str) -> None:
        """Apply color tag based on status text."""
        if not self._tree or not self._tree.winfo_exists():
            return
        txt = (status_text or "").lower()
        tag = "idle"
        for keyword, (tag_name, _, _) in self.STATUS_TAGS.items():
            if keyword in txt:
                tag = tag_name
                break
        if txt == "off":
            tag = "off"
        try:
            self._tree.item(port, tags=(tag,))
        except Exception:
            pass

    def _on_left_click(self, event) -> None:
        """Handle left click — trigger log popup on LOG column."""
        try:
            item = self._tree.identify_row(event.y)
            column = self._tree.identify_column(event.x)
            if item and column == "#8" and self._on_log_click:
                self._on_log_click(item)
        except Exception:
            pass

    def _on_right_click(self, event) -> None:
        """Handle right click — select row and store selection."""
        try:
            item = self._tree.identify_row(event.y)
            if item:
                self._tree.selection_set(item)
                self._selected_port = item
        except Exception:
            pass

    def get_selection(self) -> Optional[str]:
        """Get the currently selected port."""
        return self._selected_port

    def exists(self, port: str) -> bool:
        """Check if a row exists."""
        if not self._tree or not self._tree.winfo_exists():
            return False
        return self._tree.exists(port)
