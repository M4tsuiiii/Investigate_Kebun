"""UssdIntent — Classify semantic intent of USSD responses.

Adopted from GOOD: classify_ussd_intent (lines 738-761)
6 intents: CEK_NOMOR, CEK_STATUS, CEK_NIK, CEK_KK, VERIFY_GRACE, REAKTIVASI

Used for automatic workflow routing and response interpretation.
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("saiki.intelligence.ussd_intent")


class UssdIntent(Enum):
    """USSD response intent classification."""
    CEK_NOMOR = "cek_nomor"
    CEK_STATUS = "cek_status"
    CEK_NIK = "cek_nik"
    CEK_KK = "cek_kk"
    VERIFY_GRACE = "verify_grace"
    REAKTIVASI = "reaktivasi"
    NUMBER_INFO = "number_info"
    SUCCESS = "success"
    REQUEST_ACCEPTED = "request_accepted"
    MENU = "menu"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: UssdIntent
    confidence: float  # 0.0 - 1.0
    extracted_data: str = ""
    details: str = ""


# Indonesian mobile number pattern
_MOBILE_PATTERN = re.compile(r"08\d{9,11}")

# Success keywords (from GOOD)
_SUCCESS_KEYWORDS = (
    "berhasil", "aktif", "success", "activated", "active",
    "terverifikasi", "verified", "sukses", "done", "selesai",
    "nomor anda", "your number", "status aktif", "masih aktif",
)

# Processing keywords (from GOOD)
_PROCESSING_KEYWORDS = (
    "sedang diproses", "processing", "please wait", "harap tunggu",
    "request received", "permintaan diterima", "diproses",
    "sedang di proses", "dalam proses", "queued", "diproses",
)

# Menu keywords (from GOOD)
_MENU_KEYWORDS = (
    "try again", "coba lagi", "menu", "pilih", "welcome",
    "selamat datang", "thank you", "terima kasih", "press",
    "reply", "respond", "balance", "credit", "pulsa",
    "enter", "masukkan", "good evening", "good morning",
    "account", "content", "impoint", "your number",
    "silakan pilih", "silahkan pilih",
)

# Card status patterns
_CARD_STATUS_PATTERN = re.compile(
    r"\b(aktif|tenggang|hangus|expired|suspended|blocked)\b", re.IGNORECASE
)

# NIK pattern (16 digits)
_NIK_PATTERN = re.compile(r"\b\d{16}\b")

# Grace date pattern
_GRACE_DATE_PATTERN = re.compile(
    r"(\d{2}[-/]\d{2}[-/]\d{4}|\d{4}[-/]\d{2}[-/]\d{2})", re.IGNORECASE
)


def classify_ussd_intent(text: Optional[str]) -> IntentResult:
    """Classify the semantic intent of a USSD response string.

    Priority order (from GOOD):
    1. Empty → EMPTY
    2. Contains 08xxxxxxxxx → NUMBER_INFO
    3. Success keywords → SUCCESS
    4. Processing keywords → REQUEST_ACCEPTED
    5. Menu keywords → MENU
    6. Else → UNKNOWN

    Args:
        text: Raw USSD response text

    Returns:
        IntentResult with intent, confidence, and extracted data
    """
    if not text or not text.strip():
        return IntentResult(
            intent=UssdIntent.EMPTY,
            confidence=1.0,
            details="Empty payload",
        )

    text = text.strip()
    low = text.lower()

    # Priority 1: Contains mobile number
    number_match = _MOBILE_PATTERN.search(low)
    if number_match:
        return IntentResult(
            intent=UssdIntent.NUMBER_INFO,
            confidence=0.95,
            extracted_data=number_match.group(0),
            details=f"Number found: {number_match.group(0)}",
        )

    # Priority 2: Success keywords
    for kw in _SUCCESS_KEYWORDS:
        if kw in low:
            return IntentResult(
                intent=UssdIntent.SUCCESS,
                confidence=0.85,
                details=f"Success keyword: {kw}",
            )

    # Priority 3: Processing keywords
    for kw in _PROCESSING_KEYWORDS:
        if kw in low:
            return IntentResult(
                intent=UssdIntent.REQUEST_ACCEPTED,
                confidence=0.80,
                details=f"Processing keyword: {kw}",
            )

    # Priority 4: Menu keywords
    for kw in _MENU_KEYWORDS:
        if kw in low:
            return IntentResult(
                intent=UssdIntent.MENU,
                confidence=0.70,
                details=f"Menu keyword: {kw}",
            )

    # Priority 5: Menu pattern (numbered list)
    if re.search(r"(^|\n)\s*\d+\.", text):
        return IntentResult(
            intent=UssdIntent.MENU,
            confidence=0.75,
            details="Numbered menu list detected",
        )

    return IntentResult(
        intent=UssdIntent.UNKNOWN,
        confidence=0.30,
        details="No match",
    )


def classify_card_status_intent(text: Optional[str]) -> Optional[str]:
    """Extract card status from USSD response.

    Returns card status string (AKTIF, TENGGANG, HANGUS) or None.
    """
    if not text:
        return None
    match = _CARD_STATUS_PATTERN.search(text)
    return match.group(1).upper() if match else None


def extract_nik_from_response(text: Optional[str]) -> Optional[str]:
    """Extract 16-digit NIK from USSD response."""
    if not text:
        return None
    match = _NIK_PATTERN.search(text)
    return match.group(0) if match else None


def extract_grace_date_from_response(text: Optional[str]) -> Optional[str]:
    """Extract grace date from USSD response."""
    if not text:
        return None
    match = _GRACE_DATE_PATTERN.search(text)
    return match.group(1) if match else None
