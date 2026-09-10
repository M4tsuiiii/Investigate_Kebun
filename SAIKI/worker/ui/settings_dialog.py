"""Settings Dialog — configuration UI aligned with SAIKI architecture (Sprint 15).

Four sections:
  A. Modem — scan interval, validation timeout, default baud rate, fallback baud, auto-run
  B. Workflow — check data, reactivate fast, reactivate full, verify grace
  C. Database — NIK lookup, KK lookup
  D. Gateway — Telegram, notification

All settings changes publish events to the Event Bus.
Save button publishes SAVE_CONFIG event and persists to disk.

Sprint 15Q: Modem section shows default baud rate, fallback baud toggle,
and detected baud per verified modem (Config only).
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, Optional


CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "configs")
CONFIG_FILE = os.path.join(CONFIG_DIR, "saiki_config.json")


def load_config() -> Dict[str, Any]:
    """Load config from disk. Returns defaults if not found."""
    defaults = {
        "modem": {
            "scan_interval": 3.0,
            "validation_timeout": 2.0,
            "default_baud_rate": 115200,  # Sprint 15Q: single default baud
            "fallback_baud_enabled": False,  # Sprint 15Q: fallback baud probing
            "baud_rates": [9600, 19200, 115200],  # Kept for backward compat
            "auto_run": False,
            "detected_modems": {},  # Sprint 15Q: {port_id: {"baud_rate": 115200}}
        },
        "workflow": {
            "check_data": True,
            "reactivate_fast": True,
            "reactivate_full": True,
            "verify_grace": True,
            "number_ussd_code": "",  # Sprint 15S.2: configurable USSD for Cek Nomor fallback
        },
        "database": {
            "nik_lookup_enabled": True,
            "kk_lookup_enabled": True,
        },
        "gateway": {
            "telegram_enabled": False,
            "telegram_token": "",
            "notification_enabled": False,
        },
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Merge with defaults (saved overrides defaults)
            for section in defaults:
                if section not in saved:
                    saved[section] = defaults[section]
                else:
                    for key in defaults[section]:
                        if key not in saved[section]:
                            saved[section][key] = defaults[section][key]
            return saved
    except Exception:
        pass
    return defaults


def save_config(config: Dict[str, Any]) -> bool:
    """Persist config to disk. Returns True on success."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


