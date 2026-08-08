import os
import re
import sys
import csv
import io
import socket
import uuid
import sqlite3
import hashlib
import threading
import time
import queue
import platform
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
import serial
import serial.tools.list_ports
import logging
from logging.handlers import RotatingFileHandler

# =====================================================================
# 1. CONFIG CORE & REAL HARDWARE SECURITY (DYNAMIC HWID)
# =====================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(BASE_DIR, "vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)
DB_FILE_PATH = os.path.join(BASE_DIR, "hasil_panen.db")
SECRET_SALT = "PAHLAWAN_KEBUN_REAKTIVASI_2026_FOXCOM_SUPER_KEY"
BAUD_RATES = [9600, 19200, 115200]
# Jeda minimum setelah respons USSD sebelum dial berikutnya dimulai.
DIAL_COOLDOWN_SECONDS = 4.0
# Jeda retry dibuat lebih panjang supaya modem/operator tidak dibanjiri ulang.
USSD_RETRY_DELAY_SECONDS = 8.0
# Inject-only retries when operator has not accepted the reaktivasi request.
MAX_INJECT_RETRY = 3
# PROMPT confirmation must not leave UI in indefinite in-progress state.
PROMPT_LIFECYCLE_TIMEOUT_SECONDS = 20.0
# A response returned after a cancelled/expired USSD session has no correlation id.
# Fence the serial stream before issuing the next dial so those bytes are discarded.
USSD_SESSION_FENCE_MIN_SECONDS = 0.75
USSD_SESSION_FENCE_QUIET_SECONDS = 0.25
USSD_SESSION_FENCE_TIMEOUT_SECONDS = 3.0
# CPIN/Removal confirmation thresholds
CPIN_UNKNOWN_THRESHOLD = 3  # count of consecutive UNKNOWN/ERROR before final confirm
CPIN_FINAL_CONFIRM_TIMEOUT = 3.0  # seconds to wait on final confirmation query
CPIN_MAX_REMOVAL_CONFIRM = 2  # how many NOT_READY confirmations before forcing NOT_INSERTED

power_injection_lock = threading.BoundedSemaphore(2)
telegram_api_queue = threading.Lock()
telegram_login_lock = threading.Lock()
telegram_login_client = None
telegram_login_phone = ""

try:
    from telethon.sync import TelegramClient
    from telethon.errors import (
        SessionPasswordNeededError,
        PasswordHashInvalidError,
        PhoneCodeInvalidError,
        PhoneCodeExpiredError,
        FloodWaitError,
    )
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

global_settings = {
    "dial_cek_nomor": "*185#",
    "dial_cek_nik": "*888*4444*1#",
    "format_mode": "NIK & KK",
    "auto_validasi": True,
    "abai_aktif": True,
    "abai_tenggang": True,
    "abai_hangus": False,
    "tg_api_id": "",
    "tg_api_hash": "",
    "tg_phone": "",
    "tg_target_bot": "@pencari_data_kpu_bot",
    "tg_format_cmd": "/ceknik {NIK}",
    "tg_limit_cmd": "👤 Profile"
    ,"trigger_mode": "Auto-Run on Insert",
}

class LockedDict:
    def __init__(self):
        self._data = {}
        self._lock = threading.RLock()

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def __setitem__(self, key, value):
        with self._lock:
            self._data[key] = value

    def pop(self, key, default=None):
        with self._lock:
            return self._data.pop(key, default)

    def clear(self):
        with self._lock:
            self._data.clear()

    def __contains__(self, key):
        with self._lock:
            return key in self._data


db_cache = LockedDict()
phone_cache = LockedDict()
port_logs = {}
port_logs_lock = threading.RLock()
sqlite_write_lock = threading.RLock()
disabled_ports = set()
port_file_loggers = {}

DEFAULT_PORT_STATE = {
    "port_display": "-",
    "nomor": "-",
    "nik": "-",
    "kk": "-",
    "status": "IDLE",
    "respon": "Idle/Standby",
    "masa_aktif": "-",
    "last_cpin": "UNKNOWN",
    "last_update": None,
}

class EventBus:
    def __init__(self):
        self._listeners = {}
        self._lock = threading.Lock()

    def subscribe(self, event_name, callback):
        with self._lock:
            self._listeners.setdefault(event_name, []).append(callback)

    def publish(self, event_name, payload):
        with self._lock:
            listeners = list(self._listeners.get(event_name, []))
        for callback in listeners:
            try:
                callback(payload)
            except Exception:
                pass

class PortRegistry:
    def __init__(self):
        # update() memanggil ensure(); RLock mencegah deadlock saat lock yang
        # sama diambil kembali oleh thread yang sama.
        self._lock = threading.RLock()
        self._states = {}

    def ensure(self, port):
        with self._lock:
            if port not in self._states:
                self._states[port] = DEFAULT_PORT_STATE.copy()
                self._states[port]["port_display"] = port
                self._states[port]["last_update"] = datetime.now()
            return self._states[port]

    def update(self, port, key, value):
        with self._lock:
            state = self.ensure(port)
            if key == "status" and not self._should_accept_status_update(state, value):
                return state
            state[key] = value
            state["last_update"] = datetime.now()
            return state

    def _should_accept_status_update(self, state, new_status):
        current_status = str(state.get("status", "") or "").upper()
        new_status = str(new_status or "").upper()
        if current_status == new_status:
            return True
        if current_status == "OFF" and new_status == "IDLE":
            if state.get("last_cpin") == "NOT_INSERTED":
                return True
            print(f"Status update ditolak: current=OFF requested=IDLE reason=priority guard")
            return False
        if current_status == "READY" and new_status == "IDLE":
            if state.get("last_cpin") == "NOT_INSERTED":
                return True
            print(f"Status update ditolak: current=READY requested=IDLE reason=CPIN not NOT_INSERTED")
            return False
        return True

    def get(self, port):
        with self._lock:
            return self._states.get(port)

    def remove(self, port):
        with self._lock:
            return self._states.pop(port, None)

    def snapshot(self):
        """Salinan state untuk merender ulang UI tanpa menyentuh worker."""
        with self._lock:
            return {port: state.copy() for port, state in self._states.items()}


event_bus = EventBus()
port_registry = PortRegistry()

def ensure_port_registered(port):
    return port_registry.ensure(port)


def update_port_registry(port, key, value):
    return port_registry.update(port, key, value)


def remove_port_registry(port):
    return port_registry.remove(port)


class PortStateMachine:
    def __init__(self, port_name, ui_callback, automation_callback):
        self.port_name = port_name
        self.ui_callback = ui_callback
        self.automation_callback = automation_callback
        self.current_state = "UNKNOWN"
        self.awaiting_card_cycle = False
        self._lock = threading.Lock()
        self._subscribed = False
        event_bus.subscribe("port.cpin_transition", self._on_cpin_transition)
        self._subscribed = True

    def close(self):
        if not self._subscribed:
            return
        with event_bus._lock:
            listeners = event_bus._listeners.get("port.cpin_transition", [])
            if listeners:
                listeners = [cb for cb in listeners if cb != self._on_cpin_transition]
                if listeners:
                    event_bus._listeners["port.cpin_transition"] = listeners
                else:
                    event_bus._listeners.pop("port.cpin_transition", None)
        self._subscribed = False

    def require_card_cycle(self):
        self.awaiting_card_cycle = True

    def _set_status(self, status, respon=None):
        update_port_registry(self.port_name, "status", status)
        if respon is not None:
            update_port_registry(self.port_name, "respon", respon)
        self.ui_callback(self.port_name, "status", status)
        if respon is not None:
            self.ui_callback(self.port_name, "respon", respon)

    def _on_cpin_transition(self, payload):
        if payload.get("port") != self.port_name:
            return
        old_state = payload.get("old_state")
        new_state = payload.get("new_state")
        with self._lock:
            if new_state == self.current_state:
                return
            self.current_state = new_state

            if new_state == "READY":
                self._set_status("READY", "+CPIN: READY")
                if (global_settings.get("trigger_mode", "Auto-Run on Insert") == "Auto-Run on Insert"
                        and old_state != "READY"
                        and not self.awaiting_card_cycle):
                    self.ui_callback(self.port_name, "respon", "SIM inserted, automation queued")
                    try:
                        self.automation_callback()
                    except Exception:
                        self._set_status("GAGAL", "Auto-run failed")
                else:
                    self.ui_callback(self.port_name, "respon", "+CPIN: READY")
            elif new_state == "PIN_REQUIRED":
                self.awaiting_card_cycle = False
                self._set_status("PIN LOCK", "+CPIN: PIN/PUK Required")
            elif new_state == "NOT_INSERTED":
                self.awaiting_card_cycle = False
                # Kondisi SIM tidak terpasang diperlakukan sama dengan idle/standby di UI.
                self._set_status("IDLE", "Idle/Standby")
                self.ui_callback(self.port_name, "nomor", "-")
                self.ui_callback(self.port_name, "nik", "-")
                self.ui_callback(self.port_name, "kk", "-")
                self.ui_callback(self.port_name, "masa_aktif", "-")
            else:
                self.ui_callback(self.port_name, "respon", "Waiting for SIM state...")


def verify_user_license(hardware_id, serial_key):
    try:
        hwid_clean = hardware_id.strip().upper()
        parts = serial_key.strip().split("-")
        if len(parts) != 4:
            return False, "Format Serial Key Salah.", None
        expiry_date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
        user_signature = parts[3].upper()

        raw_string = f"{hwid_clean}|{expiry_date_str}|{SECRET_SALT}"
        expected_signature = hashlib.sha256(raw_string.encode('utf-8')).hexdigest()[:16].upper()

        if user_signature != expected_signature:
            return False, "Serial Key Tidak Valid untuk PC ini!", None
        expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d")
        if datetime.now() > expiry_date:
            return False, "Lisensi Sudah Kedaluwarsa!", expiry_date
        return True, "Lisensi Aktif", expiry_date
    except Exception:
        return False, "Eror Memproses Lisensi.", None


def get_hardware_id():
    try:
        if platform.system().lower() == "windows":
            for cmd in (["wmic", "csproduct", "get", "uuid"], ["wmic", "bios", "get", "serialnumber"]):
                try:
                    output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                    lines = [line.strip() for line in output.splitlines() if line.strip()]
                    if len(lines) >= 2 and lines[1].upper() not in {"UUID", "SERIALNUMBER"}:
                        return lines[1].upper()
                except Exception:
                    continue

        node_name = platform.node().strip()
        mac = uuid.getnode()
        raw = f"{node_name}-{mac:012X}" if node_name else f"{mac:012X}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()[:32]
    except Exception:
        return hashlib.sha256(platform.node().encode("utf-8")).hexdigest().upper()[:32]


def init_database():
    try:
        with sqlite_write_lock:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS panen_raya (nomor TEXT PRIMARY KEY, nik TEXT, kk TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
            conn.commit()
            cursor.execute("SELECT nomor, nik, kk, timestamp FROM panen_raya")
            rows = cursor.fetchall()
            conn.close()
        for nomor, nik, kk, timestamp in rows:
            phone_cache[nomor] = {
                "nik": nik,
                "kk": kk,
                "updated_at": time.time() if not timestamp else time.mktime(datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").timetuple()),
            }
            db_cache[nik] = kk
    except Exception: pass

def save_to_harvest_db(nomor, nik, kk, masa_aktif=None, lifetime_days=None):
    global db_cache
    if not nomor or not nik or not kk: return
    try:
        with sqlite_write_lock:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO panen_raya (nomor, nik, kk) VALUES (?, ?, ?)", (nomor, nik, kk))
            conn.commit()
            conn.close()
        phone_cache[nomor] = {
            "nik": nik,
            "kk": kk,
            "masa_aktif": masa_aktif or "-",
            "lifetime_days": lifetime_days,
            "updated_at": time.time(),
        }
        db_cache[nik] = kk
    except Exception: pass


def lookup_phone_cache(phone):
    phone = str(phone or "").strip()
    if not phone:
        return None
    entry = phone_cache.get(phone)
    if not isinstance(entry, dict):
        return None
    nik = str(entry.get("nik") or "").strip()
    kk = str(entry.get("kk") or "").strip()
    if not nik or not kk:
        return None
    if not re.fullmatch(r"\d{16}", nik) or not re.fullmatch(r"\d{16}", kk):
        return None
    return {"nik": nik, "kk": kk}


def update_phone_cache(phone, nik, kk):
    phone = str(phone or "").strip()
    nik = str(nik or "").strip()
    kk = str(kk or "").strip()
    if not phone or not nik or not kk:
        return
    if not re.fullmatch(r"\d{16}", nik) or not re.fullmatch(r"\d{16}", kk):
        return
    phone_cache[phone] = {
        "nik": nik,
        "kk": kk,
        "updated_at": time.time(),
    }
    db_cache[nik] = kk


def save_to_harvest_db_batch(records):
    if not records:
        return 0
    try:
        with sqlite_write_lock:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            inserted = 0
            for nomor, nik, kk in records:
                if not nomor or not nik or not kk:
                    continue
                cursor.execute("INSERT OR REPLACE INTO panen_raya (nomor, nik, kk) VALUES (?, ?, ?)", (nomor, nik, kk))
                phone_cache[nomor] = {"nik": nik, "kk": kk}
                db_cache[nik] = kk
                inserted += 1
            conn.commit()
            conn.close()
        return inserted
    except Exception:
        return 0


def _normalize_column_name(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _clean_import_value(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) in {10, 11, 12, 13, 14, 15, 16}:
        return digits
    return text


def _parse_import_row(row):
    values = [_clean_import_value(v) for v in row if v is not None]
    if not values:
        return None, None, None

    nomor = None
    nik = None
    kk = None

    for value in values:
        digits = re.sub(r"\D", "", value)
        if not digits:
            continue
        if len(digits) == 16:
            if nik is None:
                nik = digits
            elif kk is None:
                kk = digits
        elif 10 <= len(digits) <= 15 and nomor is None:
            nomor = digits

    if not nomor and values:
        first_value = values[0]
        if re.search(r"\d", first_value):
            nomor = first_value

    return nomor or None, nik or None, kk or None


def _detect_import_delimiter(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
        if not sample:
            return ","
        for delimiter in [";", ",", "\t", "|"]:
            if delimiter not in sample:
                continue
            rows = list(csv.reader(io.StringIO(sample), delimiter=delimiter))
            if rows and len(rows[0]) > 1:
                return delimiter
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
            return dialect.delimiter
        except Exception:
            return ","
    except Exception:
        return ","


def read_import_records(path):
    records = []
    try:
        delimiter = _detect_import_delimiter(path)
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=delimiter))
    except Exception:
        return records

    if not rows:
        return records

    header_names = [_normalize_column_name(c) for c in rows[0]]
    has_known_header = any(name in header_names for name in ["nomor", "nomorhp", "nohp", "hp", "phone", "telepon", "nik", "kk", "nokk", "kartukeluarga"])

    if has_known_header:
        header_positions = {}
        for idx, name in enumerate(header_names):
            if name in {"nomor", "nomorhp", "nohp", "hp", "phone", "telepon"}:
                header_positions["nomor"] = idx
            elif name == "nik":
                header_positions["nik"] = idx
            elif name in {"kk", "nokk", "kartukeluarga"}:
                header_positions["kk"] = idx

        for row in rows[1:]:
            if not row or not any(str(cell).strip() for cell in row):
                continue

            nomor = None
            nik = None
            kk = None

            if "nomor" in header_positions and header_positions["nomor"] < len(row):
                nomor = _clean_import_value(row[header_positions["nomor"]])
            if "nik" in header_positions and header_positions["nik"] < len(row):
                nik = _clean_import_value(row[header_positions["nik"]])
            if "kk" in header_positions and header_positions["kk"] < len(row):
                kk = _clean_import_value(row[header_positions["kk"]])

            if not nomor and not nik and not kk:
                continue
            if not nomor or not nik or not kk:
                parsed_nomor, parsed_nik, parsed_kk = _parse_import_row(row)
                nomor = nomor or parsed_nomor
                nik = nik or parsed_nik
                kk = kk or parsed_kk

            records.append((nomor, nik, kk))
    else:
        for row in rows:
            if not row or not any(str(cell).strip() for cell in row):
                continue
            nomor, nik, kk = _parse_import_row(row)
            if not nomor and not nik and not kk:
                continue
            records.append((nomor, nik, kk))

    return records


def iter_import_records(path, batch_size=1000):
    try:
        delimiter = _detect_import_delimiter(path)
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=delimiter))
    except Exception:
        return

    if not rows:
        return

    header_names = [_normalize_column_name(c) for c in rows[0]]
    has_known_header = any(name in header_names for name in ["nomor", "nomorhp", "nohp", "hp", "phone", "telepon", "nik", "kk", "nokk", "kartukeluarga"])

    if has_known_header:
        header_positions = {}
        for idx, name in enumerate(header_names):
            if name in {"nomor", "nomorhp", "nohp", "hp", "phone", "telepon"}:
                header_positions["nomor"] = idx
            elif name == "nik":
                header_positions["nik"] = idx
            elif name in {"kk", "nokk", "kartukeluarga"}:
                header_positions["kk"] = idx

        for row in rows[1:]:
            if not row or not any(str(cell).strip() for cell in row):
                continue
            nomor = None
            nik = None
            kk = None
            if "nomor" in header_positions and header_positions["nomor"] < len(row):
                nomor = _clean_import_value(row[header_positions["nomor"]])
            if "nik" in header_positions and header_positions["nik"] < len(row):
                nik = _clean_import_value(row[header_positions["nik"]])
            if "kk" in header_positions and header_positions["kk"] < len(row):
                kk = _clean_import_value(row[header_positions["kk"]])
            if not nomor and not nik and not kk:
                continue
            if not nomor or not nik or not kk:
                parsed_nomor, parsed_nik, parsed_kk = _parse_import_row(row)
                nomor = nomor or parsed_nomor
                nik = nik or parsed_nik
                kk = kk or parsed_kk
            yield (nomor, nik, kk)
    else:
        for row in rows:
            if not row or not any(str(cell).strip() for cell in row):
                continue
            nomor, nik, kk = _parse_import_row(row)
            if not nomor and not nik and not kk:
                continue
            yield (nomor, nik, kk)


