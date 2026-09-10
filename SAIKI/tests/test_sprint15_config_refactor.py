"""Tests for Sprint 15 — Config UX Refactor.

Tests for: config load, config save, persistence, validation, reload, default values.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from worker.rules import AutoRunConfig
from worker.ui.settings_dialog import SettingsDialog, load_config, save_config, CONFIG_FILE


# ------------------------------------------------------------------
# 1. Load Config
# ------------------------------------------------------------------

class TestLoadConfig(unittest.TestCase):
    """Test config loading from disk."""

    def test_load_config_returns_defaults_when_no_file(self):
        """load_config returns defaults when no config file exists."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path/config.json"):
            config = load_config()

        self.assertIn("modem", config)
        self.assertIn("workflow", config)
        self.assertIn("database", config)
        self.assertIn("gateway", config)

    def test_load_config_defaults_modem(self):
        """Default modem config has expected keys."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path/config.json"):
            config = load_config()

        modem = config["modem"]
        self.assertEqual(modem["scan_interval"], 3.0)
        self.assertEqual(modem["validation_timeout"], 2.0)
        self.assertEqual(modem["baud_rates"], [9600, 19200, 115200])
        self.assertFalse(modem["auto_run"])

    def test_load_config_defaults_workflow(self):
        """Default workflow config has all workflows enabled."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path/config.json"):
            config = load_config()

        workflow = config["workflow"]
        self.assertTrue(workflow["check_data"])
        self.assertTrue(workflow["reactivate_fast"])
        self.assertTrue(workflow["reactivate_full"])
        self.assertTrue(workflow["verify_grace"])

    def test_load_config_defaults_database(self):
        """Default database config has lookups enabled."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path/config.json"):
            config = load_config()

        database = config["database"]
        self.assertTrue(database["nik_lookup_enabled"])
        self.assertTrue(database["kk_lookup_enabled"])

    def test_load_config_defaults_gateway(self):
        """Default gateway config has telegram disabled."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path/config.json"):
            config = load_config()

        gateway = config["gateway"]
        self.assertFalse(gateway["telegram_enabled"])
        self.assertEqual(gateway["telegram_token"], "")
        self.assertFalse(gateway["notification_enabled"])


# ------------------------------------------------------------------
# 2. Save Config
# ------------------------------------------------------------------

class TestSaveConfig(unittest.TestCase):
    """Test config saving to disk."""

    def test_save_config_creates_file(self):
        """save_config creates the config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.json")
            with patch("worker.ui.settings_dialog.CONFIG_FILE", config_path):
                result = save_config({"modem": {"scan_interval": 5.0}})

            self.assertTrue(result)
            self.assertTrue(os.path.exists(config_path))

    def test_save_config_content(self):
        """save_config writes correct JSON content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.json")
            with patch("worker.ui.settings_dialog.CONFIG_FILE", config_path):
                save_config({"modem": {"scan_interval": 5.0}})

            with open(config_path, "r") as f:
                saved = json.load(f)
            self.assertEqual(saved["modem"]["scan_interval"], 5.0)

    def test_save_config_invalid_path(self):
        """save_config returns False on invalid path."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/dir/config.json"):
            result = save_config({"test": True})
        self.assertFalse(result)


# ------------------------------------------------------------------
# 3. Persistence Round-Trip
# ------------------------------------------------------------------

class TestPersistenceRoundTrip(unittest.TestCase):
    """Test load → edit → save → reload cycle."""

    def test_round_trip(self):
        """Config survives a full load → save → load cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.json")
            with patch("worker.ui.settings_dialog.CONFIG_FILE", config_path):
                # Save custom config
                custom = {
                    "modem": {"scan_interval": 10.0, "auto_run": True},
                    "workflow": {"check_data": False},
                }
                save_config(custom)

                # Load it back
                loaded = load_config()

            self.assertEqual(loaded["modem"]["scan_interval"], 10.0)
            self.assertTrue(loaded["modem"]["auto_run"])
            self.assertFalse(loaded["workflow"]["check_data"])
            # Unspecified keys should be filled from defaults
            self.assertIn("reactivate_fast", loaded["workflow"])

    def test_partial_save_fills_defaults(self):
        """Partial config save fills missing keys from defaults on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.json")
            with patch("worker.ui.settings_dialog.CONFIG_FILE", config_path):
                # Save only modem section
                save_config({"modem": {"scan_interval": 7.0}})

                # Load — should have all sections
                loaded = load_config()

            self.assertEqual(loaded["modem"]["scan_interval"], 7.0)
            self.assertIn("workflow", loaded)
            self.assertIn("database", loaded)
            self.assertIn("gateway", loaded)


# ------------------------------------------------------------------
# 4. Config Validation
# ------------------------------------------------------------------

class TestConfigValidation(unittest.TestCase):
    """Test config value validation."""

    def test_scan_interval_is_float(self):
        """scan_interval is stored as float."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.json")
            with patch("worker.ui.settings_dialog.CONFIG_FILE", config_path):
                save_config({"modem": {"scan_interval": 5}})
                loaded = load_config()
            self.assertIsInstance(loaded["modem"]["scan_interval"], (int, float))

    def test_baud_rates_is_list(self):
        """baud_rates is stored as list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.json")
            with patch("worker.ui.settings_dialog.CONFIG_FILE", config_path):
                save_config({"modem": {"baud_rates": [9600, 115200]}})
                loaded = load_config()
            self.assertIsInstance(loaded["modem"]["baud_rates"], list)

    def test_boolean_fields_are_bool(self):
        """Boolean config fields are actual booleans."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path.json"):
            config = load_config()
        self.assertIsInstance(config["modem"]["auto_run"], bool)
        self.assertIsInstance(config["workflow"]["check_data"], bool)
        self.assertIsInstance(config["gateway"]["telegram_enabled"], bool)


