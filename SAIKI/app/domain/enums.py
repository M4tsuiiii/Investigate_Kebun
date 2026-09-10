"""Domain enums — single source of truth for ALL business state enumerations.

All enums use str, Enum inheritance for JSON serialization compatibility.
"""

from enum import Enum


class BusinessOutcome(str, Enum):
    """Final business outcome — single source of truth.

    Fixes I-01: canonical name 'BusinessOutcome' with correct values.
    """
    SUKSES = "SUKSES"
    TENGGANG = "TENGGANG"
    FAILED = "FAILED"


class CpinState(str, Enum):
    """SIM CPIN states from AT+CPIN? response."""
    READY = "READY"
    NOT_INSERTED = "NOT_INSERTED"
    PIN_REQUIRED = "PIN_REQUIRED"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


class CardStatus(str, Enum):
    """Derived card status from grace date + response evidence."""
    AKTIF = "AKTIF"
    TENGGANG = "TENGGANG"
    HANGUS = "HANGUS"
    UNKNOWN = "UNKNOWN"


class FailureCode(str, Enum):
    """Failure classification codes."""
    GAGAL_CEK_NIK = "GAGAL_CEK_NIK"
    GAGAL_KK = "GAGAL_KK"
    GAGAL_INJEKSI = "GAGAL_INJEKSI"
    GAGAL_VERIFIKASI = "GAGAL_VERIFIKASI"
    GAGAL = "GAGAL"


class UssdClass(str, Enum):
    """USSD raw response classification."""
    PAYLOAD = "USSD_PAYLOAD"
    EMPTY_PAYLOAD = "USSD_EMPTY_PAYLOAD"
    STATUS_ONLY = "USSD_STATUS_ONLY"
    PARTIAL = "PARTIAL_RESPONSE"
    PROMPT = "PROMPT_CONFIRMATION"
    ERROR = "ERROR"
    AT_OK = "AT_OK"
    COMMAND_ECHO = "COMMAND_ECHO"
    MODEM_NOTIFICATION = "MODEM_NOTIFICATION"
    WAITING = "WAITING_RESPONSE"
    TIMEOUT = "TIMEOUT"


class UssdIntent(str, Enum):
    """Semantic intent of a USSD payload."""
    SUCCESS = "SUCCESS_MESSAGE"
    REQUEST_ACCEPTED = "REQUEST_ACCEPTED"
    MENU = "MENU_RESPONSE"
    NUMBER_INFO = "NUMBER_INFO"
    EMPTY = "EMPTY_RESPONSE"
    UNKNOWN = "UNKNOWN"


class FlowStatus(str, Enum):
    """Reactivation flow progress states."""
    STABILISASI = "STABILISASI"
    CEK_NOMOR = "CEK_NOMOR"
    CEK_STATUS = "CEK_STATUS"
    CEK_NIK = "CEK_NIK"
    CEK_KK = "CEK_KK"
    INJECTING = "INJECTING"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    GAGAL = "GAGAL"


class PortStatus(str, Enum):
    """Port UI status tags."""
    IDLE = "IDLE"
    READY = "READY"
    BUSY = "BUSY"
    OFF = "OFF"
    RESET = "RESET"
    CHECKING = "CHECKING"
    GAGAL = "GAGAL"
    PIN_LOCK = "PIN_LOCK"
    SUKSES = "SUKSES"
    DONE = "DONE"


class KkSource(str, Enum):
    """KK resolution source."""
    NIK_MODE = "NIK_MODE"
    LOCAL_DB = "LOCAL_DB"
    TELEGRAM = "TELEGRAM"
    NONE = "NONE"


class PortState(str, Enum):
    """Port participation lifecycle states (Sprint 11A).

    Controls whether a port participates in automation workflows.
    EXCLUDED ports remain connected and monitored but are ignored
    by auto-run, mass actions, and workflow scheduling.
    """
    DISCOVERED = "DISCOVERED"
    VALID_MODEM = "VALID_MODEM"
    ACTIVE = "ACTIVE"
    EXCLUDED = "EXCLUDED"
    OFFLINE = "OFFLINE"
    REMOVED = "REMOVED"


class ValidationResult(str, Enum):
    """Modem validation result (Sprint 11A)."""
    VALID_MODEM = "VALID_MODEM"
    INVALID_DEVICE = "INVALID_DEVICE"
    UNRESPONSIVE = "UNRESPONSIVE"