class SettingsDialog:
    """Settings dialog with 4 sections matching SAIKI architecture.

    Section A: Modem (scan, validation, baud, auto-run, detected modems)
    Section B: Workflow (check, reactivate, verify)
    Section C: Database (NIK, KK lookup)
    Section D: Gateway (Telegram, notification)
    """

    def __init__(self, parent: tk.Widget, event_bus, settings: Dict[str, Any]):
        self._parent = parent
        self._event_bus = event_bus
        self._settings = settings.copy()

        # Section A: Modem
        self._var_scan_interval: Optional[tk.StringVar] = None
        self._var_val_timeout: Optional[tk.StringVar] = None
        self._var_default_baud: Optional[tk.StringVar] = None
        self._var_fallback_baud: Optional[tk.BooleanVar] = None
        self._var_baud_rates: Optional[tk.StringVar] = None
        self._var_auto_run: Optional[tk.BooleanVar] = None

        # Section B: Workflow
        self._var_check_data: Optional[tk.BooleanVar] = None
        self._var_reactivate_fast: Optional[tk.BooleanVar] = None
        self._var_reactivate_full: Optional[tk.BooleanVar] = None
        self._var_verify_grace: Optional[tk.BooleanVar] = None
        self._var_number_ussd: Optional[tk.StringVar] = None  # Sprint 15S.2

        # Section C: Database
        self._var_nik_lookup: Optional[tk.BooleanVar] = None
        self._var_kk_lookup: Optional[tk.BooleanVar] = None

        # Section D: Gateway
        self._var_telegram_enabled: Optional[tk.BooleanVar] = None
        self._var_telegram_token: Optional[tk.StringVar] = None
        self._var_notification: Optional[tk.BooleanVar] = None

    def build(self, container: tk.Widget) -> None:
        """Build the settings view inside the given container."""
        modem = self._settings.get("modem", {})
        workflow = self._settings.get("workflow", {})
        database = self._settings.get("database", {})
        gateway = self._settings.get("gateway", {})

        self._var_scan_interval = tk.StringVar(value=str(modem.get("scan_interval", 3.0)))
        self._var_val_timeout = tk.StringVar(value=str(modem.get("validation_timeout", 2.0)))
        self._var_default_baud = tk.StringVar(value=str(modem.get("default_baud_rate", 115200)))
        self._var_fallback_baud = tk.BooleanVar(value=modem.get("fallback_baud_enabled", False))
        self._var_baud_rates = tk.StringVar(value=str(modem.get("baud_rates", [9600, 19200, 115200])))
        self._var_auto_run = tk.BooleanVar(value=modem.get("auto_run", False))

        self._var_check_data = tk.BooleanVar(value=workflow.get("check_data", True))
        self._var_reactivate_fast = tk.BooleanVar(value=workflow.get("reactivate_fast", True))
        self._var_reactivate_full = tk.BooleanVar(value=workflow.get("reactivate_full", True))
        self._var_verify_grace = tk.BooleanVar(value=workflow.get("verify_grace", True))
        self._var_number_ussd = tk.StringVar(value=workflow.get("number_ussd_code", ""))  # Sprint 15S.2

        self._var_nik_lookup = tk.BooleanVar(value=database.get("nik_lookup_enabled", True))
        self._var_kk_lookup = tk.BooleanVar(value=database.get("kk_lookup_enabled", True))

        self._var_telegram_enabled = tk.BooleanVar(value=gateway.get("telegram_enabled", False))
        self._var_telegram_token = tk.StringVar(value=gateway.get("telegram_token", ""))
        self._var_notification = tk.BooleanVar(value=gateway.get("notification_enabled", False))

        try:
            import customtkinter as ctk
        except ImportError:
            ctk = None

        if ctk is None:
            self._build_ttk(container)
            return

        # Scrollable container
        scrollable = ctk.CTkScrollableFrame(container, fg_color="#F5EFEB")
        scrollable.pack(fill="both", expand=True, padx=5, pady=5)

        # ── Section A: Modem ──
        sec_a = ctk.CTkFrame(scrollable, corner_radius=10, fg_color="#FFFFFF")
        sec_a.pack(fill="x", padx=5, pady=(5, 10))
        inner_a = ctk.CTkFrame(sec_a, fg_color="transparent")
        inner_a.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(inner_a, text="SECTION A — MODEM", font=("Helvetica", 12, "bold"), text_color="#2F4156").pack(anchor="w", pady=(0, 8))

        row = ctk.CTkFrame(inner_a, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text="Scan Interval (s):", font=("Helvetica", 11), text_color="#2F4156").pack(side="left", padx=(0, 10))
        ctk.CTkEntry(row, textvariable=self._var_scan_interval, width=80).pack(side="left")

        row2 = ctk.CTkFrame(inner_a, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        ctk.CTkLabel(row2, text="Validation Timeout (s):", font=("Helvetica", 11), text_color="#2F4156").pack(side="left", padx=(0, 10))
        ctk.CTkEntry(row2, textvariable=self._var_val_timeout, width=80).pack(side="left")

        row3 = ctk.CTkFrame(inner_a, fg_color="transparent")
        row3.pack(fill="x", pady=2)
        ctk.CTkLabel(row3, text="Default Baud Rate:", font=("Helvetica", 11), text_color="#2F4156").pack(side="left", padx=(0, 10))
        ctk.CTkEntry(row3, textvariable=self._var_default_baud, width=100).pack(side="left")
        ctk.CTkLabel(row3, text="(Quectel M26 = 115200)", font=("Helvetica", 9), text_color="#888888").pack(side="left", padx=(10, 0))

        row_fb = ctk.CTkFrame(inner_a, fg_color="transparent")
        row_fb.pack(fill="x", pady=2)
        ctk.CTkCheckBox(row_fb, text="Fallback Baud Probing (future)", variable=self._var_fallback_baud, text_color="#2F4156").pack(side="left")

        # Detected modems display (read-only, Config only)
        detected = modem.get("detected_modems", {})
        if detected:
            row_det = ctk.CTkFrame(inner_a, fg_color="transparent")
            row_det.pack(fill="x", pady=(8, 2))
            ctk.CTkLabel(row_det, text="Detected Modems:", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w")
            for port_id, info in detected.items():
                baud = info.get("baud_rate", "?") if isinstance(info, dict) else "?"
                row_m = ctk.CTkFrame(inner_a, fg_color="transparent")
                row_m.pack(fill="x", pady=1)
                ctk.CTkLabel(row_m, text=f"  {port_id}", font=("Helvetica", 10), text_color="#2F4156").pack(side="left")
                ctk.CTkLabel(row_m, text=f"  baud={baud}", font=("Helvetica", 10), text_color="#567C8D").pack(side="left", padx=(10, 0))

        ctk.CTkCheckBox(inner_a, text="Auto Run", variable=self._var_auto_run, text_color="#2F4156").pack(anchor="w", pady=(8, 2))

        # ── Section B: Workflow ──
        sec_b = ctk.CTkFrame(scrollable, corner_radius=10, fg_color="#FFFFFF")
        sec_b.pack(fill="x", padx=5, pady=(0, 10))
        inner_b = ctk.CTkFrame(sec_b, fg_color="transparent")
        inner_b.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(inner_b, text="SECTION B — WORKFLOW", font=("Helvetica", 12, "bold"), text_color="#2F4156").pack(anchor="w", pady=(0, 8))

        ctk.CTkCheckBox(inner_b, text="Check Data", variable=self._var_check_data, text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkCheckBox(inner_b, text="Reactivate Fast", variable=self._var_reactivate_fast, text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkCheckBox(inner_b, text="Reactivate Full", variable=self._var_reactivate_full, text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkCheckBox(inner_b, text="Verify Grace", variable=self._var_verify_grace, text_color="#2F4156").pack(anchor="w", pady=2)

        # Sprint 15S.2: Number-check USSD code
        ctk.CTkLabel(inner_b, text="Number-check USSD Code (Cek Nomor fallback):",
                     font=("Helvetica", 10), text_color="#567C8D").pack(anchor="w", pady=(8, 2))
        ctk.CTkEntry(inner_b, textvariable=self._var_number_ussd, width=250,
                     placeholder_text="e.g. *123*30#",
                     font=("Helvetica", 10)).pack(anchor="w", pady=(0, 4))

        # ── Section C: Database ──
        sec_c = ctk.CTkFrame(scrollable, corner_radius=10, fg_color="#FFFFFF")
        sec_c.pack(fill="x", padx=5, pady=(0, 10))
        inner_c = ctk.CTkFrame(sec_c, fg_color="transparent")
        inner_c.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(inner_c, text="SECTION C — DATABASE", font=("Helvetica", 12, "bold"), text_color="#2F4156").pack(anchor="w", pady=(0, 8))

        ctk.CTkCheckBox(inner_c, text="NIK Lookup", variable=self._var_nik_lookup, text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkCheckBox(inner_c, text="KK Lookup", variable=self._var_kk_lookup, text_color="#2F4156").pack(anchor="w", pady=2)

        # ── Section D: Gateway ──
        sec_d = ctk.CTkFrame(scrollable, corner_radius=10, fg_color="#FFFFFF")
        sec_d.pack(fill="x", padx=5, pady=(0, 10))
        inner_d = ctk.CTkFrame(sec_d, fg_color="transparent")
        inner_d.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(inner_d, text="SECTION D — GATEWAY", font=("Helvetica", 12, "bold"), text_color="#2F4156").pack(anchor="w", pady=(0, 8))

        ctk.CTkCheckBox(inner_d, text="Telegram Enabled", variable=self._var_telegram_enabled, text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkLabel(inner_d, text="Telegram Token:", font=("Helvetica", 11), text_color="#2F4156").pack(anchor="w", pady=(4, 2))
        ctk.CTkEntry(inner_d, textvariable=self._var_telegram_token, width=300, show="*").pack(fill="x", pady=2)
        ctk.CTkCheckBox(inner_d, text="Notification Enabled", variable=self._var_notification, text_color="#2F4156").pack(anchor="w", pady=(8, 2))

        # ── Save Button ──
        ctk.CTkButton(
            scrollable, text="Save & Reload Configuration",
            fg_color="#2F4156", text_color="#FFFFFF",
            font=("Helvetica", 12, "bold"), command=self._on_save,
        ).pack(fill="x", pady=(10, 5), padx=5)

    def _build_ttk(self, container: tk.Widget) -> None:
        """Fallback ttk-based settings view."""
        frame = ttk.Frame(container)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frame, text="Scan Interval (s):").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(frame, textvariable=self._var_scan_interval, width=10).grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(frame, text="Auto Run:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(frame, variable=self._var_auto_run).grid(row=1, column=1, padx=5, pady=2)

        ttk.Button(frame, text="Save", command=self._on_save).grid(row=10, column=0, columnspan=2, pady=10)

    def _collect_settings(self) -> Dict[str, Any]:
        """Collect current UI values into a settings dict."""
        settings = dict(self._settings)
        settings["modem"] = {
            "scan_interval": float(self._var_scan_interval.get() if self._var_scan_interval else 3.0),
            "validation_timeout": float(self._var_val_timeout.get() if self._var_val_timeout else 2.0),
            "default_baud_rate": int(self._var_default_baud.get() if self._var_default_baud else 115200),
            "fallback_baud_enabled": self._var_fallback_baud.get() if self._var_fallback_baud else False,
            "baud_rates": [int(x.strip()) for x in (self._var_baud_rates.get() if self._var_baud_rates else "9600,19200,115200").replace("[", "").replace("]", "").split(",")],
            "auto_run": self._var_auto_run.get() if self._var_auto_run else False,
            "detected_modems": self._settings.get("modem", {}).get("detected_modems", {}),
        }
        settings["workflow"] = {
            "check_data": self._var_check_data.get() if self._var_check_data else True,
            "reactivate_fast": self._var_reactivate_fast.get() if self._var_reactivate_fast else True,
            "reactivate_full": self._var_reactivate_full.get() if self._var_reactivate_full else True,
            "verify_grace": self._var_verify_grace.get() if self._var_verify_grace else True,
            "number_ussd_code": self._var_number_ussd.get() if self._var_number_ussd else "",  # Sprint 15S.2
        }
        settings["database"] = {
            "nik_lookup_enabled": self._var_nik_lookup.get() if self._var_nik_lookup else True,
            "kk_lookup_enabled": self._var_kk_lookup.get() if self._var_kk_lookup else True,
        }
        settings["gateway"] = {
            "telegram_enabled": self._var_telegram_enabled.get() if self._var_telegram_enabled else False,
            "telegram_token": self._var_telegram_token.get() if self._var_telegram_token else "",
            "notification_enabled": self._var_notification.get() if self._var_notification else False,
        }
        return settings

    def _on_save(self) -> None:
        """Collect settings, save to disk, and publish save event."""
        from .events import CommandEvent
        settings = self._collect_settings()
        self._settings = settings

        # Persist to disk
        saved = save_config(settings)

        # Publish to event bus (controller handles reload)
        self._event_bus.publish(CommandEvent.SAVE_CONFIG.value, {"settings": settings})

        if saved:
            messagebox.showinfo("Hot-Reload", "Konfigurasi Berhasil Disimpan & Diperbarui!")
        else:
            messagebox.showwarning("Warning", "Konfigurasi diperbarui tapi gagal menyimpan ke disk.")

    def get_settings(self) -> Dict[str, Any]:
        """Get current settings values."""
        return self._collect_settings()
