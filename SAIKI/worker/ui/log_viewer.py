"""Log Viewer — popup window for viewing raw port logs.

Read-only text widget that displays log lines for a specific port.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional


class LogViewer:
    """Log viewer popup window.

    Zero business logic. Pure display:
    - Opens a Toplevel window
    - Displays log lines in a read-only text widget
    - Auto-scrolls to bottom
    """

    def __init__(self, parent: tk.Widget):
        self._parent = parent
        self._log_data: Dict[str, List[str]] = {}

    def set_log_data(self, port: str, lines: List[str]) -> None:
        """Store log data for a port."""
        self._log_data[port] = lines

    def show(self, port: str) -> None:
        """Open log viewer for the given port."""
        popup = tk.Toplevel(self._parent)
        popup.title(f"Log Raw - {port}")
        popup.geometry("700x400")
        popup.configure(bg="#2F4156")

        text = tk.Text(
            popup,
            bg="#2F4156",
            fg="#FFFFFF",
            font=("Courier", 10),
            wrap=tk.WORD,
        )
        text.pack(fill="both", expand=True)

        lines = self._log_data.get(port, ["Belum ada data log."])
        for line in lines:
            text.insert(tk.END, line + "\n")
        text.config(state=tk.DISABLED)

        text.see(tk.END)

    def append_line(self, port: str, line: str) -> None:
        """Append a log line to the stored data."""
        if port not in self._log_data:
            self._log_data[port] = []
        self._log_data[port].append(line)

    def clear(self, port: Optional[str] = None) -> None:
        """Clear log data for a specific port or all ports."""
        if port:
            self._log_data.pop(port, None)
        else:
            self._log_data.clear()