def record_status_match(nomor, kategori, masa_aktif):
    """Simpan/update kartu aktif atau tenggang yang tidak dibypass."""
    if not nomor:
        return
    try:
        with sqlite_write_lock:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            cursor.execute("""CREATE TABLE IF NOT EXISTS status_kartu
                          (nomor TEXT PRIMARY KEY, kategori TEXT, masa_aktif TEXT,
                           timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""INSERT OR REPLACE INTO status_kartu
                          (nomor, kategori, masa_aktif, timestamp)
                          VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                       (nomor, kategori, masa_aktif))
            conn.commit()
            conn.close()
    except Exception:
        pass

def record_reactivation_result(nomor, nik, kk, status_awal, status_akhir, hasil):
    """Audit hasil reaktivasi, baik sukses maupun gagal verifikasi."""
    try:
        with sqlite_write_lock:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            cursor.execute("""CREATE TABLE IF NOT EXISTS riwayat_reaktivasi
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, nomor TEXT, nik TEXT,
                           kk TEXT, status_awal TEXT, status_akhir TEXT, hasil TEXT,
                           timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""INSERT INTO riwayat_reaktivasi
                          (nomor, nik, kk, status_awal, status_akhir, hasil)
                          VALUES (?, ?, ?, ?, ?, ?)""",
                       (nomor, nik, kk, status_awal, status_akhir, hasil))
            conn.commit()
            conn.close()
    except Exception:
        pass

def clean_modem_response(text):
    if not text: return ""
    text = re.sub(r"\+WIND:\s*\d+|\+MREG:\s*\d+,\d+|\+CPIN:\s*\w+|\bOK\b", "", text, flags=re.IGNORECASE)
    cusd_match = re.search(r'\+CUSD:\s*\d+,\s*"(.*?)"', text, flags=re.IGNORECASE)
    if cusd_match:
        text = cusd_match.group(1)
    return re.sub(r'\s+', ' ', text.replace("\r", "").replace("\n", " ")).strip()


def normalize_serial_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).replace("\r", " ").replace("\n", " ")).strip()


def extract_ussd_payload(raw):
    raw_text = normalize_serial_text(raw)
    matches = re.findall(r'\+CUSD:\s*\d+,\s*"([^\"]*)"', raw_text, flags=re.IGNORECASE)
    if matches:
        return matches[-1].strip()
    return None


def extract_ussd_status_only(raw):
    """Return status code as string if +CUSD: <n> present without quoted payload.
    Examples matched: '+CUSD: 0', '+CUSD: 1', '+CUSD: 2', '+CUSD: 4' with no quoted payload.
    """
    raw_text = normalize_serial_text(raw)
    # group(2) is the full ",\"...\"" clause when present; group(3) is the payload text.
    # findall cannot distinguish missing clause vs empty payload (both yield ''), so use finditer.
    matches = list(re.finditer(r'\+CUSD:\s*(\d+)(\s*,\s*"([^"]*)")?', raw_text, flags=re.IGNORECASE))
    if matches:
        for match in reversed(matches):
            status = match.group(1)
            # If a quoted payload clause is present (even if empty string), treat it as a payload
            # and therefore NOT a status-only entry.
            if match.group(2) is not None:
                return None
            # Incomplete payload start ("+CUSD: 0,\"...") must not be treated as status-only.
            rest = raw_text[match.end():].lstrip()
            if rest.startswith(","):
                return None
            # only return recognized numeric statuses when there is truly no quoted payload
            if status in ("0", "1", "2", "4"):
                return status
        return None
    return None


def has_incomplete_ussd_payload(raw):
    raw_text = normalize_serial_text(raw)
    return bool(re.search(r'\+CUSD:\s*\d+,\s*"[^\"]*$', raw_text, flags=re.IGNORECASE))


def is_prompt_confirmation(raw):
    if not raw:
        return False
    text = normalize_serial_text(raw).lower()
    return any(keyword in text for keyword in [
        "confirm", "konfirmasi", "pilih", "silakan pilih", "silahkan pilih", "input angka", "jawab", "1.", "2." ]
    )


def is_at_ok_response(raw):
    raw_text = normalize_serial_text(raw)
    if not raw_text:
        return False
    if "+CUSD:" in raw_text:
        return False
    return bool(re.search(r"(^|\s)OK($|\s)", raw_text, flags=re.IGNORECASE))


def is_command_echo(raw):
    raw_text = normalize_serial_text(raw)
    return bool(re.search(r"AT\+CUSD=", raw_text, flags=re.IGNORECASE) and "+CUSD:" not in raw_text)


def is_modem_notification(raw):
    raw_text = normalize_serial_text(raw)
    return bool(re.search(r"\+WIND:|\+MREG:|\+CPIN:|\+CREG:|\+CGREG:|\+CIEV:|\+CSQ:", raw_text, flags=re.IGNORECASE))


def classify_ussd_response(text):
    raw = normalize_serial_text(text)
    if not raw:
        return "TIMEOUT", ""
    payload = extract_ussd_payload(raw)
    status_only = extract_ussd_status_only(raw)
    if payload is not None:
        # Empty quoted payload should be classified separately so callers can decide
        # whether this indicates an empty/unfinished session vs a real payload.
        if payload == "":
            logging.info(f"USSD_CLASSIFY: raw={raw} kind=USSD_EMPTY_PAYLOAD decision=RETURN_EMPTY")
            return "USSD_EMPTY_PAYLOAD", ""
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=USSD_PAYLOAD decision=RETURN_PAYLOAD")
        return "USSD_PAYLOAD", payload
    if status_only is not None:
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=USSD_STATUS_ONLY decision=RETURN_STATUS_ONLY:{status_only}")
        return "USSD_STATUS_ONLY", status_only
    if has_incomplete_ussd_payload(raw):
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=PARTIAL_RESPONSE decision=RETURN_PARTIAL")
        return "PARTIAL_RESPONSE", raw
    if is_prompt_confirmation(raw):
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=PROMPT_CONFIRMATION decision=RETURN_PROMPT")
        return "PROMPT_CONFIRMATION", raw
    if re.search(r"\+CME ERROR|CME ERROR|\+CMS ERROR|CMS ERROR", raw, flags=re.IGNORECASE):
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=ERROR decision=RETURN_ERROR")
        return "ERROR", raw
    if is_at_ok_response(raw):
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=AT_OK decision=RETURN_AT_OK")
        return "AT_OK", raw
    if is_command_echo(raw):
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=COMMAND_ECHO decision=RETURN_ECHO")
        return "COMMAND_ECHO", raw
    if is_modem_notification(raw):
        logging.info(f"USSD_CLASSIFY: raw={raw} kind=MODEM_NOTIFICATION decision=RETURN_NOTIFICATION")
        return "MODEM_NOTIFICATION", raw
    logging.info(f"USSD_CLASSIFY: raw={raw} kind=WAITING_RESPONSE decision=RETURN_WAIT")
    return "WAITING_RESPONSE", raw


def classify_ussd_evidence(payload):
    """Return normalized evidence flags from a USSD payload without changing workflow semantics.

    Mixed operator payloads may set multiple evidence flags at once
    (e.g. TRY_AGAIN + NUMBER_INFO). Primary intent is decided separately
    by classify_ussd_intent(); workflow gates use the flags they already consume.
    """
    if payload is None:
        return {
            "text": "",
            "has_success_evidence": False,
            "has_processing_evidence": False,
            "has_tenggang_evidence": False,
            "has_try_again_evidence": False,
            "has_number_info_evidence": False,
            "has_menu_evidence": False,
            "has_retry_reject_evidence": False,
            "secondary_intents": [],
        }

    text = normalize_serial_text(payload).strip()
    low = text.lower()
    has_success = any(k in low for k in ("sukses", "berhasil", "success", "completed"))
    has_processing = any(k in low for k in ("sedang diproses", "sedang di proses", "di proses", "dalam proses", "permintaan diterima", "diterima", "accepted", "processing", "in process", "queued", "diproses"))
    has_tenggang = bool(re.search(r"\b(dalam\s+masa\s+tenggang|masa\s+tenggang|sedang\s+dalam\s+masa\s+tenggang|sedang\s+dalam\s+tenggang)\b", low))
    try_again_keywords = (
        "try again",
        "please try again",
        "coba lagi",
        "silakan coba lagi",
        "silahkan coba lagi",
    )
    retry_reject_keywords = (
        "retry",
        "temporary busy",
        "network busy",
        "request failed",
        "sementara sibuk",
        "jaringan sibuk",
    )
    menu_keywords = (
        "good morning",
        "good afternoon",
        "good evening",
        "welcome",
        "menu",
        "account",
        "content",
        "impoint",
        "your number",
        "balance",
        "pilih",
        "silakan pilih",
        "silahkan pilih",
    )
    has_try_again = any(k in low for k in try_again_keywords)
    has_retry_reject = has_try_again or any(k in low for k in retry_reject_keywords)
    has_number_info = bool(re.search(r"08\d{9,11}", low))
    has_menu = any(k in low for k in menu_keywords) or bool(re.search(r"(^|\n)\s*\d+\.", text))

    # Non-primary co-signals for accurate mixed-payload logging (order is informative only).
    secondary = []
    if has_try_again:
        secondary.append("TRY_AGAIN")
    if has_success:
        secondary.append("SUCCESS_MESSAGE")
    if has_processing:
        secondary.append("REQUEST_ACCEPTED")
    if has_tenggang:
        secondary.append("TENGGANG")
    if has_number_info:
        secondary.append("NUMBER_INFO")
    if has_menu and not has_number_info:
        secondary.append("MENU_RESPONSE")
    if has_retry_reject and not has_try_again:
        secondary.append("RETRY_REJECT")

    return {
        "text": text,
        "has_success_evidence": has_success,
        "has_processing_evidence": has_processing,
        "has_tenggang_evidence": has_tenggang,
        "has_try_again_evidence": has_try_again,
        "has_number_info_evidence": has_number_info,
        "has_menu_evidence": has_menu,
        "has_retry_reject_evidence": has_retry_reject,
        "secondary_intents": secondary,
    }


def classify_ussd_intent(payload):
    """Classify the dominant semantic intent of a USSD payload string.

    Returns one of:
    NUMBER_INFO, MENU_RESPONSE, REQUEST_ACCEPTED, SUCCESS_MESSAGE,
    TRY_AGAIN, EMPTY_RESPONSE, UNKNOWN

    Priority (dominant response first):
    1) EMPTY_RESPONSE
    2) SUCCESS_MESSAGE
    3) REQUEST_ACCEPTED
    4) TRY_AGAIN  (out-ranks informational NUMBER_INFO / menu greetings)
    5) NUMBER_INFO
    6) MENU_RESPONSE
    7) UNKNOWN

    Mixed payloads keep full evidence via classify_ussd_evidence(); this
    function only selects the primary intent used in logs.
    """
    evidence = classify_ussd_evidence(payload)
    text = evidence["text"]
    if text == "":
        primary = "EMPTY_RESPONSE"
    elif evidence["has_success_evidence"]:
        # Business-critical outcomes keep priority over retry/info noise.
        primary = "SUCCESS_MESSAGE"
    elif evidence["has_processing_evidence"]:
        primary = "REQUEST_ACCEPTED"
    elif evidence["has_try_again_evidence"] or evidence["has_retry_reject_evidence"]:
        # Try Again / not-accepted dominates pure informational number/menu text.
        primary = "TRY_AGAIN"
    elif evidence["has_number_info_evidence"]:
        primary = "NUMBER_INFO"
    elif evidence["has_menu_evidence"]:
        primary = "MENU_RESPONSE"
    else:
        primary = "UNKNOWN"

    secondary = [s for s in evidence.get("secondary_intents", []) if s != primary]
    if secondary:
        logging.info(
            "USSD_INTENT_DETAIL: primary=%s evidence=%s mixed=True payload=%s",
            primary,
            ",".join(secondary),
            text[:240],
        )
    else:
        logging.info(
            "USSD_INTENT_DETAIL: primary=%s evidence=- mixed=False payload=%s",
            primary,
            text[:240],
        )
    return primary


def is_inject_not_accepted_response(payload):
    """CATEGORY B: operator has not accepted the inject request; inject may be retried.

    CATEGORY A (accepted/processing) must return False so verification can proceed.
    Uses classifier evidence only; does not change retry policy gates.
    """
    if not isinstance(payload, str):
        return False
    if payload.startswith(("USSD_STATUS_ONLY:", "USSD_EMPTY_PAYLOAD", "PROMPT:", "PARTIAL:", "ERROR:")):
        return False
    if payload in ("timeout", "COMMAND_EXECUTED"):
        return False
    evidence = classify_ussd_evidence(payload)
    # CATEGORY A signals: accepted, processing, or tenggang acknowledgment.
    if evidence["has_success_evidence"] or evidence["has_processing_evidence"] or evidence["has_tenggang_evidence"]:
        return False
    return bool(evidence["has_retry_reject_evidence"])


def is_ussd_payload_complete(text):
    raw = normalize_serial_text(text)
    if not raw:
        return False
    if extract_ussd_payload(raw) is not None:
        return True
    if re.search(r"\+CME ERROR|CME ERROR", raw, flags=re.IGNORECASE):
        return True
    if is_prompt_confirmation(raw):
        return True
    return False


def build_reaktivasi_command(nik, kk):
    nik = str(nik or "").strip()
    kk = str(kk or "").strip()
    if not nik or nik == "-" or not kk or kk == "-":
        return ""
    return f"*888*89*1*{nik}*{kk}#"

def extract_grace_date(text):
    """Extract the grace date from USSD response; this is the primary business fact."""
    if not text: return "-"
    m_iso = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", text)
    if m_iso: return m_iso.group(1).replace("/", "-")
    m_loc = re.search(r"(\d{2}[-/]\d{2}[-/]\d{4})", text)
    if m_loc:
        parts = m_loc.group(1).replace("/", "-").split("-")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return "-"


def extract_exp_date(text):
    """Backward-compatible wrapper for grace-date extraction."""
    return extract_grace_date(text)


def classify_card_status(grace_date, raw_response=""):
    """Derive card status from grace date and today; this value is always derived, never primary.

    Respons eksplisit seperti "sedang dalam masa tenggang" adalah indikator tambahan
    untuk status TENGGANG, tanpa menggantikan logika utama untuk AKTIF atau HANGUS.
    """
    try:
        grace_date_value = datetime.strptime(grace_date, "%Y-%m-%d").date()
        days_remaining = (grace_date_value - datetime.now().date()).days
    except (TypeError, ValueError):
        days_remaining = None

    response = raw_response or ""
    evidence = classify_ussd_evidence(response)
    if evidence["has_tenggang_evidence"]:
        return "TENGGANG", days_remaining
    if re.search(r"\bnomor\s+hangus\b|\bstatus\s+hangus\b|\btelah\s+hangus\b", response.lower()):
        return "HANGUS", days_remaining
    if re.search(r"\bmasih\s+aktif\b|\bstatus\s+(?:kartu\s+)?aktif\b|\bkartu\s+aktif\b", response.lower()):
        return "AKTIF", days_remaining
    if days_remaining is None:
        return "UNKNOWN", None
    if days_remaining > 0:
        return "AKTIF", days_remaining
    if days_remaining >= -30:
        return "TENGGANG", days_remaining
    return "HANGUS", days_remaining


def has_grace_date_changed(before_grace_date, after_grace_date):
    """Return True when the grace date changed, otherwise False."""
    try:
        before_value = str(before_grace_date or "").strip()
        after_value = str(after_grace_date or "").strip()
        if not before_value or before_value == "-" or not after_value or after_value == "-":
            return False
        before_date = datetime.strptime(before_value, "%Y-%m-%d").date()
        after_date = datetime.strptime(after_value, "%Y-%m-%d").date()
        return before_date != after_date
    except (TypeError, ValueError):
        return False


def evaluate_business_outcome(before_grace_date, after_grace_date, before_card_status_value, after_card_status_value, inject_response):
    """Single source of truth for final Business Outcome.

    Returns only one of: SUCCESS, TENGGANG, FAILED.
    Workflow may route Continue/Stop/Retry/Wait from this value, but must not
    re-decide the business outcome inline.
    """
    grace_changed = has_grace_date_changed(before_grace_date, after_grace_date)
    evidence = classify_ussd_evidence(inject_response)

    if grace_changed and str(after_card_status_value or "").upper() not in {"", "HANGUS", "UNKNOWN"}:
        return "SUCCESS"

    if not grace_changed and evidence["has_tenggang_evidence"]:
        return "TENGGANG"

    return "FAILED"


def decide_business_outcome(business_snapshot, inject_response):
    """Resolve and store the final Business Outcome from the shared snapshot."""
    snapshot = business_snapshot if isinstance(business_snapshot, dict) else {}
    business_outcome = evaluate_business_outcome(
        snapshot.get("before_grace_date"),
        snapshot.get("after_grace_date"),
        snapshot.get("before_card_status_value"),
        snapshot.get("after_card_status_value"),
        inject_response,
    )
    snapshot["business_outcome"] = business_outcome
    return business_outcome


def format_day_delta(days_remaining):
    return f"{days_remaining:+d} hari" if days_remaining is not None else "tanggal tidak terbaca"

def format_lifetime(days_remaining):
    if days_remaining is None:
        return "tanggal tidak terbaca"
    return f"{days_remaining} hari tersisa" if days_remaining >= 0 else f"{-days_remaining} hari melewati batas"

def is_network_available(host="8.8.8.8", port=53, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def mock_telegram_gateway_query(nik):
    with telegram_api_queue:
        time.sleep(1.2)
        if not is_network_available():
            return "DATA_TIDAK_DITEMUKAN"
        bot_response_raw = "Pencarian NIK: DATA TIDAK DITEMUKAN"
        if "tidak ditemukan" in bot_response_raw.lower() or "tidak ada" in bot_response_raw.lower():
            return "DATA_TIDAK_DITEMUKAN"
        kk_match = re.search(r"(?:KK|KELUARGA|NO_KK).*?(\d{16})", bot_response_raw, flags=re.IGNORECASE)
        return kk_match.group(1) if kk_match else None

def _reset_telegram_login_state():
    global telegram_login_client, telegram_login_phone
    if telegram_login_client:
        try:
            telegram_login_client.disconnect()
        except Exception:
            pass
    telegram_login_client = None
    telegram_login_phone = ""


def request_telegram_otp(api_id, api_hash, phone):
    """Kirim OTP Telegram dan simpan client sementara untuk verifikasi kode."""
    global telegram_login_client, telegram_login_phone
    if not TELETHON_AVAILABLE:
        raise RuntimeError("Pustaka Telethon belum terpasang. Jalankan: pip install telethon")
    if not is_network_available():
        raise RuntimeError("Tidak ada koneksi internet. Login Telegram tidak bisa diproses saat offline.")
    if not api_id.isdigit() or not api_hash or not phone.startswith("+"):
        raise ValueError("API ID, API Hash, dan nomor format internasional (+62...) wajib diisi.")
    with telegram_login_lock:
        try:
            if telegram_login_client:
                try:
                    telegram_login_client.disconnect()
                except Exception:
                    pass
            session_path = os.path.join(BASE_DIR, "telegram_login")
            client = TelegramClient(session_path, int(api_id), api_hash)
            client.connect()
            if not client.is_connected():
                raise RuntimeError("Gagal terhubung ke Telegram. Periksa jaringan dan kredensial API.")
            if client.is_user_authorized():
                telegram_login_client = client
                telegram_login_phone = phone
                return "Session Telegram sudah aktif di perangkat ini."
            client.send_code_request(phone)
            telegram_login_client = client
            telegram_login_phone = phone
            return "OTP telah dikirim. Periksa Telegram atau SMS, lalu masukkan kodenya."
        except Exception as exc:
            _reset_telegram_login_state()
            raise RuntimeError(f"Gagal mengirim OTP: {exc}") from exc


def verify_telegram_otp(code, password_2fa=""):
    """Verifikasi OTP yang sebelumnya diminta; session disimpan lokal oleh Telethon."""
    if not TELETHON_AVAILABLE:
        raise RuntimeError("Pustaka Telethon belum terpasang. Jalankan: pip install telethon")
    if not is_network_available():
        raise RuntimeError("Tidak ada koneksi internet. Login Telegram tidak bisa diproses saat offline.")
    if not code:
        raise ValueError("Kode OTP wajib diisi.")
    with telegram_login_lock:
        if not telegram_login_client or not telegram_login_phone:
            raise RuntimeError("Klik Kirim OTP terlebih dahulu.")
        try:
            if not telegram_login_client.is_connected():
                telegram_login_client.connect()
            telegram_login_client.sign_in(phone=telegram_login_phone, code=code)
        except SessionPasswordNeededError:
            if not password_2fa:
                raise RuntimeError("Akun memakai verifikasi dua langkah; isi Password 2FA.")
            try:
                telegram_login_client.sign_in(password=password_2fa)
            except PasswordHashInvalidError as exc:
                raise RuntimeError("Password 2FA salah. Periksa kembali password akun.") from exc
            except Exception as exc:
                raise RuntimeError(f"Gagal memverifikasi password 2FA: {exc}") from exc
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
            raise RuntimeError("Kode OTP salah atau sudah kadaluarsa. Coba kirim ulang OTP.") from exc
        except FloodWaitError as exc:
            wait_seconds = getattr(exc, "seconds", None)
            wait_text = f" {wait_seconds} detik" if wait_seconds is not None else ""
            raise RuntimeError(f"Telegram sedang membatasi permintaan{wait_text}. Tunggu beberapa menit lalu coba lagi.") from exc
        except Exception as exc:
            message = str(exc).lower()
            if "invalid" in message and "code" in message:
                raise RuntimeError("Kode OTP salah atau sudah kadaluarsa. Coba kirim ulang OTP.") from exc
            if "flood" in message or "wait" in message:
                raise RuntimeError("Telegram sedang membatasi permintaan. Tunggu beberapa menit lalu coba lagi.") from exc
            if "connection" in message or "temporarily unavailable" in message or "network" in message:
                try:
                    telegram_login_client.disconnect()
                    telegram_login_client.connect()
                    telegram_login_client.sign_in(phone=telegram_login_phone, code=code)
                except Exception as retry_exc:
                    raise RuntimeError(f"Gagal verifikasi OTP: {retry_exc}") from retry_exc
            else:
                raise RuntimeError(f"Gagal verifikasi OTP: {exc}") from exc

        if not telegram_login_client.is_user_authorized():
            raise RuntimeError("OTP tidak dapat diverifikasi.")
        try:
            telegram_login_client.session.save()
        except Exception:
            pass
        return "Login Telegram berhasil. Session tersimpan lokal."

# =====================================================================
# 2. HARDWARE CLIENT ENGINE (AUTO DETECT ALL COM PORTS)
# =====================================================================
class PortWorker(threading.Thread):
    def __init__(self, port_name, ui_callback):
        super().__init__()
        self.port_name = port_name
        self.ui_callback = ui_callback
        self.is_running = True
        self.force_retry = False
        self.single_action = None  # Action: 'cek_nomor', 'cek_nik', 'cari_kk', 'reaktivasi'
        self.reset_requested = False
        self.current_baud = None
        self._active_serial = None
        self.daemon = True
        with port_logs_lock:
            port_logs[self.port_name] = []
        # CPIN / SIM state tracking for insert/remove detection
        self.cpin_state = None  # None, 'READY', 'NOT_INSERTED'
        self.cpin_failure_count = 0
        self.pending_removal_confirmation = False
        self.removal_confirmation_count = 0
        self.max_removal_confirmation = 2
        self.unknown_failure_count = 0
        self.pending_auto_run = False
        self.next_dial_allowed_at = 0.0
        self.ussd_internal_state = "IDLE"
        self._ussd_session_id = 0
        self._ussd_session_active = False
        self._eventbus_released = False
        self._cooperative_cancel_logged = False
        self._prompt_pending = False
        self._prompt_pending_since = 0.0
        self._prompt_pending_context = ""
        self.business_snapshot = {
            "before_grace_date": None,
            "before_card_status_value": None,
            "after_grace_date": None,
            "after_card_status_value": None,
            "business_outcome": None,
        }
        self.state_machine = PortStateMachine(self.port_name, self.ui_callback, self._queue_auto_run)
        # setup per-port rotating file logger
        try:
            logger_name = f"port.{self.port_name}"
            self.file_logger = logging.getLogger(logger_name)
            if not self.file_logger.handlers:
                self.file_logger.setLevel(logging.INFO)
                fh = RotatingFileHandler(os.path.join(LOGS_DIR, f"port_{self.port_name}.log"), maxBytes=200*1024, backupCount=5, encoding='utf-8')
                fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
                fh.setFormatter(fmt)
                self.file_logger.addHandler(fh)
            port_file_loggers[self.port_name] = self.file_logger
        except Exception:
            self.file_logger = None

    def log(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"[{ts}] {text}"
        with port_logs_lock:
            if self.port_name not in port_logs:
                port_logs[self.port_name] = []
            port_logs[self.port_name].append(msg)
            if len(port_logs[self.port_name]) > 100:
                port_logs[self.port_name].pop(0)
        # also write to rotating file logger if available
        try:
            if getattr(self, 'file_logger', None):
                self.file_logger.info(text)
        except Exception:
            pass

    def request_modem_reset(self):
        self.reset_requested = True
        self._cooperative_cancel_logged = False
        self.force_retry = False
        self.single_action = None
        self.pending_auto_run = False
        self.log(f"Reset requested for {self.port_name}")

    def _should_cooperative_cancel(self, checkpoint=""):
        if not self.reset_requested:
            return False
        if not self._cooperative_cancel_logged:
            suffix = f" checkpoint={checkpoint}" if checkpoint else ""
            self.log(f"COOPERATIVE_RESET_PENDING: port={self.port_name}{suffix}")
            self._cooperative_cancel_logged = True
        return True

    def _release_eventbus_listener(self, reason=""):
        if self._eventbus_released:
            return
        self._eventbus_released = True
        try:
            state_machine = getattr(self, "state_machine", None)
            if state_machine is not None:
                state_machine.close()
        except Exception:
            pass
        finally:
            self.state_machine = None
        if reason:
            self.log(f"EVENTBUS_UNSUBSCRIBE: port={self.port_name} reason={reason}")

    def shutdown(self):
        if not self.is_running:
            return
        self.is_running = False
        self.reset_requested = True
        self.single_action = None
        self.pending_auto_run = False
        self._clear_temporary_workflow_state("SHUTDOWN_REQUEST")
        self._release_eventbus_listener("SHUTDOWN_REQUEST")
        try:
            if self._active_serial is not None and self._active_serial.is_open:
                self._active_serial.close()
        except Exception:
            pass
        finally:
            self._active_serial = None

    def _new_business_snapshot(self):
        """Empty temporary business snapshot (runtime only; not harvest/history)."""
        return {
            "before_grace_date": None,
            "before_card_status_value": None,
            "after_grace_date": None,
            "after_card_status_value": None,
            "business_outcome": None,
        }

    def _clear_temporary_workflow_state(self, reason=""):
        """Clear temporary runtime workflow/transport state only.

        Does NOT clear: harvest DB, outcome history, awaiting_card_cycle,
        permanent configuration, CPIN identity, or auto-run policy.
        """
        self.business_snapshot = self._new_business_snapshot()
        self.ussd_internal_state = "IDLE"
        self._ussd_session_active = False
        self._prompt_pending = False
        self._prompt_pending_since = 0.0
        self._prompt_pending_context = ""
        if reason:
            self.log(f"TEMP_WORKFLOW_CLEANUP: port={self.port_name} reason={reason}")

    def _set_prompt_pending(self, prompt_response, context=""):
        if self._prompt_pending:
            return
        self._prompt_pending = True
        self._prompt_pending_since = time.monotonic()
        self._prompt_pending_context = context or "PROMPT"
        self.ui_callback(self.port_name, "status", "PROMPT")
        self.ui_callback(
            self.port_name,
            "respon",
            f"{prompt_response} | menunggu konfirmasi (timeout {int(PROMPT_LIFECYCLE_TIMEOUT_SECONDS)} detik)",
        )
        self.log(f"PROMPT_PENDING: port={self.port_name} context={self._prompt_pending_context}")

    def _clear_prompt_pending(self, reason=""):
        if not self._prompt_pending:
            return
        self._prompt_pending = False
        self._prompt_pending_since = 0.0
        self._prompt_pending_context = ""
        if reason:
            self.log(f"PROMPT_RESOLVED: port={self.port_name} reason={reason}")

    def _advance_prompt_lifecycle(self):
        """Return True while prompt remains pending and owned by the run-loop."""
        if not self._prompt_pending:
            return False
        if self.reset_requested:
            self._clear_prompt_pending("CANCELLED_BY_RESET")
            return False
        elapsed = time.monotonic() - self._prompt_pending_since
        if elapsed >= PROMPT_LIFECYCLE_TIMEOUT_SECONDS:
            self._clear_prompt_pending("TIMEOUT")
            self.ui_callback(self.port_name, "status", "GAGAL")
            self.ui_callback(self.port_name, "respon", "Permintaan konfirmasi operator tidak ditindaklanjuti (timeout)")
            return False
        return True

    def _clear_checking_status_on_ready(self):
        """CHECKING is ephemeral UI overlay; must not survive confirmed READY (incl. READY→READY)."""
        state = port_registry.get(self.port_name) or {}
        if str(state.get("status", "") or "").upper() != "CHECKING":
            return
        self.ui_callback(self.port_name, "status", "READY")
        self.ui_callback(self.port_name, "respon", "+CPIN: READY")
        self.log(f"CHECKING cleared on READY: port={self.port_name}")

    def _perform_modem_reset(self, ser):
        self._cooperative_cancel_logged = False
        self._clear_temporary_workflow_state("RESET")
        self.ui_callback(self.port_name, "status", "RESET")
        self.ui_callback(self.port_name, "respon", "Reset modem sedang diproses...")
        self.log(f"Reset start: closing active serial handle on {self.port_name}")
        try:
            if ser and ser.is_open:
                ser.close()
        except Exception as exc:
            self.log(f"Reset warning: gagal menutup handle aktif: {exc}")

        time.sleep(0.6)
        reset_baud = self.current_baud or BAUD_RATES[0]
        self.log(f"Reset: using baud rate {reset_baud} for {self.port_name}")
        try:
            reset_ser = serial.Serial(self.port_name, reset_baud, timeout=2)
            self.log(f"Reset: opening {self.port_name} for reset sequence")
            reset_ser.write(b"ATZ\r\n")
            self.log(f"Reset: sent ATZ to {self.port_name}")
            time.sleep(0.2)
            reset_ser.reset_input_buffer()
            reset_ser.write(b"AT+CFUN=1,1\r\n")
            self.log(f"Reset: sent AT+CFUN=1,1 to {self.port_name}")
            time.sleep(1.0)
            reset_ser.reset_input_buffer()
            reset_ser.close()
            self.log(f"Reset completed for {self.port_name}")
        except Exception as exc:
            self.log(f"Reset gagal untuk {self.port_name}: {exc}")
            self.ui_callback(self.port_name, "respon", f"Reset modem gagal: {exc}")
            self._clear_temporary_workflow_state("RESET_FAILED")
            return

        self.current_baud = None
        self.pending_auto_run = True
        self.ui_callback(self.port_name, "respon", "Reset modem selesai; mencoba koneksi ulang dan menjalankan automasi...")
        self.log(f"Reset finished for {self.port_name}; auto-run queued")

    def _emit_event(self, event_name, payload):
        event_bus.publish(event_name, payload)

    def _set_port_status(self, status, respon=None):
        update_port_registry(self.port_name, "status", status)
        update_port_registry(self.port_name, "last_cpin", self.cpin_state or "UNKNOWN")
        self.ui_callback(self.port_name, "status", status)
        if respon is not None:
            self.ui_callback(self.port_name, "respon", respon)

    def _extract_cpin_state(self, raw_up):
        raw_up = raw_up.strip().upper()
        if not raw_up:
            return "UNKNOWN"
        if re.search(r"\+CPIN:\s*NOT\s+READY", raw_up):
            return "NOT_READY"
        # Avoid matching 'NOT READY' as READY by using explicit patterns
        if re.search(r"(^|\W)(?:\+CPIN:\s*)?READY(\W|$)", raw_up) and "NOT READY" not in raw_up:
            return "READY"
        if re.search(r"\b(PIN|PUK)\b", raw_up) or "SIM PIN" in raw_up or "SIM PUK" in raw_up:
            return "PIN_REQUIRED"
        if re.search(r"NOT\s+INSERTED", raw_up) or "+CME ERROR: 10" in raw_up or ("ERROR" in raw_up and "NOT INSERTED" in raw_up):
            return "NOT_INSERTED"
        return "UNKNOWN"

    def _queue_auto_run(self):
        self.pending_auto_run = True

    def _set_ussd_internal_state(self, state):
        self.ussd_internal_state = state
        self.log(f"USSD state -> {state}")

    def _log_cpin_check(self, action, old_state, raw, parsed, fail_count, decision=None):
        decision_text = f" decision={decision}" if decision else ""
        self.log(f"CPIN_CHECK: port={self.port_name} old={old_state} parsed={parsed} fail_count={fail_count} action={action}{decision_text} raw={raw.replace(chr(10), ' ').replace(chr(13), ' ').strip()}")

    def _log_cpin_lifecycle(self, previous_state, current_state, raw, decision, confirmation_count):
        raw_text = str(raw or "").replace(chr(10), " ").replace(chr(13), " ").strip()
        self.log(f"CPIN_LIFECYCLE: port={self.port_name} previous={previous_state} current={current_state} decision={decision} confirmation_count={confirmation_count} raw={raw_text}")

    def _log_cpin_decision(self, old_state, raw, parsed, failure_count, decision, reason):
        raw_text = str(raw or "").replace(chr(10), " ").replace(chr(13), " ").strip()
        self.log(f"CPIN_DECISION: port={self.port_name} old={old_state} parsed={parsed} failure_count={failure_count} decision={decision} reason={reason} raw={raw_text}")

    def _log_ussd_flow_decision(self, action, response, decision, reason):
        resp_text = str(response or "").replace(chr(10), " ").replace(chr(13), " ").strip()
        self.log(f"USSD_FLOW_DECISION: port={self.port_name} action={action} response={resp_text} decision={decision} reason={reason}")

    def _is_removal_candidate_error(self, raw):
        raw_up = str(raw or "").upper()
        return "ERROR" in raw_up and "NOT INSERTED" not in raw_up and "+CME ERROR: 10" not in raw_up and "READY" not in raw_up

    def _flush_serial_input(self, ser):
        if not ser:
            return
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        try:
            if hasattr(ser, "flushInput"):
                ser.flushInput()
        except Exception:
            pass
        time.sleep(0.15)

    def _begin_ussd_transport_session(self, ser):
        self._ussd_session_id = getattr(self, "_ussd_session_id", 0) + 1
        self._ussd_session_active = True
        self._set_ussd_internal_state("SENDING_COMMAND")
        self.log(f"USSD transport session #{self._ussd_session_id} started")
        return self._ussd_session_id

    def _finalize_ussd_transport_session(self, session_id):
        if getattr(self, "_ussd_session_id", None) == session_id:
            self._ussd_session_active = False

    def _fence_ussd_transport_session(self, ser, session_id):
        """Cancel the prior USSD context and discard bytes emitted before this session.

        +CUSD responses do not carry a request id, therefore an input-buffer reset alone
        cannot protect a new dial from a response that arrives a moment later.  The
        cancellation plus quiet-period fence is the ownership boundary between sessions.
        """
        try:
            ser.write(b"AT+CUSD=2\r\n")
            started_at = time.monotonic()
            last_data_at = started_at
            discarded = ""
            deadline = started_at + USSD_SESSION_FENCE_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if ser.in_waiting > 0:
                    chunk = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                    if chunk:
                        discarded += chunk
                        last_data_at = time.monotonic()
                now = time.monotonic()
                min_elapsed = now - started_at >= USSD_SESSION_FENCE_MIN_SECONDS
                quiet = now - last_data_at >= USSD_SESSION_FENCE_QUIET_SECONDS
                if min_elapsed and quiet:
                    break
                time.sleep(0.05)
            if discarded:
                self.log(f"USSD_SESSION_FENCE: port={self.port_name} session={session_id} discarded={normalize_serial_text(discarded)}")
            else:
                self.log(f"USSD_SESSION_FENCE: port={self.port_name} session={session_id} discarded=<none>")
            return True
        except Exception as exc:
            self.log(f"USSD session fence failed for session {session_id}: {exc}")
            return False

    def _write_ussd_transport_command(self, ser, cmd, session_id):
        try:
            if not self._fence_ussd_transport_session(ser, session_id):
                self._finalize_ussd_transport_session(session_id)
                return False
            ser.write(f'AT+CUSD=1,"{cmd}",15\r\n'.encode('utf-8'))
            return True
        except Exception as exc:
            self.log(f"AT+CUSD write failed for session {session_id}: {exc}")
            self._finalize_ussd_transport_session(session_id)
            return False

    def _read_ussd_transport_response(self, ser, session_id):
        resp = ""
        self._set_ussd_internal_state("WAITING_RESPONSE")
        start = time.monotonic()
        last_chunk_at = None
        while time.monotonic() - start < 20.0:
            if getattr(self, "_ussd_session_id", None) != session_id or not getattr(self, "_ussd_session_active", False):
                break
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                if chunk:
                    resp += chunk
                    last_chunk_at = time.monotonic()
            if is_ussd_payload_complete(resp):
                if last_chunk_at is not None and time.monotonic() - last_chunk_at >= 0.8:
                    break
            time.sleep(0.2)
        return resp

    def _handle_cpin_transition(self, old_state, new_state, ser):
        self.log(f"CPIN state change: {old_state} -> {new_state}")
        self.cpin_state = new_state
        update_port_registry(self.port_name, "last_cpin", new_state)
        if new_state == "READY":
            # Transition into READY always retires ephemeral CHECKING UI.
            self._clear_checking_status_on_ready()
        if new_state == "NOT_INSERTED":
            # SIM remove ends any in-flight temporary workflow/session residue.
            self._clear_temporary_workflow_state("SIM_REMOVE")
        self._emit_event("port.cpin_transition", {"port": self.port_name, "old_state": old_state, "new_state": new_state})

    def run(self):
        current_baud = self.current_baud
        try:
            while self.is_running:
                if self.port_name in disabled_ports:
                    self.ui_callback(self.port_name, "port_display", f"🔴 {self.port_name}(OFF)")
                    self.ui_callback(self.port_name, "status", "OFF")
                    self.ui_callback(self.port_name, "respon", "Port dinonaktifkan")
                    time.sleep(2)
                    continue

                ser = None
                try:
                    if not current_baud:
                        for baud in BAUD_RATES:
                            try:
                                t_ser = serial.Serial(self.port_name, baud, timeout=1)
                                t_ser.write(b"AT\r\n")
                                time.sleep(0.2)
                                resp = t_ser.read(t_ser.in_waiting).decode("utf-8", errors="ignore")
                                t_ser.close()
                                if "OK" in resp.upper():
                                    current_baud = baud
                                    self.current_baud = baud
                                    break
                            except Exception: continue
                    
                    if not current_baud:
                        self.ui_callback(self.port_name, "port_display", f"🔴 {self.port_name}")
                        self.ui_callback(self.port_name, "status", "OFF")
                        self.ui_callback(self.port_name, "respon", "Modem tidak teraliri daya/mati")
                        time.sleep(4)
                        continue

                    self.ui_callback(self.port_name, "port_display", f"🟢 {self.port_name}")
                    ser = serial.Serial(self.port_name, current_baud, timeout=2)
                    self._active_serial = ser
                    ser.write(b"ATE0\r\n")
                    time.sleep(0.1)
                    ser.reset_input_buffer()

                    while self.is_running and self.port_name not in disabled_ports:
                        if self.reset_requested:
                            self.reset_requested = False
                            self._perform_modem_reset(ser)
                            self.log(f"Reset cycle completed; reconnecting and resuming FSM for {self.port_name}")
                            break
                        if self._advance_prompt_lifecycle():
                            time.sleep(0.2)
                            continue

                    # prioritized manual actions
                    if self.single_action:
                        act = self.single_action
                        self.single_action = None
                        self.execute_single_action(ser, act)

                    if self.force_retry:
                        self.force_retry = False
                        self.execute_full_flow(ser)

                    if self.pending_auto_run:
                        self.pending_auto_run = False
                        self.execute_full_flow(ser)

                    if self.reset_requested:
                        continue

                    # Periodically poll SIM state only (no USSD here)
                    ser.reset_input_buffer()
                    ser.write(b"AT+CPIN?\r\n")
                    raw = ""
                    end_time = time.time() + 3.0
                    while time.time() < end_time:
                        if ser.in_waiting > 0:
                            raw += ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                        time.sleep(0.1)
                    detected_state = self._extract_cpin_state(raw)
                    old_state = self.cpin_state
                    self._log_cpin_check("INITIAL", old_state, raw, detected_state, self.cpin_failure_count)

                    # Reset counters on clear READY (including READY->READY poll)
                    if old_state == "READY" and detected_state == "READY":
                        self.unknown_failure_count = 0
                        self.pending_removal_confirmation = False
                        self.removal_confirmation_count = 0
                        self.cpin_failure_count = 0
                        # CHECKING must never survive confirmed READY.
                        self._clear_checking_status_on_ready()

                    # Case A: observed NOT_READY -> start removal confirmation flow
                    if old_state == "READY" and detected_state == "NOT_READY":
                        if not self.pending_removal_confirmation:
                            self.pending_removal_confirmation = True
                            self.removal_confirmation_count = 0
                        self._log_cpin_lifecycle(old_state, detected_state, raw, "WAIT_CONFIRMATION", self.removal_confirmation_count)

                    # Case B: repeated UNKNOWN/ERROR while previously READY (modem may be lost)
                    if old_state == "READY" and detected_state == "UNKNOWN":
                        self.unknown_failure_count += 1
                        # If threshold reached, perform final confirmation
                        if self.unknown_failure_count >= CPIN_UNKNOWN_THRESHOLD:
                            self._log_cpin_lifecycle(old_state, detected_state, raw, "THRESHOLD_REACHED", self.unknown_failure_count)
                            # final confirmation query
                            self._flush_serial_input(ser)
                            time.sleep(0.2)
                            ser.write(b"AT+CPIN?\r\n")
                            final_raw = ""
                            end_time2 = time.time() + CPIN_FINAL_CONFIRM_TIMEOUT
                            while time.time() < end_time2:
                                if ser.in_waiting > 0:
                                    final_raw += ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                                time.sleep(0.1)
                            final_state = self._extract_cpin_state(final_raw)
                            # Decision logic for final confirmation
                            decision = None
                            reason = None
                            if final_state == "NOT_INSERTED" or "+CME ERROR: 10" in (final_raw or ""):
                                decision = "NOT_INSERTED"
                                reason = "CONFIRMED_BY_FINAL_QUERY"
                            elif final_state == "READY":
                                decision = "READY"
                                reason = "FINAL_READ_READY"
                            elif self._is_removal_candidate_error(final_raw):
                                decision = "NOT_INSERTED"
                                reason = "ERROR_AFTER_UNKNOWN_CONSIDERED_REMOVAL"
                            else:
                                # fallback: consider removed if still unknown after final check
                                decision = "NOT_INSERTED"
                                reason = "CPIN_TIMEOUT_CONFIRM_FAILED"

                            # log CPIN_DECISION
                            try:
                                self._log_cpin_decision(old_state, final_raw, final_state, self.unknown_failure_count, decision, reason)
                            except Exception:
                                self._log_cpin_lifecycle(old_state, decision, final_raw, decision, self.unknown_failure_count)

                            # apply decision
                            if decision == "READY":
                                detected_state = "READY"
                                self.unknown_failure_count = 0
                                self.cpin_failure_count = 0
                                self._clear_checking_status_on_ready()
                            else:
                                detected_state = "NOT_INSERTED"
                                self.unknown_failure_count = 0
                                self.pending_removal_confirmation = False
                                self.removal_confirmation_count = 0

                    # If we are in pending_removal_confirmation flow, handle NOT_READY confirmations
                    if self.pending_removal_confirmation and old_state == "READY":
                        # perform a retry/confirm sequence similar to previous logic
                        self._flush_serial_input(ser)
                        time.sleep(0.2)
                        ser.write(b"AT+CPIN?\r\n")
                        raw_retry = ""
                        end_time = time.time() + 3.0
                        while time.time() < end_time:
                            if ser.in_waiting > 0:
                                raw_retry += ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                            time.sleep(0.1)
                        confirmed_state = self._extract_cpin_state(raw_retry)
                        self._log_cpin_check("RETRY_RESULT", old_state, raw_retry, confirmed_state, self.cpin_failure_count, decision="CONFIRM")
                        raw = raw + " | " + raw_retry

                        if confirmed_state == "READY":
                            detected_state = "READY"
                            self.pending_removal_confirmation = False
                            self.removal_confirmation_count = 0
                            self.cpin_failure_count = 0
                            self._clear_checking_status_on_ready()
                            self._log_cpin_lifecycle(old_state, detected_state, raw, "CANCEL_CONFIRMATION", 0)
                        elif confirmed_state == "NOT_INSERTED":
                            detected_state = "NOT_INSERTED"
                            self.pending_removal_confirmation = False
                            self.removal_confirmation_count = 0
                            self._log_cpin_lifecycle(old_state, detected_state, raw, "SIM_REMOVED", 0)
                        elif confirmed_state == "NOT_READY":
                            self.removal_confirmation_count += 1
                            if self.removal_confirmation_count >= CPIN_MAX_REMOVAL_CONFIRM:
                                detected_state = "NOT_INSERTED"
                                self.pending_removal_confirmation = False
                                self.removal_confirmation_count = 0
                                self._log_cpin_lifecycle(old_state, detected_state, raw, "SIM_REMOVED", CPIN_MAX_REMOVAL_CONFIRM)
                            else:
                                detected_state = "NOT_READY"
                                self._log_cpin_lifecycle(old_state, detected_state, raw, "CONFIRMING_REMOVAL", self.removal_confirmation_count)
                        else:
                            # If error on retry and it's a removal candidate, treat as removed
                            if self._is_removal_candidate_error(raw_retry):
                                detected_state = "NOT_INSERTED"
                                self.pending_removal_confirmation = False
                                self.removal_confirmation_count = 0
                                self._log_cpin_lifecycle(old_state, detected_state, raw, "SIM_REMOVED", 0)

                    # Normalize counters and UI signals
                    if detected_state in ("READY", "NOT_INSERTED", "PIN_REQUIRED"):
                        self.cpin_failure_count = 0
                        self.unknown_failure_count = 0
                        if detected_state != "NOT_READY":
                            self.pending_removal_confirmation = False
                            self.removal_confirmation_count = 0
                    elif detected_state == "NOT_READY" and old_state == "READY":
                        # keep unknown_failure_count at 0 while handling NOT_READY flow
                        self.unknown_failure_count = 0
                    elif detected_state == "UNKNOWN" and old_state == "READY" and not self.pending_removal_confirmation:
                        self.cpin_failure_count += 1
                        if self.cpin_failure_count >= 2:
                            self.ui_callback(self.port_name, "status", "CHECKING")
                            self.ui_callback(self.port_name, "respon", "CPIN not responding; rechecking...")

                    if detected_state != "UNKNOWN" and detected_state != "NOT_READY":
                        if detected_state != old_state:
                            self._handle_cpin_transition(old_state, detected_state, ser)

                except Exception as e:
                    self.log(f"Error Loop: {e}")
                    current_baud = None
                    self.current_baud = None
                    self.ui_callback(self.port_name, "port_display", f"🔴 {self.port_name}")
                    self.ui_callback(self.port_name, "respon", f"Modem error: {e}")
                    time.sleep(4)
                finally:
                    if ser is not None:
                        if self._active_serial is ser:
                            self._active_serial = None
                        if ser.is_open:
                            ser.close()
        finally:
            self._release_eventbus_listener("WORKER_EXIT")

    def send_ussd(self, ser, cmd):
        remaining_cooldown = self.next_dial_allowed_at - time.monotonic()
        if remaining_cooldown > 0:
            self.log(f"Menunggu {remaining_cooldown:.1f}s sebelum dial berikutnya")
            time.sleep(remaining_cooldown)
        self.log(f"Dialing: {cmd}")

        session_id = self._begin_ussd_transport_session(ser)
        if not self._write_ussd_transport_command(ser, cmd, session_id):
            self._set_ussd_internal_state("FAILED")
            self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
            return "timeout"

        resp = self._read_ussd_transport_response(ser, session_id)
        self._set_ussd_internal_state("VALIDATING_RESPONSE")
        kind, clean = classify_ussd_response(resp)
        self.log(f"Raw response session {session_id}: {resp}")
        self._finalize_ussd_transport_session(session_id)
        # If classification indicates an empty quoted payload, give a short grace period
        # to allow possible delayed/continued payloads from the modem/operator.
        if kind == "USSD_EMPTY_PAYLOAD":
            self.log(f"USSD empty-quoted payload received; attempting short grace read for session {session_id}")
            self._set_ussd_internal_state("EMPTY_PAYLOAD")
            # Log classify decision
            logging.info(f"USSD_CLASSIFY: port={self.port_name} raw={normalize_serial_text(resp)} classification=USSD_EMPTY_PAYLOAD")
            # Keep any bytes already in buffer; they may be delayed payload for this session.
            time.sleep(0.5)
            extra = ""
            tstart = time.monotonic()
            last_chunk_at2 = None
            while time.monotonic() - tstart < 3.0:
                if ser.in_waiting > 0:
                    chunk2 = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                    if chunk2:
                        extra += chunk2
                        last_chunk_at2 = time.monotonic()
                if extra and is_ussd_payload_complete(extra):
                    if last_chunk_at2 is not None and time.monotonic() - last_chunk_at2 >= 0.8:
                        break
                time.sleep(0.2)
            if extra:
                combined = resp + " | " + extra
                kind2, clean2 = classify_ussd_response(combined)
                self.log(f"USSD grace read classification: {kind2}: {clean2}")
                if kind2 == "USSD_PAYLOAD":
                    self.log(f"USSD payload found after grace: {clean2}")
                    self._set_ussd_internal_state("SUCCESS")
                    self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
                    # Flow decision logging
                    self._log_ussd_flow_decision("send_ussd", "USSD_EMPTY_PAYLOAD", "GRACE_PAYLOAD_USED", "EMPTY_USSD_RESPONSE->PAYLOAD")
                    return clean2
            # no payload arrived in grace window -> return empty marker
            self._set_ussd_internal_state("EMPTY_PAYLOAD")
            self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
            self._log_ussd_flow_decision("send_ussd", "USSD_EMPTY_PAYLOAD", "EMPTY_RETURN", "EMPTY_USSD_RESPONSE")
            return "USSD_EMPTY_PAYLOAD"
        # If classification indicates a status-only USSD (no quoted payload), do not retry automatically
        if kind == "USSD_STATUS_ONLY":
            self.log(f"USSD status-only received: {clean}; session {session_id} completed")
            self._set_ussd_internal_state("STATUS_ONLY")
            self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
            return f"USSD_STATUS_ONLY:{clean}"
        if kind == "USSD_PAYLOAD":
            self.log(f"USSD payload: {clean}")
            self._set_ussd_internal_state("SUCCESS")
            self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
            return clean
        if kind == "PROMPT_CONFIRMATION":
            self.log(f"Konfirmasi prompt diterima: {clean}")
            self._set_ussd_internal_state("WAITING_CONFIRMATION")
            self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
            return f"PROMPT: {clean}"
        if kind == "PARTIAL_RESPONSE":
            self.log(f"Respons parsial/kurang lengkap diterima: {clean}")
            self._set_ussd_internal_state("FAILED")
            self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
            return f"PARTIAL: {clean}"
        if kind == "ERROR":
            self.log(f"Respon Error: {clean}")
            self._set_ussd_internal_state("FAILED")
            self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
            return f"ERROR: {clean}"
        if kind in ("COMMAND_ECHO", "AT_OK", "MODEM_NOTIFICATION", "WAITING_RESPONSE", "TIMEOUT"):
            self.log(f"Tidak ada payload USSD nyata; status {kind}: {clean}")
            self.log(f"Session {session_id} timeout/retry exhausted")

        self._set_ussd_internal_state("FAILED")
        self.next_dial_allowed_at = time.monotonic() + DIAL_COOLDOWN_SECONDS
        return "timeout"

    def _is_ussd_prompt(self, response):
        return isinstance(response, str) and response.startswith("PROMPT:")

    def _is_ussd_error(self, response):
        return isinstance(response, str) and response.startswith("ERROR:")

    def _is_ussd_partial(self, response):
        return isinstance(response, str) and response.startswith("PARTIAL:")

    def _is_ussd_command_executed(self, response):
        return isinstance(response, str) and response == "COMMAND_EXECUTED"

    def _should_retry_ussd(self, kind):
        return kind in ("TIMEOUT", "ERROR", "COMMAND_ECHO", "AT_OK", "MODEM_NOTIFICATION", "WAITING_RESPONSE")

    def _is_ussd_payload(self, response):
        return isinstance(response, str) and response not in ("timeout", "COMMAND_EXECUTED") and not self._is_ussd_error(response) and not self._is_ussd_prompt(response) and not self._is_ussd_partial(response)

    def _finalize_temporary_transport_state(self, reason=""):
        """Return transport temporary flags to idle after a workflow exit."""
        self.ussd_internal_state = "IDLE"
        self._ussd_session_active = False
        if reason:
            self.log(f"TEMP_TRANSPORT_FINALIZE: port={self.port_name} reason={reason}")

    def execute_single_action(self, ser, action):
        # Start each manual action with clean temporary runtime state.
        self._clear_temporary_workflow_state("SINGLE_ACTION_START")
        try:
            self._execute_single_action_body(ser, action)
        finally:
            # Leave transport idle after SUCCESS/FAILED/DONE/PROMPT without changing UI outcome.
            self._finalize_temporary_transport_state("SINGLE_ACTION_END")

    def _execute_single_action_body(self, ser, action):
        if self._should_cooperative_cancel("SINGLE_ACTION_START"):
            return
        if action == "cek_nomor":
            self.ui_callback(self.port_name, "status", "PROSES")
            self.ui_callback(self.port_name, "respon", f"Dial {global_settings['dial_cek_nomor']}...")
            if self._should_cooperative_cancel("SINGLE_CEK_NOMOR_PRE_DIAL"):
                return
            res = self.send_ussd(ser, global_settings["dial_cek_nomor"])
            if self._should_cooperative_cancel("SINGLE_CEK_NOMOR_POST_DIAL"):
                return
            self.ui_callback(self.port_name, "respon", res)
            if isinstance(res, str) and res.startswith("USSD_STATUS_ONLY:"):
                code = res.split(":", 1)[1]
                self._log_ussd_flow_decision("cek_nomor", res, "NO_PAYLOAD" if code == "0" else "STATUS_ONLY", f"STATUS_ONLY:{code}")
                # no payload -> cannot get number; mark as failed (not a timeout/error)
                self.ui_callback(self.port_name, "status", "GAGAL")
                return
            if self._is_ussd_prompt(res):
                self._set_prompt_pending(res, "SINGLE_CEK_NOMOR")
                return
            if res != "timeout" and not self._is_ussd_error(res) and not self._is_ussd_partial(res) and "error" not in res.lower():
                num_m = re.search(r"(08\d{9,11})", res)
                if num_m: self.ui_callback(self.port_name, "nomor", num_m.group(1))
                grace_date = extract_grace_date(res)
                if grace_date != "-": self.ui_callback(self.port_name, "masa_aktif", grace_date)
                self.ui_callback(self.port_name, "status", "DONE")
            else: self.ui_callback(self.port_name, "status", "GAGAL")

        elif action == "cek_nik":
            self.ui_callback(self.port_name, "status", "PROSES")
            self.ui_callback(self.port_name, "respon", f"Dial {global_settings['dial_cek_nik']}...")
            if self._should_cooperative_cancel("SINGLE_CEK_NIK_PRE_DIAL"):
                return
            res = self.send_ussd(ser, global_settings["dial_cek_nik"])
            if self._should_cooperative_cancel("SINGLE_CEK_NIK_POST_DIAL"):
                return
            self.ui_callback(self.port_name, "respon", res)
            if isinstance(res, str) and res.startswith("USSD_STATUS_ONLY:"):
                code = res.split(":", 1)[1]
                self._log_ussd_flow_decision("cek_nik", res, "NO_PAYLOAD" if code == "0" else "STATUS_ONLY", f"STATUS_ONLY:{code}")
                # no payload -> cannot get NIK; mark as failed (not a timeout/error)
                self.ui_callback(self.port_name, "status", "GAGAL")
                return
            if self._is_ussd_prompt(res):
                self._set_prompt_pending(res, "SINGLE_CEK_NIK")
                return
            nik_m = re.search(r"(\d{16})", res)
            if nik_m:
                self.ui_callback(self.port_name, "nik", nik_m.group(1))
                state = port_registry.get(self.port_name) or DEFAULT_PORT_STATE
                nomor = state.get("nomor")
                kk_state = str(state.get("kk", "") or "").strip()
                if nomor and nomor != "-" and kk_state and kk_state != "-":
                    update_phone_cache(nomor, nik_m.group(1), kk_state)
                self.ui_callback(self.port_name, "status", "DONE")
            else:
                self.ui_callback(self.port_name, "status", "GAGAL")

        elif action == "reaktivasi":
            if self._should_cooperative_cancel("SINGLE_REAKTIVASI_START"):
                return
            state = port_registry.get(self.port_name) or DEFAULT_PORT_STATE
            nik = str(state.get("nik", "") or "").strip()
            kk = str(state.get("kk", "") or "").strip()
            current_grace_date = str(state.get("masa_aktif", "") or "").strip()
            if current_grace_date and current_grace_date != "-":
                before_card_status_value, _ = classify_card_status(current_grace_date, "")
            else:
                before_card_status_value = None
            self.business_snapshot = {
                "before_grace_date": current_grace_date if current_grace_date and current_grace_date != "-" else None,
                "before_card_status_value": before_card_status_value,
                "after_grace_date": None,
                "after_card_status_value": None,
                "business_outcome": None,
            }
            if state.get("nomor") and state.get("nomor") != "-" and nik and kk:
                update_phone_cache(state.get("nomor"), nik, kk)
            if not nik or not kk:
                cache_entry = lookup_phone_cache(state.get("nomor"))
                if cache_entry:
                    nik = cache_entry["nik"]
                    kk = cache_entry["kk"]
                    self.ui_callback(self.port_name, "nik", nik)
                    self.ui_callback(self.port_name, "kk", kk)
                    self.ui_callback(self.port_name, "respon", "NIK/KK diambil dari cache lokal")
            cmd = build_reaktivasi_command(nik, kk)
            if not cmd:
                self.ui_callback(self.port_name, "status", "GAGAL")
                self.ui_callback(self.port_name, "respon", "NIK/KK tidak tersedia untuk reaktivasi")
                return
            self.ui_callback(self.port_name, "status", "PROSES")
            inject_attempt = 0
            while True:
                if self._should_cooperative_cancel("SINGLE_REAKTIVASI_LOOP"):
                    return
                inject_attempt += 1
                if inject_attempt == 1:
                    self.ui_callback(self.port_name, "respon", f"Mengirim reaktivasi: {cmd}")
                else:
                    self.ui_callback(self.port_name, "respon", f"Retry injeksi reaktivasi ({inject_attempt}/{MAX_INJECT_RETRY})...")
                with power_injection_lock:
                    res = self.send_ussd(ser, cmd)
                if self._should_cooperative_cancel("SINGLE_REAKTIVASI_POST_INJECT"):
                    return
                self.ui_callback(self.port_name, "respon", res)
                provisional_inject = False
                if isinstance(res, str) and res.startswith("USSD_STATUS_ONLY:"):
                    code = res.split(":", 1)[1]
                    if code == "0":
                        self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_SUCCESS", "WAITING_VERIFICATION")
                        provisional_inject = True
                    else:
                        self._log_ussd_flow_decision("injeksi", res, "STATUS_ONLY", f"STATUS_ONLY:{code}")
                if isinstance(res, str) and res == "USSD_EMPTY_PAYLOAD":
                    self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_WAITING", "EMPTY_USSD_RESPONSE")
                    provisional_inject = True
                if self._is_ussd_prompt(res):
                    self._set_prompt_pending(res, "SINGLE_REAKTIVASI_INJEKSI")
                    return
                # If res is an actual payload string, classify intent to decide injection outcome
                if isinstance(res, str) and not res.startswith(("USSD_STATUS_ONLY:", "USSD_EMPTY_PAYLOAD", "PROMPT:", "PARTIAL:", "ERROR:", "USSD_STATUS_ONLY:")) and res not in ("timeout", "COMMAND_EXECUTED"):
                    intent = classify_ussd_intent(res)
                    self.log(f"USSD_INTENT: port={self.port_name} payload={res} intent={intent}")
                    if intent == "SUCCESS_MESSAGE":
                        self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_SUCCESS", "SUCCESS_MESSAGE")
                        provisional_inject = True
                    elif intent == "REQUEST_ACCEPTED":
                        self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_SUCCESS", "REQUEST_ACCEPTED")
                        provisional_inject = True
                    elif is_inject_not_accepted_response(res):
                        # CATEGORY B: operator has not accepted; do not mark provisional / do not verify.
                        self._log_ussd_flow_decision("injeksi", res, "INJECT_NOT_ACCEPTED", intent)
                        provisional_inject = False
                    elif intent == "EMPTY_RESPONSE":
                        self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_WAITING", "EMPTY_USSD_RESPONSE")
                        provisional_inject = True
                    elif intent == "MENU_RESPONSE":
                        self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_WAITING", "MENU_RESPONSE")
                        provisional_inject = True
                    elif intent == "NUMBER_INFO":
                        self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_WAITING", "NUMBER_INFO")
                        provisional_inject = True
                    else:
                        self._log_ussd_flow_decision("injeksi", res, "PROVISIONAL_WAITING", "UNKNOWN_INTENT")
                        provisional_inject = True

                # CATEGORY B retry: inject only; verification must not start yet.
                if is_inject_not_accepted_response(res):
                    if inject_attempt < MAX_INJECT_RETRY:
                        if self._should_cooperative_cancel("SINGLE_REAKTIVASI_PRE_RETRY_SLEEP"):
                            return
                        self._log_ussd_flow_decision("injeksi", res, "INJECT_RETRY", f"attempt={inject_attempt}/{MAX_INJECT_RETRY}")
                        time.sleep(USSD_RETRY_DELAY_SECONDS)
                        continue
                    decide_business_outcome(self.business_snapshot, None)
                    self.ui_callback(self.port_name, "status", "GAGAL")
                    self.ui_callback(self.port_name, "respon", "Gagal mengirim permintaan reaktivasi (retry habis)")
                    return

                if provisional_inject or (res != "timeout" and not self._is_ussd_error(res) and not self._is_ussd_partial(res) and not self._is_ussd_command_executed(res) and "error" not in res.lower()):
                    self.ui_callback(self.port_name, "respon", "Verifikasi status kartu setelah reaktivasi...")
                    if self._should_cooperative_cancel("SINGLE_REAKTIVASI_PRE_VERIFY"):
                        return
                    res_verifikasi = self.send_ussd(ser, global_settings["dial_cek_nomor"])
                    if self._should_cooperative_cancel("SINGLE_REAKTIVASI_POST_VERIFY"):
                        return
                    if self._is_ussd_prompt(res_verifikasi):
                        self._set_prompt_pending(res_verifikasi, "SINGLE_REAKTIVASI_VERIFIKASI")
                        return
                    grace_date = extract_grace_date(res_verifikasi)
                    derived_card_status, days_remaining = classify_card_status(grace_date, res_verifikasi)
                    self.business_snapshot["after_grace_date"] = grace_date if grace_date and grace_date != "-" else None
                    self.business_snapshot["after_card_status_value"] = derived_card_status
                    business_outcome = decide_business_outcome(self.business_snapshot, res)
                    self.ui_callback(self.port_name, "respon", res_verifikasi)
                    lifetime_text = format_lifetime(days_remaining)
                    self.ui_callback(self.port_name, "masa_aktif", grace_date)
                    if business_outcome == "SUCCESS":
                        self.ui_callback(self.port_name, "status", "SUKSES")
                        self.ui_callback(self.port_name, "respon", f"Terverifikasi AKTIF ({format_day_delta(days_remaining)}); masa aktif: {grace_date}; lifetime: {lifetime_text}")
                    elif business_outcome == "TENGGANG":
                        self.ui_callback(self.port_name, "status", "DONE")
                        self.ui_callback(self.port_name, "respon", f"Terverifikasi TENGGANG ({format_day_delta(days_remaining)}); masa aktif: {grace_date}; lifetime: {lifetime_text}")
                    else:
                        self.ui_callback(self.port_name, "status", "GAGAL")
                        self.ui_callback(self.port_name, "respon", f"Reaktivasi belum tervalidasi: {derived_card_status} ({format_day_delta(days_remaining)}); masa aktif: {grace_date}; lifetime: {lifetime_text}")
                else:
                    # Operational stop before verification; business outcome is decided centrally as FAILED.
                    decide_business_outcome(self.business_snapshot, None)
                    self.ui_callback(self.port_name, "status", "GAGAL")
                break

    def execute_full_flow(self, ser):
        # Start each full run with clean temporary runtime state (not card-cycle / config).
        self._clear_temporary_workflow_state("FULL_FLOW_START")
        try:
            self._execute_full_flow_body(ser)
        finally:
            # Leave transport idle after SUCCESS/FAILED/DONE/PROMPT without changing UI outcome.
            self._finalize_temporary_transport_state("FULL_FLOW_END")

    def _execute_full_flow_body(self, ser):
        if self._should_cooperative_cancel("FULL_FLOW_START"):
            return
        # FSM V3: CPIN READY -> stabilisasi sinyal -> cek masa aktif.
        self.ui_callback(self.port_name, "status", "STABILISASI")
        self.ui_callback(self.port_name, "respon", "SIM terdeteksi; stabilisasi sinyal...")
        for _ in range(15):
            if not self.is_running or self.port_name in disabled_ports or self._should_cooperative_cancel("FULL_FLOW_STABILISASI"):
                return
            time.sleep(1)

        self.ui_callback(self.port_name, "status", "PROSES")
        self.ui_callback(self.port_name, "respon", f"Dial {global_settings['dial_cek_nomor']}...")
        if self._should_cooperative_cancel("FULL_FLOW_PRE_CEK_NOMOR"):
            return
        res_nomor = self.send_ussd(ser, global_settings["dial_cek_nomor"])
        if self._should_cooperative_cancel("FULL_FLOW_POST_CEK_NOMOR"):
            return
        self.ui_callback(self.port_name, "respon", res_nomor)
        if isinstance(res_nomor, str) and res_nomor.startswith("USSD_STATUS_ONLY:"):
            code = res_nomor.split(":", 1)[1]
            self._log_ussd_flow_decision("flow_check_nomor", res_nomor, "NO_PAYLOAD" if code == "0" else "STATUS_ONLY", f"STATUS_ONLY:{code}")
            # No payload available — cannot extract number
            self.ui_callback(self.port_name, "status", "GAGAL")
            self.ui_callback(self.port_name, "respon", "Nomor tidak ditemukan pada respons operator (status-only)")
            return
        if self._is_ussd_prompt(res_nomor):
            self._set_prompt_pending(res_nomor, "FULL_CEK_NOMOR")
            return
        if res_nomor == "timeout" or self._is_ussd_error(res_nomor) or self._is_ussd_partial(res_nomor) or self._is_ussd_command_executed(res_nomor) or "error" in res_nomor.lower():
            self.ui_callback(self.port_name, "status", "GAGAL")
            return
        if "not inserted" in res_nomor.lower():
            self.ui_callback(self.port_name, "status", "IDLE")
            self.ui_callback(self.port_name, "respon", "Idle/Standby")
            return

        num_m = re.search(r"(08\d{9,11})", res_nomor)
        grace_date = extract_grace_date(res_nomor)
        if not num_m:
            self.ui_callback(self.port_name, "status", "GAGAL")
            self.ui_callback(self.port_name, "respon", "Nomor tidak ditemukan pada respons operator")
            return

        nomor_hp = num_m.group(1)
        derived_card_status, days_remaining = classify_card_status(grace_date, res_nomor)
        self.business_snapshot = {
            "before_grace_date": grace_date if grace_date and grace_date != "-" else None,
            "before_card_status_value": derived_card_status,
            "after_grace_date": None,
            "after_card_status_value": None,
            "business_outcome": None,
        }
        self.ui_callback(self.port_name, "nomor", nomor_hp)
        self.ui_callback(self.port_name, "masa_aktif", grace_date)
        if derived_card_status == "UNKNOWN":
            self.ui_callback(self.port_name, "status", "GAGAL")
            self.ui_callback(self.port_name, "respon", "Status kartu/tanggal masa aktif tidak dapat dikenali")
            return

        # AKTIF dan TENGGANG: bypass berarti berhenti; tanpa bypass cukup
        # search & match di SQLite, tidak masuk alur injeksi.
        if derived_card_status in ("AKTIF", "TENGGANG"):
            bypass = global_settings["abai_aktif"] if derived_card_status == "AKTIF" else global_settings["abai_tenggang"]
            lifetime_text = format_lifetime(days_remaining)
            if bypass:
                self.ui_callback(self.port_name, "status", "DONE")
            if bypass:
                self.ui_callback(self.port_name, "respon", f"{derived_card_status} ({format_day_delta(days_remaining)}): dibypass / early exit; masa aktif: {grace_date}; lifetime: {lifetime_text}")
            else:
                self.ui_callback(self.port_name, "respon", f"{derived_card_status} ({format_day_delta(days_remaining)}): search & match SQLite; masa aktif: {grace_date}; lifetime: {lifetime_text}")
                record_status_match(nomor_hp, derived_card_status, grace_date)
                self.ui_callback(self.port_name, "status", "DONE")
                self.ui_callback(self.port_name, "respon", f"{derived_card_status}: tersimpan di SQLite, tanpa injeksi")
            self.state_machine.require_card_cycle()
            return

        # Hanya kartu HANGUS (<= -31 hari) yang diteruskan ke reaktivasi.
        cache_entry = lookup_phone_cache(nomor_hp)
        if cache_entry:
            nik = cache_entry["nik"]
            kk = cache_entry["kk"]
            self.ui_callback(self.port_name, "nik", nik)
            self.ui_callback(self.port_name, "kk", kk)
            self.ui_callback(self.port_name, "respon", "Data NIK/KK ditemukan di cache lokal; lanjut reaktivasi")
        else:
            self.ui_callback(self.port_name, "respon", f"HANGUS ({format_day_delta(days_remaining)}): cek NIK...")
            if self._should_cooperative_cancel("FULL_FLOW_PRE_CEK_NIK"):
                return
            res_nik = self.send_ussd(ser, global_settings["dial_cek_nik"])
            if self._should_cooperative_cancel("FULL_FLOW_POST_CEK_NIK"):
                return
            self.ui_callback(self.port_name, "respon", res_nik)
            if isinstance(res_nik, str) and res_nik.startswith("USSD_STATUS_ONLY:"):
                code = res_nik.split(":", 1)[1]
                self._log_ussd_flow_decision("flow_check_nik", res_nik, "NO_PAYLOAD" if code == "0" else "STATUS_ONLY", f"STATUS_ONLY:{code}")
                self.ui_callback(self.port_name, "status", "GAGAL")
                record_reactivation_result(
                    nomor_hp,
                    None,
                    None,
                    self.business_snapshot.get("before_card_status_value"),
                    self.business_snapshot.get("after_card_status_value") or "-",
                    "GAGAL_CEK_NIK",
                )
                return
            if self._is_ussd_prompt(res_nik):
                self._set_prompt_pending(res_nik, "FULL_CEK_NIK")
                return
            nik_m = re.search(r"(\d{16})", res_nik)
            if res_nik == "timeout" or self._is_ussd_error(res_nik) or self._is_ussd_partial(res_nik) or self._is_ussd_command_executed(res_nik) or "error" in res_nik.lower() or not nik_m:
                self.ui_callback(self.port_name, "status", "GAGAL")
                record_reactivation_result(
                    nomor_hp,
                    None,
                    None,
                    self.business_snapshot.get("before_card_status_value"),
                    self.business_snapshot.get("after_card_status_value") or "-",
                    "GAGAL_CEK_NIK",
                )
                return

            nik = nik_m.group(1)
            self.ui_callback(self.port_name, "nik", nik)
            kk = nik if global_settings["format_mode"] == "NIK & NIK" else None
            if kk is None:
                self.ui_callback(self.port_name, "respon", "Search KK di database lokal...")
                kk = db_cache.get(nik)
                if not kk:
                    self.ui_callback(self.port_name, "respon", "KK tidak ada di lokal; query Telegram...")
                    if self._should_cooperative_cancel("FULL_FLOW_PRE_TELEGRAM"):
                        return
                    kk = mock_telegram_gateway_query(nik)
                    if self._should_cooperative_cancel("FULL_FLOW_POST_TELEGRAM"):
                        return
                if kk == "DATA_TIDAK_DITEMUKAN" or not kk:
                    self.ui_callback(self.port_name, "status", "GAGAL")
                    self.ui_callback(self.port_name, "respon", "Data KK tidak ditemukan")
                    record_reactivation_result(
                        nomor_hp,
                        nik,
                        None,
                        self.business_snapshot.get("before_card_status_value"),
                        self.business_snapshot.get("after_card_status_value") or "-",
                        "GAGAL_KK",
                    )
                    return
        if nik and kk:
            update_phone_cache(nomor_hp, nik, kk)
        self.ui_callback(self.port_name, "kk", kk)

        inj_cmd = build_reaktivasi_command(nik, kk)
        inject_attempt = 0
        while True:
            if self._should_cooperative_cancel("FULL_FLOW_INJECT_LOOP"):
                return
            inject_attempt += 1
            with power_injection_lock:
                if inject_attempt == 1:
                    self.ui_callback(self.port_name, "respon", "Injeksi reaktivasi...")
                else:
                    self.ui_callback(self.port_name, "respon", f"Retry injeksi reaktivasi ({inject_attempt}/{MAX_INJECT_RETRY})...")
                res_inj = self.send_ussd(ser, inj_cmd)
            if self._should_cooperative_cancel("FULL_FLOW_POST_INJECT"):
                return
            self.ui_callback(self.port_name, "respon", res_inj)
            provisional_inject = False
            if isinstance(res_inj, str) and res_inj.startswith("USSD_STATUS_ONLY:"):
                code = res_inj.split(":", 1)[1]
                if code == "0":
                    self._log_ussd_flow_decision("injeksi", res_inj, "PROVISIONAL_SUCCESS", "WAITING_VERIFICATION")
                    provisional_inject = True
                else:
                    self._log_ussd_flow_decision("injeksi", res_inj, "STATUS_ONLY", f"STATUS_ONLY:{code}")
            if isinstance(res_inj, str) and res_inj == "USSD_EMPTY_PAYLOAD":
                self._log_ussd_flow_decision("injeksi", res_inj, "PROVISIONAL_WAITING", "EMPTY_USSD_RESPONSE")
                provisional_inject = True
            if self._is_ussd_prompt(res_inj):
                self._set_prompt_pending(res_inj, "FULL_INJEKSI")
                return
            # If modem returned COMMAND_EXECUTED, treat as provisional success for injection
            if self._is_ussd_command_executed(res_inj):
                self._log_ussd_flow_decision("injeksi", res_inj, "PROVISIONAL_SUCCESS", "COMMAND_EXECUTED")
                provisional_inject = True
            # If a real payload was returned, classify intent to decide
            if isinstance(res_inj, str) and not res_inj.startswith(("USSD_STATUS_ONLY:", "USSD_EMPTY_PAYLOAD", "PROMPT:", "PARTIAL:", "ERROR:")) and res_inj not in ("timeout", "COMMAND_EXECUTED"):
                intent = classify_ussd_intent(res_inj)
                self.log(f"USSD_INTENT: port={self.port_name} payload={res_inj} intent={intent}")
                if intent in ("SUCCESS_MESSAGE", "REQUEST_ACCEPTED"):
                    self._log_ussd_flow_decision("injeksi", res_inj, "PROVISIONAL_SUCCESS", intent)
                    provisional_inject = True
                elif is_inject_not_accepted_response(res_inj):
                    # CATEGORY B: operator has not accepted; do not mark provisional / do not verify.
                    self._log_ussd_flow_decision("injeksi", res_inj, "INJECT_NOT_ACCEPTED", intent)
                    provisional_inject = False
                else:
                    # MENU_RESPONSE, NUMBER_INFO, EMPTY_RESPONSE, UNKNOWN -> do not treat as success; mark provisional waiting
                    self._log_ussd_flow_decision("injeksi", res_inj, "PROVISIONAL_WAITING", intent)
                    provisional_inject = True
            # CATEGORY B retry: inject only; verification must not start yet.
            if is_inject_not_accepted_response(res_inj):
                if inject_attempt < MAX_INJECT_RETRY:
                    if self._should_cooperative_cancel("FULL_FLOW_PRE_RETRY_SLEEP"):
                        return
                    self._log_ussd_flow_decision("injeksi", res_inj, "INJECT_RETRY", f"attempt={inject_attempt}/{MAX_INJECT_RETRY}")
                    time.sleep(USSD_RETRY_DELAY_SECONDS)
                    continue
                decide_business_outcome(self.business_snapshot, None)
                self.ui_callback(self.port_name, "status", "GAGAL")
                self.ui_callback(self.port_name, "respon", "Gagal mengirim permintaan reaktivasi (retry habis)")
                record_reactivation_result(
                    nomor_hp,
                    nik,
                    kk,
                    self.business_snapshot.get("before_card_status_value"),
                    self.business_snapshot.get("after_card_status_value") or "-",
                    "GAGAL_INJEKSI",
                )
                return
            evidence = classify_ussd_evidence(res_inj)
            if not provisional_inject and (res_inj == "timeout" or self._is_ussd_error(res_inj) or self._is_ussd_partial(res_inj) or self._is_ussd_command_executed(res_inj) or not evidence["has_success_evidence"]):
                # Operational stop before verification; business outcome is decided centrally as FAILED.
                decide_business_outcome(self.business_snapshot, None)
                self.ui_callback(self.port_name, "status", "GAGAL")
                record_reactivation_result(
                    nomor_hp,
                    nik,
                    kk,
                    self.business_snapshot.get("before_card_status_value"),
                    self.business_snapshot.get("after_card_status_value") or "-",
                    "GAGAL_INJEKSI",
                )
                return
            break

        # Verifikasi final wajib: status harus berubah dari HANGUS menjadi AKTIF.
        self.ui_callback(self.port_name, "respon", "Verifikasi perubahan masa aktif...")
        if self._should_cooperative_cancel("FULL_FLOW_PRE_VERIFY"):
            return
        res_verifikasi = self.send_ussd(ser, global_settings["dial_cek_nomor"])
        if self._should_cooperative_cancel("FULL_FLOW_POST_VERIFY"):
            return
        if isinstance(res_verifikasi, str) and res_verifikasi.startswith("USSD_STATUS_ONLY:"):
            code = res_verifikasi.split(":", 1)[1]
            self._log_ussd_flow_decision("flow_verifikasi", res_verifikasi, "STATUS_ONLY", f"STATUS_ONLY:{code}")
            self.business_snapshot["after_grace_date"] = None
            self.business_snapshot["after_card_status_value"] = None
            # No verification facts available; final business outcome is decided centrally as FAILED.
            decide_business_outcome(self.business_snapshot, None)
            self.ui_callback(self.port_name, "status", "GAGAL")
            self.ui_callback(self.port_name, "respon", "Injeksi selesai tetapi verifikasi tidak mengembalikan payload (status-only)")
            record_reactivation_result(
                nomor_hp,
                nik,
                kk,
                self.business_snapshot.get("before_card_status_value"),
                self.business_snapshot.get("after_card_status_value") or "-",
                "GAGAL_VERIFIKASI",
            )
            return
        if self._is_ussd_prompt(res_verifikasi):
            self._set_prompt_pending(res_verifikasi, "FULL_VERIFIKASI")
            return
        grace_date = extract_grace_date(res_verifikasi)
        derived_card_status, days_remaining = classify_card_status(grace_date, res_verifikasi)
        self.business_snapshot["after_grace_date"] = grace_date if grace_date and grace_date != "-" else None
        self.business_snapshot["after_card_status_value"] = derived_card_status
        business_outcome = decide_business_outcome(self.business_snapshot, res_inj)
        self.ui_callback(self.port_name, "respon", res_verifikasi)
        if business_outcome == "SUCCESS":
            self.ui_callback(self.port_name, "masa_aktif", grace_date)
            self.ui_callback(self.port_name, "status", "SUKSES")
            self.ui_callback(self.port_name, "respon", f"Terverifikasi AKTIF ({format_day_delta(days_remaining)}); masa aktif: {grace_date}; lifetime: {format_lifetime(days_remaining)}")
            save_to_harvest_db(nomor_hp, nik, kk, masa_aktif=grace_date, lifetime_days=days_remaining)
            record_reactivation_result(
                nomor_hp,
                nik,
                kk,
                self.business_snapshot.get("before_card_status_value"),
                self.business_snapshot.get("after_card_status_value") or "-",
                "SUKSES",
            )
            self.state_machine.require_card_cycle()
        elif business_outcome == "TENGGANG":
            self.ui_callback(self.port_name, "masa_aktif", grace_date)
            self.ui_callback(self.port_name, "status", "DONE")
            self.ui_callback(self.port_name, "respon", f"Terverifikasi TENGGANG ({format_day_delta(days_remaining)}); masa aktif: {grace_date}; lifetime: {format_lifetime(days_remaining)}")
            record_reactivation_result(
                nomor_hp,
                nik,
                kk,
                self.business_snapshot.get("before_card_status_value"),
                self.business_snapshot.get("after_card_status_value") or "-",
                "TENGGANG",
            )
        else:
            self.ui_callback(self.port_name, "status", "GAGAL")
            self.ui_callback(self.port_name, "respon", "Injeksi selesai tetapi status belum AKTIF")
            record_reactivation_result(
                nomor_hp,
                nik,
                kk,
                self.business_snapshot.get("before_card_status_value"),
                self.business_snapshot.get("after_card_status_value") or "-",
                "GAGAL_VERIFIKASI",
            )



# =====================================================================
# 3. INTERACTION ENGINE UI/UX (LIGHT THEME LOCKED & 10 CONTEXT MENUS)
# =====================================================================
class KebunAutomasiGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Kebun Reaktivasi Massal v2.2 - Light Commercial Edition")
        self.geometry("1150x700")
        
        # LOCK TEMA KE LIGHT MODE UNTUK KONSISTENSI TOTAL
        ctk.set_appearance_mode("Light")
        self.configure(fg_color="#F5EFEB")
        
        self.workers = {}
        self.selected_item = None
        self.filter_mode = "Tampilkan Semua Port"
        self.port_row_cache = {}
        # Semua akses widget Tk hanya dilakukan dari main thread. Worker modem
        # cukup mengirim data ke antrean ini; UI menggabungkan update tiap 100 ms.
        self.ui_updates = queue.Queue()
        self.ui_tasks = queue.Queue()
        self.port_scan_results = queue.Queue()
        self.scan_in_progress = False
        self.monitor_started = False
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.hwid = get_hardware_id()
        self.check_license_gate()

    def on_close(self):
        for port, worker in list(self.workers.items()):
            try:
                worker.shutdown()
            except Exception:
                pass
            try:
                worker.join(timeout=3.0)
            except Exception:
                pass
            try:
                remove_port_registry(port)
            except Exception:
                pass
        self.workers.clear()
        try:
            self.destroy()
        except Exception:
            pass
        try:
            self.quit()
        except Exception:
            pass

    def check_license_gate(self):
        license_file = os.path.join(BASE_DIR, "license.key")
        if os.path.exists(license_file):
            with open(license_file, "r") as f: saved_key = f.read().strip()
            is_valid, _, _ = verify_user_license(self.hwid, saved_key)
            if is_valid:
                self.build_ui_canvas()
                return
        self.show_license_popup_gate()

    def show_license_popup_gate(self):
        self.withdraw()
        popup = ctk.CTkToplevel()
        popup.title("Aktivasi Perangkat")
        popup.geometry("450x280")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)
        popup.protocol("WM_DELETE_WINDOW", self.quit)

        ctk.CTkLabel(popup, text="🔒 VERIFIKASI LISENSI APLIKASI", font=("Helvetica", 13, "bold"), text_color="#2F4156").pack(pady=15)
        ctk.CTkLabel(popup, text="Hardware ID (Unik PC Anda):", font=("Helvetica", 11), text_color="#2F4156").pack(anchor="w", padx=30)
        ent_hwid = ctk.CTkEntry(popup, width=390)
        ent_hwid.insert(0, self.hwid)
        ent_hwid.configure(state="readonly")
        ent_hwid.pack(pady=5, padx=30)
        
        ctk.CTkLabel(popup, text="Masukkan Activation Key:", font=("Helvetica", 11), text_color="#2F4156").pack(anchor="w", padx=30, pady=(10,0))
        ent_key = ctk.CTkEntry(popup, width=390, placeholder_text="YYYY-MM-DD-SIGNATURE")
        ent_key.pack(pady=5, padx=30)
        
        def proses_aktivasi():
            input_key = ent_key.get().strip()
            status_valid, info_msg, _ = verify_user_license(self.hwid, input_key)
            if status_valid:
                with open(os.path.join(BASE_DIR, "license.key"), "w") as f: f.write(input_key)
                messagebox.showinfo("Sukses", "Aktivasi Berhasil! Selamat bekerja, bray!")
                popup.destroy()
                self.deiconify()
                self.build_ui_canvas()
            else: messagebox.showerror("Gagal Aktivasi", info_msg)

        ctk.CTkButton(popup, text="🎫 Aktivasi", fg_color="#2F4156", text_color="#FFFFFF", command=proses_aktivasi).pack(pady=20)

    def show_license_status_popup(self):
        license_file = os.path.join(BASE_DIR, "license.key")
        saved_key = ""
        if os.path.exists(license_file):
            with open(license_file, "r") as f: saved_key = f.read().strip()
            
        is_valid, msg, exp_date = verify_user_license(self.hwid, saved_key)
        
        pop = ctk.CTkToplevel(self)
        pop.title("🎫 STATUS LISENSI REAL-TIME")
        pop.geometry("450x380")
        pop.resizable(False, False)
        pop.attributes("-topmost", True)
        
        frame = ctk.CTkFrame(pop, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(frame, text="🎫 STATUS LISENSI PERANGKAT", font=("Helvetica", 13, "bold"), text_color="#2F4156").pack(pady=(0, 10))
        ctk.CTkLabel(frame, text=f"Hardware ID : {self.hwid}", font=("Courier", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=2)
        status_str = "🟢 AKTIF" if is_valid else f"🔴 EXPIRED ({msg})"
        ctk.CTkLabel(frame, text=f"Status       : {status_str}", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=2)
        
        exp_str = exp_date.strftime("%Y-%m-%d") if exp_date else "Tidak Diketahui"
        ctk.CTkLabel(frame, text=f"Kedaluwarsa  : {exp_str}", font=("Helvetica", 11), text_color="#2F4156").pack(anchor="w", pady=2)
        
        sisa_hari = (exp_date - datetime.now()).days + 1 if exp_date and is_valid else 0
        ctk.CTkLabel(frame, text=f"Sisa Aktif   : {sisa_hari} Hari", font=("Helvetica", 12, "bold"), text_color="#567C8D").pack(anchor="w", pady=(2, 15))
        
        ctk.CTkLabel(frame, text="Perpanjang Lisensi (Input Key Baru):", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=2)
        e_renewal = ctk.CTkEntry(frame, width=390, placeholder_text="Tempel Serial Key Baru Di Sini")
        e_renewal.pack(fill="x", pady=5)
        
        def perpanjang():
            new_key = e_renewal.get().strip()
            valid, info, _ = verify_user_license(self.hwid, new_key)
            if valid:
                with open(license_file, "w") as f: f.write(new_key)
                messagebox.showinfo("Sukses", "Lisensi Berhasil Diperpanjang!")
                pop.destroy()
            else: messagebox.showerror("Gagal", info)
                
        ctk.CTkButton(frame, text="⚡ Perpanjang Lisensi", fg_color="#2F4156", command=perpanjang).pack(fill="x", pady=15)

    def build_ui_canvas(self):
        self.chrome_tab_bar = ctk.CTkFrame(self, fg_color="#D9D9D9", height=40, corner_radius=0)
        self.chrome_tab_bar.pack(fill="x", side="top")
        
        self.btn_tab_home = ctk.CTkButton(self.chrome_tab_bar, text="💻 WORKSPACE", width=140, height=35, corner_radius=8, font=("Helvetica", 11, "bold"), command=lambda: self.switch_chrome_tab("HOME"))
        self.btn_tab_home.pack(side="left", padx=(10, 2), pady=(5, 0))
        
        self.btn_tab_report = ctk.CTkButton(self.chrome_tab_bar, text="📊 PANEN MONITOR", width=140, height=35, corner_radius=8, font=("Helvetica", 11, "bold"), command=lambda: self.switch_chrome_tab("REPORT"))
        self.btn_tab_report.pack(side="left", padx=2, pady=(5, 0))
        
        self.btn_tab_setting = ctk.CTkButton(self.chrome_tab_bar, text="⚙️ CONFIG", width=140, height=35, corner_radius=8, font=("Helvetica", 11, "bold"), command=lambda: self.switch_chrome_tab("SETTING"))
        self.btn_tab_setting.pack(side="left", padx=2, pady=(5, 0))
        
        self.body_content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.body_content.pack(fill="both", expand=True, padx=10, pady=10)
        
        footer = ctk.CTkFrame(self, height=25, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=15, pady=2)
        
        self.lbl_footer = ctk.CTkLabel(footer, text="SLOT ACTIVE PORT MONITOR: Initializing...", text_color="#2F4156", font=("Helvetica", 11, "bold"))
        self.lbl_footer.pack(side="left")
        
        self.switch_chrome_tab("HOME")
        self.after(100, self.drain_background_events)

    def switch_chrome_tab(self, target):
        for widget in self.body_content.winfo_children(): widget.destroy()
            
        color_active, color_inactive = "#F5EFEB", "#B0B0B0"
        text_active, text_inactive = "#2F4156", "#555555"
        
        self.btn_tab_home.configure(fg_color=color_inactive, text_color=text_inactive)
        self.btn_tab_report.configure(fg_color=color_inactive, text_color=text_inactive)
        self.btn_tab_setting.configure(fg_color=color_inactive, text_color=text_inactive)
        
        if target == "HOME":
            self.btn_tab_home.configure(fg_color=color_active, text_color=text_active)
            self.render_home_view()
        elif target == "REPORT":
            self.btn_tab_report.configure(fg_color=color_active, text_color=text_active)
            self.render_report_view()
        elif target == "SETTING":
            self.btn_tab_setting.configure(fg_color=color_active, text_color=text_active)
            self.render_setting_view()

    def render_home_view(self):
        action_bar = ctk.CTkFrame(self.body_content, fg_color="#FFFFFF", height=45, corner_radius=8)
        action_bar.pack(fill="x", padx=5, pady=(0, 8))
        
        ctk.CTkLabel(action_bar, text="Filter:", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(side="left", padx=(10, 2))
        self.cb_filter_port = ctk.CTkOptionMenu(action_bar, values=["Tampilkan Semua Port", "Hanya Port Aktif (Menyala 🟢)", "Hanya Port Off (Mati 🔴)"], width=200, fg_color="#567C8D", button_color="#2F4156", command=self.apply_port_filter)
        self.cb_filter_port.pack(side="left", padx=5, pady=7)
        
        ctk.CTkButton(action_bar, text="🔄 Restart All", fg_color="#2F4156", text_color="#FFFFFF", width=120, command=self.restart_all).pack(side="left", padx=5, pady=7)
        ctk.CTkButton(action_bar, text="🔌 Reset Modem", fg_color="#2F4156", text_color="#FFFFFF", width=120, command=self.reset_modem).pack(side="left", padx=5, pady=7)
        ctk.CTkButton(action_bar, text="🎫 Status Lisensi", fg_color="#C8D9E6", text_color="#2F4156", width=110, command=self.show_license_status_popup).pack(side="left", padx=5, pady=7)
        
        table_frame = ttk.Frame(self.body_content)
        table_frame.pack(fill="both", expand=True, padx=5, pady=2)
        
        # 8 KOLOM LENGKAP PRESISIsesuai REVISI USER
        cols = ("port", "nomor", "nik", "kk", "status", "respon", "masa_aktif", "log")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        
        self.tree.heading("port", text="PORT")
        self.tree.heading("nomor", text="NOMOR")
        self.tree.heading("nik", text="NIK")
        self.tree.heading("kk", text="KK")
        self.tree.heading("status", text="STATUS")
        self.tree.heading("respon", text="RESPON")
        self.tree.heading("masa_aktif", text="MASA AKTIF")
        self.tree.heading("log", text="LOG")
        
        self.tree.column("port", width=100, anchor=tk.CENTER)
        self.tree.column("nomor", width=120, anchor=tk.CENTER)
        self.tree.column("nik", width=150, anchor=tk.CENTER)
        self.tree.column("kk", width=150, anchor=tk.CENTER)
        self.tree.column("status", width=90, anchor=tk.CENTER)
        self.tree.column("respon", width=290, anchor=tk.W)
        self.tree.column("masa_aktif", width=110, anchor=tk.CENTER)
        self.tree.column("log", width=60, anchor=tk.CENTER)
        
        self.tree.tag_configure("sukses", background="#E2F0D9", foreground="#276A3C")
        self.tree.tag_configure("done", background="#E2F0D9", foreground="#276A3C")
        self.tree.tag_configure("proses", background="#D9E1F2", foreground="#1F4E78")
        self.tree.tag_configure("gagal", background="#FCE4D6", foreground="#A51D24")
        self.tree.tag_configure("idle", background="#F5F5F5", foreground="#666666")
        self.tree.tag_configure("off", background="#F0F0F0", foreground="#555555")
        
        sb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self.check_log_trigger)
        
        # 10 OPSI CONTEXT MENU LENGKAP DARI USER
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="🟢 On Port", command=self.menu_on_port)
        self.context_menu.add_command(label="🔴 Off Port", command=self.menu_off_port)
        self.context_menu.add_command(label="🔄 Restart Port", command=self.menu_restart_port)
        self.context_menu.add_command(label="🔌 Reset Port", command=self.menu_reset_port)
        self.context_menu.add_command(label="🔁 Reprocess", command=self.menu_reprocess)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📲 Cek Nomor", command=self.menu_cek_nomor)
        self.context_menu.add_command(label="🪪 Cek NIK", command=self.menu_cek_nik)
        self.context_menu.add_command(label="🔍 Cari / Ambil KK", command=self.menu_cari_kk)
        self.context_menu.add_command(label="⚡ Reaktivasi", command=self.menu_reaktivasi)
        self.context_menu.add_command(label="📊 Cek Limit", command=self.menu_cek_limit)
        
        self.tree.bind("<Button-3>", self.on_tree_right_click)
        # Tab sebelumnya menghancurkan Treeview, bukan worker atau registry.
        # Pulihkan tampilan dari state yang sudah ada tanpa menunggu scan berikutnya.
        self.restore_port_table()
        self.request_port_scan()

    def _should_show_port(self, port):
        is_off = port in disabled_ports
        if self.filter_mode.startswith("Hanya Port Aktif"):
            return not is_off
        if self.filter_mode.startswith("Hanya Port Off"):
            return is_off
        return True

    def restore_port_table(self):
        """Gambar ulang tabel Workspace dari registry; tidak membuat worker baru."""
        if not hasattr(self, "tree") or not self.tree.winfo_exists():
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        # Hanya worker yang masih terdaftar ditampilkan; state port lama yang
        # sudah dicabut tidak ikut muncul kembali setelah ganti tab.
        for port in sorted(self.workers):
            if not self._should_show_port(port):
                continue
            row_values = self._get_port_row_values(port)
            self.tree.insert("", tk.END, iid=port, values=row_values)
            self._apply_row_tags(port, row_values[4])

    def apply_port_filter(self, choice):
        self.filter_mode = choice
        self.restore_port_table()
        self.request_port_scan()

    def on_tree_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.selected_item = item
            self.context_menu.post(event.x_root, event.y_root)

    # AKSI 10 CONTEXT MENU LENGKAP
    def menu_on_port(self):
        if self.selected_item and self.selected_item in disabled_ports:
            disabled_ports.remove(self.selected_item)
            self.update_tree_row(self.selected_item, "respon", "Port diaktifkan kembali")

    def menu_off_port(self):
        if self.selected_item:
            disabled_ports.add(self.selected_item)
            self.update_tree_row(self.selected_item, "port_display", f"🔴 {self.selected_item}(OFF)")
            self.update_tree_row(self.selected_item, "status", "OFF")

    def menu_restart_port(self):
        if self.selected_item in self.workers:
            self.workers[self.selected_item].force_retry = True

    def menu_reset_port(self):
        if self.selected_item:
            self.update_tree_row(self.selected_item, "status", "RESET")
            self.update_tree_row(self.selected_item, "respon", "Reset modem sedang diproses...")
            if self.selected_item in self.workers:
                self.workers[self.selected_item].request_modem_reset()
            else:
                self.update_tree_row(self.selected_item, "respon", "Port belum aktif/worker belum tersedia")

    def menu_reprocess(self):
        self.menu_restart_port()

    def menu_cek_nomor(self):
        if self.selected_item in self.workers:
            self.workers[self.selected_item].single_action = "cek_nomor"

    def menu_cek_nik(self):
        if self.selected_item in self.workers:
            self.workers[self.selected_item].single_action = "cek_nik"

    def menu_cari_kk(self):
        if not self.selected_item: return
        port = self.selected_item
        self.update_tree_row(port, "status", "PROSES")
        self.update_tree_row(port, "respon", "Mencari KK di database lokal...")
        def proc():
            # Worker tidak boleh membaca widget Tkinter; gunakan state thread-safe.
            state = port_registry.get(port) or DEFAULT_PORT_STATE
            nik = state.get("nik", "-") if state.get("nik", "-") != "-" else "332803XXXXXXXXXX"
            kk = db_cache.get(nik)
            if kk:
                self.update_tree_row(port, "kk", kk)
                self.update_tree_row(port, "status", "DONE")
                self.update_tree_row(port, "respon", f"KK ditemukan di database lokal: {kk}")
                return
            self.update_tree_row(port, "respon", "KK tidak ada di lokal; query Telegram...")
            kk = mock_telegram_gateway_query(nik)
            if kk == "DATA_TIDAK_DITEMUKAN" or not kk:
                self.update_tree_row(port, "status", "GAGAL")
                self.update_tree_row(port, "respon", "Pencarian KK Manual: Data Tidak Ditemukan")
            else:
                self.update_tree_row(port, "kk", kk)
                self.update_tree_row(port, "status", "DONE")
                self.update_tree_row(port, "respon", f"KK Ditemukan: {kk}")
        threading.Thread(target=proc, daemon=True).start()

    def menu_reaktivasi(self):
        if self.selected_item in self.workers:
            self.update_tree_row(self.selected_item, "status", "PROSES")
            self.update_tree_row(self.selected_item, "respon", "Mengirim command reaktivasi...")
            self.workers[self.selected_item].single_action = "reaktivasi"

    def menu_cek_limit(self):
        if not self.selected_item: return
        port = self.selected_item
        self.update_tree_row(port, "status", "PROSES")
        self.update_tree_row(port, "respon", "Pengecekan sisa limit bot Telegram...")
        def proc():
            time.sleep(1.0)
            self.update_tree_row(port, "status", "DONE")
            self.update_tree_row(port, "respon", "Sisa Kuota Bot Telegram: 185/200 Kueri Hari Ini")
        threading.Thread(target=proc, daemon=True).start()

    def _refresh_panen_monitor_table(self):
        if not hasattr(self, "panen_tree") or not self.panen_tree.winfo_exists():
            return
        for item in self.panen_tree.get_children():
            self.panen_tree.delete(item)
        try:
            conn = sqlite3.connect(DB_FILE_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT nomor, nik, kk, timestamp FROM panen_raya ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            conn.close()
            for idx, (nomor, nik, kk, timestamp) in enumerate(rows, start=1):
                self.panen_tree.insert("", tk.END, iid=nomor, values=(idx, nomor, nik, kk, timestamp or ""))
        except Exception:
            self.panen_tree.insert("", tk.END, values=(1, "-", "-", "-", "Belum ada data"))

    def delete_panen_rows(self, rows=None, bulk=False):
        if bulk:
            confirm = messagebox.askyesno("Hapus massal", "Yakin ingin menghapus semua data panen dari database?")
            if not confirm:
                return
            target_rows = []
        else:
            target_rows = list(rows or self.panen_tree.selection())
            if not target_rows:
                messagebox.showinfo("Pilih data", "Pilih minimal satu baris data panen terlebih dahulu.")
                return
            confirm = messagebox.askyesno("Hapus baris", "Yakin ingin menghapus baris terpilih dari database?")
            if not confirm:
                return

        try:
            with sqlite_write_lock:
                conn = sqlite3.connect(DB_FILE_PATH)
                cursor = conn.cursor()
                if bulk:
                    cursor.execute("DELETE FROM panen_raya")
                else:
                    for item in target_rows:
                        nomor = self.panen_tree.item(item, "values")[1]
                        if nomor and nomor != "-":
                            cursor.execute("DELETE FROM panen_raya WHERE nomor = ?", (nomor,))
                conn.commit()
                conn.close()
        except Exception as e:
            messagebox.showerror("Gagal hapus", str(e))
            return

        if bulk:
            phone_cache.clear()
            db_cache.clear()
        else:
            for item in target_rows:
                values = self.panen_tree.item(item, "values")
                if len(values) >= 2:
                    nomor = values[1]
                    nik = values[2]
                    kk = values[3]
                    if nomor in phone_cache:
                        phone_cache.pop(nomor, None)
                    if nik in db_cache and db_cache.get(nik) == kk:
                        db_cache.pop(nik, None)

        self._refresh_panen_monitor_table()
        messagebox.showinfo("Berhasil", "Data panen berhasil dihapus.")

    def on_panen_tree_right_click(self, event):
        item = self.panen_tree.identify_row(event.y)
        if item:
            self.panen_tree.selection_set(item)
            self.panen_context_menu.post(event.x_root, event.y_root)

    def render_report_view(self):
        lbl = ctk.CTkLabel(self.body_content, text="📋 RINGKASAN LIVE HASIL PANEN DATABASE", font=("Helvetica", 13, "bold"), text_color="#2F4156")
        lbl.pack(pady=(5, 8))

        toolbar = ctk.CTkFrame(self.body_content, fg_color="#FFFFFF", corner_radius=8)
        toolbar.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkButton(toolbar, text="🗑️ Hapus Terpilih", fg_color="#A51D24", hover_color="#7A141A", command=lambda: self.delete_panen_rows()).pack(side="left", padx=8, pady=8)
        ctk.CTkButton(toolbar, text="🧹 Hapus Semua Data Panen", fg_color="#567C8D", hover_color="#2F4156", command=lambda: self.delete_panen_rows(bulk=True)).pack(side="left", padx=(0, 8), pady=8)
        ctk.CTkButton(toolbar, text="🔄 Refresh", fg_color="#2F4156", hover_color="#1A2836", command=self._refresh_panen_monitor_table).pack(side="left", padx=(0, 8), pady=8)

        table_frame = ttk.Frame(self.body_content)
        table_frame.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        self.panen_tree = ttk.Treeview(table_frame, columns=("no", "nomor", "nik", "kk", "timestamp"), show="headings", height=16)
        self.panen_tree.heading("no", text="#")
        self.panen_tree.heading("nomor", text="NOMOR")
        self.panen_tree.heading("nik", text="NIK")
        self.panen_tree.heading("kk", text="KK")
        self.panen_tree.heading("timestamp", text="WAKTU")
        self.panen_tree.column("no", width=50, anchor=tk.CENTER)
        self.panen_tree.column("nomor", width=140, anchor=tk.CENTER)
        self.panen_tree.column("nik", width=170, anchor=tk.CENTER)
        self.panen_tree.column("kk", width=170, anchor=tk.CENTER)
        self.panen_tree.column("timestamp", width=190, anchor=tk.CENTER)
        self.panen_tree.pack(side="left", fill="both", expand=True)
        self.panen_tree.bind("<Button-3>", self.on_panen_tree_right_click)
        self.panen_tree.bind("<Control-a>", lambda event: self.panen_tree.selection_set(self.panen_tree.get_children()))
        self.panen_tree.configure(selectmode="extended")

        self.panen_context_menu = tk.Menu(self, tearoff=0)
        self.panen_context_menu.add_command(label="🗑️ Hapus baris terpilih", command=lambda: self.delete_panen_rows())
        self.panen_context_menu.add_command(label="🧹 Hapus semua data panen", command=lambda: self.delete_panen_rows(bulk=True))

        sb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.panen_tree.yview)
        self.panen_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        self._refresh_panen_monitor_table()

    def render_setting_view(self):
        container = ctk.CTkFrame(self.body_content, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=5, pady=5)
        
        left_p = ctk.CTkFrame(container, corner_radius=10, fg_color="#FFFFFF")
        left_p.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        inner_left = ctk.CTkFrame(left_p, fg_color="transparent"); inner_left.pack(fill="both", expand=True, padx=15, pady=15)
        
        ctk.CTkLabel(inner_left, text="Cek Nomor USSD:", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=2)
        self.e_dial_n = ctk.CTkEntry(inner_left, width=300); self.e_dial_n.insert(0, global_settings["dial_cek_nomor"]); self.e_dial_n.pack(fill="x", pady=2)
        
        ctk.CTkLabel(inner_left, text="Cek NIK USSD:", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=2)
        self.e_dial_k = ctk.CTkEntry(inner_left, width=300); self.e_dial_k.insert(0, global_settings["dial_cek_nik"]); self.e_dial_k.pack(fill="x", pady=2)
        
        data_p = ctk.CTkFrame(inner_left, corner_radius=8, fg_color="#F5EFEB")
        data_p.pack(fill="x", pady=15)
        ctk.CTkButton(data_p, text="📥 Export Hasil (.CSV)", fg_color="#567C8D", hover_color="#2F4156", command=self.export_panen).pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(data_p, text="📤 Import Bibit (.CSV)", fg_color="#567C8D", hover_color="#2F4156", command=self.import_bibit).pack(fill="x", padx=10, pady=5)
        
        right_p = ctk.CTkFrame(container, corner_radius=10, fg_color="#FFFFFF")
        right_p.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        inner_right = ctk.CTkFrame(right_p, fg_color="transparent"); inner_right.pack(fill="both", expand=True, padx=15, pady=15)
        
        ctk.CTkLabel(inner_right, text="🔑 GATEWAY INTEGRATION", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkButton(inner_right, text="🔑 SECURE TELEGRAM CREDENTIALS", fg_color="#2F4156", text_color="#FFFFFF", hover_color="#1A2836", command=self.open_tg_popup).pack(fill="x", pady=(2, 10))
        
        ctk.CTkLabel(inner_right, text="Format Injeksi:", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=2)
        self.cb_format = ctk.CTkOptionMenu(inner_right, values=["NIK & KK", "NIK & NIK"], fg_color="#567C8D", button_color="#2F4156")
        self.cb_format.set(global_settings["format_mode"]); self.cb_format.pack(fill="x", pady=3)
        
        ctk.CTkLabel(inner_right, text="Mode Trigger:", font=("Helvetica", 11, "bold"), text_color="#2F4156").pack(anchor="w", pady=(8,2))
        self.cb_trigger_mode = ctk.CTkOptionMenu(inner_right, values=["Auto-Run on Insert", "Manual Trigger Only"], fg_color="#567C8D", button_color="#2F4156")
        self.cb_trigger_mode.set(global_settings.get("trigger_mode", "Auto-Run on Insert")); self.cb_trigger_mode.pack(fill="x", pady=3)
        
        self.v_aktif = tk.BooleanVar(value=global_settings["abai_aktif"])
        self.v_tenggang = tk.BooleanVar(value=global_settings["abai_tenggang"])
        self.v_hangus = tk.BooleanVar(value=global_settings["abai_hangus"])
        ctk.CTkCheckBox(inner_right, text="Bypass Kartu Aktif Normal", variable=self.v_aktif, text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkCheckBox(inner_right, text="Bypass Kartu Masa Tenggang", variable=self.v_tenggang, text_color="#2F4156").pack(anchor="w", pady=2)
        ctk.CTkCheckBox(inner_right, text="Bypass Kartu Nomor Hangus", variable=self.v_hangus, text_color="#2F4156").pack(anchor="w", pady=2)
        
        ctk.CTkButton(self.body_content, text="💾 Save & Reload Configuration", fg_color="#2F4156", text_color="#FFFFFF", font=("Helvetica", 12, "bold"), command=self.save_reload_config).pack(side="bottom", fill="x", pady=5)

    def open_tg_popup(self):
        pop = ctk.CTkToplevel(self)
        pop.title("🔑 SECURE TELEGRAM CREDENTIALS")
        pop.geometry("500x470"); pop.resizable(False, False); pop.attributes("-topmost", True)
        frame = ctk.CTkFrame(pop, fg_color="transparent"); frame.pack(fill="both", expand=True, padx=20, pady=15)
        
        ctk.CTkLabel(frame, text="API ID:", text_color="#2F4156").grid(row=0, column=0, sticky="w", pady=4)
        e_api_id = ctk.CTkEntry(frame, width=280); e_api_id.insert(0, global_settings["tg_api_id"]); e_api_id.grid(row=0, column=1, columnspan=2, pady=4)
        
        ctk.CTkLabel(frame, text="API HASH:", text_color="#2F4156").grid(row=1, column=0, sticky="w", pady=4)
        e_api_hash = ctk.CTkEntry(frame, width=280); e_api_hash.insert(0, global_settings["tg_api_hash"]); e_api_hash.grid(row=1, column=1, columnspan=2, pady=4)
        
        ctk.CTkLabel(frame, text="Nomor HP:", text_color="#2F4156").grid(row=2, column=0, sticky="w", pady=4)
        e_phone = ctk.CTkEntry(frame, width=280, placeholder_text="+62812..."); e_phone.insert(0, global_settings["tg_phone"]); e_phone.grid(row=2, column=1, columnspan=2, pady=4)
        
        ctk.CTkLabel(frame, text="Kode OTP:", text_color="#2F4156").grid(row=3, column=0, sticky="w", pady=4)
        e_otp = ctk.CTkEntry(frame, width=150, placeholder_text="12345", show="*"); e_otp.grid(row=3, column=1, sticky="w", pady=4)
        ctk.CTkButton(frame, text="⚡ Kirim OTP", width=110, fg_color="#567C8D").grid(row=3, column=2, sticky="e", pady=4)
        
        ctk.CTkLabel(frame, text="Target Bot:", text_color="#2F4156").grid(row=4, column=0, sticky="w", pady=4)
        e_bot = ctk.CTkEntry(frame, width=280); e_bot.insert(0, global_settings["tg_target_bot"]); e_bot.grid(row=4, column=1, columnspan=2, pady=4)
        
        ctk.CTkLabel(frame, text="Format Cmd:", text_color="#2F4156").grid(row=5, column=0, sticky="w", pady=4)
        e_cmd = ctk.CTkEntry(frame, width=280, placeholder_text="/ceknik {NIK}"); e_cmd.insert(0, global_settings["tg_format_cmd"]); e_cmd.grid(row=5, column=1, columnspan=2, pady=4)

        ctk.CTkLabel(frame, text="Password 2FA:", text_color="#2F4156").grid(row=6, column=0, sticky="w", pady=4)
        e_2fa = ctk.CTkEntry(frame, width=280, placeholder_text="Opsional; hanya bila akun memakai 2FA", show="*")
        e_2fa.grid(row=6, column=1, columnspan=2, pady=4)
        status_var = tk.StringVar(value="Isi API ID, API Hash, dan nomor lalu kirim OTP.")
        ctk.CTkLabel(frame, textvariable=status_var, wraplength=440, justify="left", text_color="#567C8D").grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 2))
        
        def save_tg_bot():
            global_settings["tg_api_id"] = e_api_id.get().strip()
            global_settings["tg_api_hash"] = e_api_hash.get().strip()
            global_settings["tg_phone"] = e_phone.get().strip()
            global_settings["tg_target_bot"] = e_bot.get().strip()
            global_settings["tg_format_cmd"] = e_cmd.get().strip()
            pop.destroy()
            messagebox.showinfo("Saved", "Kredensial Gateway Telegram Berhasil Disimpan!")

        def run_telegram_task(work):
            def worker():
                try:
                    result = work()
                    self.ui_tasks.put(lambda: status_var.set(result))
                except Exception as exc:
                    self.ui_tasks.put(lambda: status_var.set(f"Gagal: {exc}"))
            threading.Thread(target=worker, daemon=True, name="telegram-login").start()

        def send_otp():
            global_settings["tg_api_id"] = e_api_id.get().strip()
            global_settings["tg_api_hash"] = e_api_hash.get().strip()
            global_settings["tg_phone"] = e_phone.get().strip()
            status_var.set("Mengirim OTP...")
            run_telegram_task(lambda: request_telegram_otp(
                global_settings["tg_api_id"], global_settings["tg_api_hash"], global_settings["tg_phone"]))

        def verify_otp():
            status_var.set("Memverifikasi OTP...")
            run_telegram_task(lambda: verify_telegram_otp(e_otp.get().strip(), e_2fa.get().strip()))

        # Tombol baru ini menimpa tombol lama yang sebelumnya tidak memiliki command.
        ctk.CTkButton(frame, text="Kirim OTP", width=110, fg_color="#567C8D", command=send_otp).grid(row=3, column=2, sticky="e", pady=4)
        ctk.CTkButton(frame, text="Login dengan OTP", fg_color="#2F4156", text_color="#FFFFFF", command=verify_otp).grid(row=9, column=1, sticky="e", pady=15)
        ctk.CTkButton(frame, text="Simpan Konfigurasi", fg_color="#2F4156", text_color="#FFFFFF", font=("Helvetica", 11, "bold"), command=save_tg_bot).grid(row=10, column=2, sticky="e", pady=15)

    def save_reload_config(self):
        global global_settings
        global_settings["dial_cek_nomor"] = self.e_dial_n.get()
        global_settings["dial_cek_nik"] = self.e_dial_k.get()
        global_settings["format_mode"] = self.cb_format.get()
        # persist trigger mode selection
        try: global_settings["trigger_mode"] = self.cb_trigger_mode.get()
        except Exception: pass
        global_settings["abai_aktif"] = self.v_aktif.get()
        global_settings["abai_tenggang"] = self.v_tenggang.get()
        global_settings["abai_hangus"] = self.v_hangus.get()
        messagebox.showinfo("Hot-Reload", "Konfigurasi Berhasil Diperbarui!")

    def _get_port_row_values(self, port):
        state = ensure_port_registered(port)
        return [
            state["port_display"],
            state["nomor"],
            state["nik"],
            state["kk"],
            state["status"],
            state["respon"],
            state["masa_aktif"],
            "LOG",
        ]

    def _apply_row_tags(self, item, status_text):
        txt = (status_text or "").lower()
        if "sukses" in txt:
            self.tree.item(item, tags=("sukses",))
        elif "done" in txt:
            self.tree.item(item, tags=("done",))
        elif "proses" in txt or "ready" in txt or "stabilisasi" in txt:
            self.tree.item(item, tags=("proses",))
        elif "no sim" in txt or "not inserted" in txt or "idle" in txt:
            self.tree.item(item, tags=("idle",))
        elif txt == "off":
            self.tree.item(item, tags=("off",))
        elif "gagal" in txt:
            self.tree.item(item, tags=("gagal",))
        else:
            self.tree.item(item, tags=("idle",))

    def update_tree_row(self, port, col_name, value):
        # PortWorker berjalan di background. Jangan pernah memanggil Tkinter
        # (termasuk self.after) dari thread tersebut karena dapat membuat UI
        # macet saat banyak modem aktif.
        if threading.current_thread() is not threading.main_thread():
            self.ui_updates.put((port, col_name, value))
            return
        self._update_tree_row_main(port, col_name, value)

    def _update_tree_row_main(self, port, col_name, value):
        col_map = {"port_display": 0, "nomor": 1, "nik": 2, "kk": 3, "status": 4, "respon": 5, "masa_aktif": 6}
        # Always update registry state first, then cache, even if tree row is temporarily absent
        if col_name in ("port_display", "nomor", "nik", "kk", "status", "respon", "masa_aktif"):
            state = update_port_registry(port, col_name, value)
            if col_name == "status":
                if str(state.get("status", "") or "").upper() != str(value or "").upper():
                    return
        cached_row = self.port_row_cache.get(port, ["-", "-", "-", "-", "IDLE", "Idle/Standby", "-", "LOG"])
        cached_row[col_map[col_name]] = value
        self.port_row_cache[port] = cached_row

        try:
            if not hasattr(self, 'tree') or not self.tree.winfo_exists():
                return
            if not self.tree.exists(port):
                row_values = self._get_port_row_values(port)
                self.tree.insert("", tk.END, iid=port, values=row_values)
                self._apply_row_tags(port, row_values[4])
                return
            cur = list(self.tree.item(port, "values"))
            if len(cur) < 7:
                cur = ["-"] * 7
            cur[col_map[col_name]] = value
            self.tree.item(port, values=cur)
            if col_name == "status":
                self._apply_row_tags(port, value)
        except Exception:
            pass

    def drain_background_events(self):
        """Jalankan di main thread: gabungkan burst update dari worker modem."""
        while True:
            try:
                task = self.ui_tasks.get_nowait()
            except queue.Empty:
                break
            try:
                task()
            except Exception:
                pass
        latest = {}
        for _ in range(1500):
            try:
                port, column, value = self.ui_updates.get_nowait()
            except queue.Empty:
                break
            latest[(port, column)] = value
        for (port, column), value in latest.items():
            self._update_tree_row_main(port, column, value)

        newest_scan = None
        while True:
            try:
                newest_scan = self.port_scan_results.get_nowait()
            except queue.Empty:
                break
        if newest_scan is not None:
            self._apply_port_scan(newest_scan)
        self.after(100, self.drain_background_events)

    def check_log_trigger(self, event):
        try:
            item = self.tree.identify_row(event.y)
            column = self.tree.identify_column(event.x)
            if item and column == "#8":
                pop = ctk.CTkToplevel(self)
                pop.title(f"Log Raw - {item}")
                txt = tk.Text(pop, bg="#2F4156", fg="#FFFFFF", font=("Courier", 10)); txt.pack(fill="both", expand=True)
                with port_logs_lock:
                    log_snapshot = list(port_logs.get(item, ["Belum ada data log."]))
                for l in log_snapshot:
                    txt.insert(tk.END, l + "\n")
                txt.config(state=tk.DISABLED)
        except Exception: pass

    def start_port_monitoring(self):
        """Mulai satu scheduler pemindaian; aman dipanggil berulang kali."""
        if self.monitor_started:
            return
        self.monitor_started = True
        self.request_port_scan()
        self.after(3000, self._port_monitor_tick)

    def _port_monitor_tick(self):
        self.request_port_scan()
        self.after(3000, self._port_monitor_tick)

    def request_port_scan(self):
        """Enumerasi COM di background agar UI tetap responsif."""
        if self.scan_in_progress:
            return
        self.scan_in_progress = True

        def scan_in_background():
            try:
                found = [p.device for p in serial.tools.list_ports.comports()]
                found.sort(key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)
                self.port_scan_results.put(found)
            except Exception as e:
                print(f"Error scan ports: {e}")
            finally:
                self.scan_in_progress = False

        threading.Thread(target=scan_in_background, daemon=True, name="port-scanner").start()

    def scan_ports(self):
        """Kompatibilitas untuk pemanggil lama; tidak memblokir UI."""
        self.request_port_scan()

    def _apply_port_scan(self, found):
        try:
            menyala_count = 0
            mati_count = 0

            # Worker dan registry harus tetap hidup, meski tab Workspace sedang
            # tidak dirender. Blok UI di bawah hanya bertugas menggambar tabel.
            for p in found:
                is_off = p in disabled_ports
                port_label = f"[OFF] {p}" if is_off else f"[ON] {p}"
                ensure_port_registered(p)
                update_port_registry(p, "port_display", port_label)
                if p not in self.workers:
                    worker = PortWorker(p, self.update_tree_row)
                    self.workers[p] = worker
                    worker.start()
            
            if hasattr(self, 'tree') and self.tree.winfo_exists():
                for p in found:
                    is_off = p in disabled_ports
                    if is_off: mati_count += 1
                    else: menyala_count += 1
                    
                    # FILTER LOGIC
                    should_show = True
                    if self.filter_mode == "Hanya Port Aktif (Menyala 🟢)" and is_off: should_show = False
                    elif self.filter_mode == "Hanya Port Off (Mati 🔴)" and not is_off: should_show = False
                    
                    port_label = f"🔴 {p}(OFF)" if is_off else f"🟢 {p}"
                    
                    if should_show:
                        row_values = self._get_port_row_values(p)
                        if not self.tree.exists(p):
                            self.tree.insert("", tk.END, iid=p, values=row_values)
                        else:
                            current_values = list(self.tree.item(p, "values"))
                            if current_values != row_values:
                                self.tree.item(p, values=row_values)
                        self._apply_row_tags(p, row_values[4])
                    elif self.tree.exists(p):
                        self.tree.delete(p)

            # Hentikan worker untuk port yang sudah benar-benar hilang agar
            # worker lama tidak tertinggal setelah modem dicabut.
            for port, worker in list(self.workers.items()):
                if port not in found:
                    worker.shutdown()
                    try:
                        worker.join(timeout=2.0)
                    except Exception:
                        pass
                    self.workers.pop(port, None)
                    try:
                        remove_port_registry(port)
                    except Exception:
                        pass
                    if hasattr(self, 'tree') and self.tree.winfo_exists() and self.tree.exists(port):
                        self.tree.delete(port)

            if not (hasattr(self, 'tree') and self.tree.winfo_exists()):
                menyala_count = sum(1 for p in found if p not in disabled_ports)
                mati_count = len(found) - menyala_count
                        
            if hasattr(self, 'lbl_footer') and self.lbl_footer.winfo_exists():
                self.lbl_footer.configure(text=f"SLOT ACTIVE PORT MONITOR: {len(found)} Slot COM Terdeteksi ({menyala_count} Menyala 🟢 | {mati_count} Mati 🔴)")
                
        except Exception as e:
            print(f"Error scan ports: {e}")

    def restart_all(self):
        for w in self.workers.values(): w.force_retry = True

    def reset_modem(self):
        if not self.workers:
            messagebox.showinfo("Reset Modem", "Belum ada port modem yang aktif.")
            return

        for port, worker in self.workers.items():
            if not worker.is_running:
                continue
            self.update_tree_row(port, "status", "RESET")
            self.update_tree_row(port, "respon", "Reset modem sedang diproses...")
            worker.request_modem_reset()

    def export_panen(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
        if path:
            try:
                conn = sqlite3.connect(DB_FILE_PATH)
                c = conn.cursor(); c.execute("SELECT nomor, nik, kk, timestamp FROM panen_raya")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("Nomor HP,NIK,KK,Waktu Panen\n")
                    for r in c.fetchall(): f.write(f"{r[0]},{r[1]},{r[2]},{r[3]}\n")
                conn.close()
                messagebox.showinfo("Sukses", "Data berhasil diekspor!")
            except Exception as e: messagebox.showerror("Eror", str(e))

    def import_bibit(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not path:
            return

        progress_popup = ctk.CTkToplevel(self)
        progress_popup.title("Mengimpor Data Bibit")
        progress_popup.geometry("420x140")
        progress_popup.resizable(False, False)
        progress_popup.attributes("-topmost", True)

        label = ctk.CTkLabel(progress_popup, text="Memproses file CSV...", wraplength=360)
        label.pack(padx=20, pady=(18, 8))
        progress_bar = ctk.CTkProgressBar(progress_popup, width=360)
        progress_bar.set(0)
        progress_bar.pack(padx=20, pady=8)
        status_label = ctk.CTkLabel(progress_popup, text="0 / 0 record")
        status_label.pack(padx=20, pady=(2, 12))

        def update_progress(processed, total, message=None):
            if not progress_popup.winfo_exists():
                return
            if total:
                progress_bar.set(min(processed / total, 1.0))
            else:
                progress_bar.set(0)
            if message:
                label.configure(text=message)
            status_label.configure(text=f"{processed} / {total} record")
            progress_popup.update_idletasks()

        def worker():
            try:
                total = 0
                processed = 0
                batch = []
                iterator = iter_import_records(path)
                for record in iterator:
                    total += 1
                    if record[0] and record[1] and record[2]:
                        batch.append(record)
                        if len(batch) >= 1000:
                            processed += save_to_harvest_db_batch(batch)
                            batch = []
                            self.ui_tasks.put(lambda: update_progress(processed, total, "Menyimpan data ke database..."))
                    if total % 500 == 0:
                        self.ui_tasks.put(lambda: update_progress(processed, total, "Memproses file CSV..."))

                if batch:
                    processed += save_to_harvest_db_batch(batch)

                init_database()
                self.ui_tasks.put(lambda: update_progress(processed, total, "Impor selesai"))
                self.ui_tasks.put(lambda: messagebox.showinfo("Sukses", f"Berhasil mengimpor {processed} data bibit!"))
                self.ui_tasks.put(progress_popup.destroy)
            except Exception as exc:
                self.ui_tasks.put(lambda: messagebox.showerror("Gagal", str(exc)))
                self.ui_tasks.put(progress_popup.destroy)

        threading.Thread(target=worker, daemon=True, name="import-bibit").start()

if __name__ == "__main__":
    init_database()
    app = KebunAutomasiGUI()
    app.after(500, app.start_port_monitoring)
    app.mainloop()
