# CONFIG_MAPPING.md — Sprint 15 Config UX Refactor

Maps each Settings UI field → JSON config key → Consumer module.

## Section A: Modem Settings

| UI Field | Config Key | Default | Consumer |
|---|---|---|---|
| Scan Interval | `modem.scan_interval` | `3.0` | `worker_manager.py` → `_scan_ports_raw()` |
| Validation Timeout | `modem.validation_timeout` | `2.0` | `modem_validator.py` → `_validate_with_baud_detection()` |
| Baud Rates | `modem.baud_rates` | `[9600, 19200, 115200]` | `modem_validator.py` → `ModemValidator(baud_rates=...)` |
| Auto-Run | `modem.auto_run` | `False` | `controller.py` → `_handle_save_config()` → `AutoRunConfig` |

## Section B: Workflow Settings

| UI Field | Config Key | Default | Consumer |
|---|---|---|---|
| Cek Data | `workflow.check_data` | `True` | `rules.py` → `AutoRunConfig.check_data` |
| Aktifkan Ulang (Fast) | `workflow.reactivate_fast` | `True` | `rules.py` → `AutoRunConfig.reactivate_fast` |
| Aktifkan Ulang (Full) | `workflow.reactivate_full` | `True` | `rules.py` → `AutoRunConfig.reactivate_full` |
| Verifikasi Grace Period | `workflow.verify_grace` | `True` | `rules.py` → `AutoRunConfig.verify_grace` |

## Section C: Database Settings

| UI Field | Config Key | Default | Consumer |
|---|---|---|---|
| Cek NIK Aktif | `database.nik_lookup_enabled` | `True` | `controller.py` → `_handle_db_lookup_nik()` |
| Cek KK Aktif | `database.kk_lookup_enabled` | `True` | `controller.py` → `_handle_db_lookup_kk()` |

## Section D: Gateway Settings

| UI Field | Config Key | Default | Consumer |
|---|---|---|---|
| Telegram Enabled | `gateway.telegram_enabled` | `False` | `worker_manager.py` → notification dispatch |
| Telegram Token | `gateway.telegram_token` | `""` | `worker_manager.py` → notification dispatch |
| Notification Enabled | `gateway.notification_enabled` | `False` | `worker_manager.py` → notification dispatch |

## Persistence

- **File**: `configs/saiki_config.json`
- **Format**: JSON
- **Load**: `worker/ui/settings_dialog.py` → `load_config()`
- **Save**: `worker/ui/settings_dialog.py` → `save_config(settings)`
- **Controller**: `worker/ui/controller.py` → `_handle_save_config()` applies `auto_run` to `AutoRunConfig` and publishes `ui.settings.changed`

## Default Config Structure

```json
{
  "modem": {
    "scan_interval": 3.0,
    "validation_timeout": 2.0,
    "baud_rates": [9600, 19200, 115200],
    "auto_run": false
  },
  "workflow": {
    "check_data": true,
    "reactivate_fast": true,
    "reactivate_full": true,
    "verify_grace": true
  },
  "database": {
    "nik_lookup_enabled": true,
    "kk_lookup_enabled": true
  },
  "gateway": {
    "telegram_enabled": false,
    "telegram_token": "",
    "notification_enabled": false
  }
}
```