# ------------------------------------------------------------------
# 5. SettingsDialog Collect
# ------------------------------------------------------------------

class TestSettingsDialogCollect(unittest.TestCase):
    """Test SettingsDialog._collect_settings()."""

    def _make_dialog(self, settings=None):
        """Create a minimal SettingsDialog for testing."""
        if settings is None:
            settings = load_config()
        parent = MagicMock()
        event_bus = MagicMock()
        dialog = SettingsDialog(parent, event_bus, settings)
        # Initialize tkinter vars
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        dialog._var_scan_interval = tk.StringVar(value="3.0")
        dialog._var_val_timeout = tk.StringVar(value="2.0")
        dialog._var_baud_rates = tk.StringVar(value="[9600, 19200, 115200]")
        dialog._var_auto_run = tk.BooleanVar(value=False)
        dialog._var_check_data = tk.BooleanVar(value=True)
        dialog._var_reactivate_fast = tk.BooleanVar(value=True)
        dialog._var_reactivate_full = tk.BooleanVar(value=True)
        dialog._var_verify_grace = tk.BooleanVar(value=True)
        dialog._var_nik_lookup = tk.BooleanVar(value=True)
        dialog._var_kk_lookup = tk.BooleanVar(value=True)
        dialog._var_telegram_enabled = tk.BooleanVar(value=False)
        dialog._var_telegram_token = tk.StringVar(value="")
        dialog._var_notification = tk.BooleanVar(value=False)
        root.destroy()
        return dialog

    def test_collect_settings_has_all_sections(self):
        """_collect_settings returns all 4 sections."""
        dialog = self._make_dialog()
        settings = dialog._collect_settings()
        self.assertIn("modem", settings)
        self.assertIn("workflow", settings)
        self.assertIn("database", settings)
        self.assertIn("gateway", settings)

    def test_collect_settings_modem_values(self):
        """_collect_settings returns correct modem values."""
        dialog = self._make_dialog()
        settings = dialog._collect_settings()
        self.assertEqual(settings["modem"]["scan_interval"], 3.0)
        self.assertEqual(settings["modem"]["validation_timeout"], 2.0)
        self.assertFalse(settings["modem"]["auto_run"])

    def test_collect_settings_workflow_values(self):
        """_collect_settings returns correct workflow values."""
        dialog = self._make_dialog()
        settings = dialog._collect_settings()
        self.assertTrue(settings["workflow"]["check_data"])
        self.assertTrue(settings["workflow"]["reactivate_fast"])


# ------------------------------------------------------------------
# 6. Default Values
# ------------------------------------------------------------------

class TestDefaultValues(unittest.TestCase):
    """Test that default config matches expected architecture."""

    def test_default_scan_interval(self):
        """Default scan interval is 3.0 seconds."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path.json"):
            config = load_config()
        self.assertEqual(config["modem"]["scan_interval"], 3.0)

    def test_default_baud_rates(self):
        """Default baud rates match GOOD-compatible order."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path.json"):
            config = load_config()
        self.assertEqual(config["modem"]["baud_rates"], [9600, 19200, 115200])

    def test_default_auto_run_off(self):
        """Default auto-run is OFF."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path.json"):
            config = load_config()
        self.assertFalse(config["modem"]["auto_run"])

    def test_all_workflows_enabled_by_default(self):
        """All workflows are enabled by default."""
        with patch("worker.ui.settings_dialog.CONFIG_FILE", "/nonexistent/path.json"):
            config = load_config()
        for key in ["check_data", "reactivate_fast", "reactivate_full", "verify_grace"]:
            self.assertTrue(config["workflow"][key], f"{key} should be True by default")


# ------------------------------------------------------------------
# 7. Controller Config Handling
# ------------------------------------------------------------------

class TestControllerConfigHandling(unittest.TestCase):
    """Test UIController._handle_save_config applies settings."""

    def test_save_config_applies_auto_run(self):
        """SAVE_CONFIG with auto_run applies to AutoRunConfig."""
        from worker.ui.controller import UIController

        event_bus = MagicMock()
        worker_manager = MagicMock()
        auto_run_config = AutoRunConfig()
        automation_engine = MagicMock()
        db_lookup = MagicMock()

        controller = UIController(event_bus, worker_manager, auto_run_config, automation_engine, db_lookup)

        # Save config with auto_run=True
        controller._handle_save_config({
            "settings": {"modem": {"auto_run": True}}
        })

        self.assertTrue(auto_run_config.auto_run_enabled)

    def test_save_config_publishes_settings_changed(self):
        """SAVE_CONFIG publishes SETTINGS_CHANGED event."""
        from worker.ui.controller import UIController

        event_bus = MagicMock()
        worker_manager = MagicMock()
        auto_run_config = AutoRunConfig()
        automation_engine = MagicMock()
        db_lookup = MagicMock()

        controller = UIController(event_bus, worker_manager, auto_run_config, automation_engine, db_lookup)
        controller._handle_save_config({"settings": {"modem": {"auto_run": False}}})

        event_bus.publish.assert_called()
        call_args = event_bus.publish.call_args
        self.assertEqual(call_args[0][0], "ui.settings.changed")


if __name__ == "__main__":
    unittest.main()
