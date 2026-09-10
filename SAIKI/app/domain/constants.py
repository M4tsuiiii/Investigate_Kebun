"""Domain constants — single source of truth for ALL magic numbers and timing values.

Source: GOOD/app/kebun_reaktivasi(rev).py lines 35-53
Hidden Rules: HR-011 (magic wait values), M-11 (13+ magic wait values)
"""

# === USSD Timing (BR-018, BR-019) ===
USSD_SESSION_FENCE_MIN_SECONDS: float = 0.75
USSD_SESSION_FENCE_QUIET_SECONDS: float = 0.25
USSD_SESSION_FENCE_TIMEOUT_SECONDS: float = 3.0
DIAL_COOLDOWN_SECONDS: float = 4.0

# === Verification Timing (BR-019b / HUNTER-7) ===
VERIFICATION_DELAY_SECONDS: float = 15.0
VERIFICATION_READ_TIMEOUT: float = 30.0

# === CPIN Thresholds (HR-018, HR-019) ===
CPIN_UNKNOWN_THRESHOLD: int = 3
CPIN_CHECKING_THRESHOLD: int = 2
CPIN_MAX_REMOVAL_CONFIRM: int = 2
CPIN_POLL_INTERVAL: float = 1.0
CPIN_POLL_TIMEOUT: float = 3.0

# === Prompt Recovery (BR-026) ===
PROMPT_RECOVERY_MAX: int = 2

# === USSD Grace Read (BR-017) ===
USSD_GRACE_READ_INITIAL_WAIT: float = 0.5
USSD_GRACE_READ_WINDOW: float = 3.0
USSD_PAYLOAD_QUIET_SECONDS: float = 0.8

# === Stabilization ===
STABILIZATION_SECONDS: float = 15.0

# === Serial Defaults ===
DEFAULT_BAUD_RATES: list = [115200, 9600, 57600, 38400, 19200, 4800]
DEFAULT_SCAN_TIMEOUT: float = 1.0
DEFAULT_AT_TIMEOUT: float = 2.0
DEFAULT_READ_TIMEOUT: float = 20.0

# === Modem Validation Baud Detection (Sprint 13) ===
MODEM_BAUD_RATES: list = [9600, 19200, 115200]  # GOOD-compatible: slowest first
MODEM_BAUD_TIMEOUT: float = 1.0  # per-baud-rate probe timeout

# === Concurrency ===
MAX_CONCURRENT_INJECTIONS: int = 2

# === Sprint 15Q: Modem Discovery ===
DISCOVERY_BAUD_RATE: int = 115200  # Default probe baud (Quectel M26)
DISCOVERY_PROBE_TIMEOUT: float = 2.0  # Seconds to wait for AT response
DISCOVERY_MAX_CONCURRENT: int = 4  # Max parallel probes
DISCOVERY_CANDIDATE_KEYWORDS: list = [
    "Quectel",
    "XR21V1414",
    "USB UART",
    "USB Serial",
    "AT Port",
]

# === Sprint 15R: Scan Stability ===
DISCOVERY_RETRY_COOLDOWN: float = 30.0  # Seconds before retrying a failed port
DISCOVERY_CANDIDATE_KEYWORDS_HIGH_PRIORITY: list = [
    "XR21V1414",
    "Quectel",
    "AT Port",
]
DISCOVERY_KNOWN_HWIDS: list = [
    "VID_04E2&PID_1414",  # Exar XR21V1414
    "VID:PID=04E2:1414",
]
DISCOVERY_KNOWN_VIDS: list = [
    "04E2",  # Exar
    "2C7C",  # Quectel
]
