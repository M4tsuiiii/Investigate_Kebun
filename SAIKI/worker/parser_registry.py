"""ParserRegistry — Central store for all response parsers.

Parsers are pure functions: raw_response -> parsed_data dict.
Skills look up parsers by name from this registry.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable, Dict, Optional

from app.domain.classifier import parse_cpin_response as _domain_parse_cpin
from app.domain.enums import CardStatus


# === Parser Functions ===


def parse_cnum(raw: str) -> Dict[str, Any]:
    """Parse MSISDN from +CNUM response.

    Format: +CNUM: "","number",type
    """
    if not raw:
        return {"number": None}
    match = re.search(r'\+CNUM:\s*"",\s*"(\d+)"', raw)
    return {"number": match.group(1).strip() if match else None}


def extract_number_from_ussd(raw: str) -> Dict[str, Any]:
    """Extract phone number from USSD response text."""
    if not raw:
        return {"number": None}
    match = re.search(r"(0\d{9,12})", raw)
    if match:
        return {"number": match.group(1)}
    match = re.search(r"(\+62\d{9,12})", raw)
    return {"number": match.group(1) if match else None}


def extract_grace_date(raw: str) -> Dict[str, Any]:
    """Extract grace date from *185# response.

    Pattern: 'Active 24-08-2026'
    """
    if not raw:
        return {"grace_date": None}
    match = re.search(r"Active\s+(\d{2}-\d{2}-\d{4})", raw)
    return {"grace_date": match.group(1) if match else None}


def classify_card_status_from_grace(raw: str) -> Dict[str, Any]:
    """Classify card status by calculating masa aktif from grace_date.

    Rules (from PENUNJANG.md):
    - grace_date - today > 0 -> AKTIF
    - -30 <= grace_date - today <= 0 -> TENGGANG
    - grace_date - today < -30 -> HANGUS
    """
    grace_result = extract_grace_date(raw)
    grace_str = grace_result.get("grace_date")
    if not grace_str:
        return {"card_status": CardStatus.UNKNOWN.value}

    try:
        grace_date = datetime.strptime(grace_str, "%d-%m-%Y").date()
        today = date.today()
        delta = (grace_date - today).days

        if delta > 0:
            status = CardStatus.AKTIF
        elif -30 <= delta <= 0:
            status = CardStatus.TENGGANG
        else:
            status = CardStatus.HANGUS

        return {"card_status": status.value, "masa_aktif_days": delta}
    except (ValueError, TypeError):
        return {"card_status": CardStatus.UNKNOWN.value}


def extract_nik(raw: str) -> Dict[str, Any]:
    """Extract NIK from *888*4444*1# response.

    Pattern: 'NIK : 31750554xxxxxxxx'
    """
    if not raw:
        return {"nik": None}
    match = re.search(r"NIK\s*:\s*(\d{16})", raw)
    return {"nik": match.group(1) if match else None}


def extract_kk(raw: str) -> Dict[str, Any]:
    """Extract KK from response (if available)."""
    if not raw:
        return {"kk": None, "source": "none"}
    match = re.search(r"KK\s*:\s*(\d{16})", raw)
    return {"kk": match.group(1) if match else None, "source": "ussd"}


def classify_injection_response(raw: str) -> Dict[str, Any]:
    """Classify injection response from *888*89*1*{NIK}*{KK}#.

    Rules:
    - HANGUS -> 'Permintaan kamu sedang di proses' -> provisional
    - TENGGANG -> 'Nomor xxx sedang dalam masa tenggang' -> direct success
    - AKTIF -> 'Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus' -> failed
    """
    if not raw:
        return {"injected": False, "provisional": False, "card_status": "unknown"}

    raw_lower = raw.lower()

    if "sedang di proses" in raw_lower or "diproses" in raw_lower:
        return {"injected": True, "provisional": True, "card_status": "HANGUS"}

    if "masa tenggang" in raw_lower:
        return {"injected": True, "provisional": False, "card_status": "TENGGANG"}

    if "kartu hangus" in raw_lower or "kartu hanggus" in raw_lower:
        return {"injected": False, "provisional": False, "card_status": "AKTIF"}

    if "berhasil" in raw_lower or "success" in raw_lower:
        return {"injected": True, "provisional": False, "card_status": "unknown"}

    return {"injected": False, "provisional": False, "card_status": "unknown"}


def verify_grace_response(raw: str) -> Dict[str, Any]:
    """Full verification: extract grace_date + classify card_status."""
    grace_result = extract_grace_date(raw)
    status_result = classify_card_status_from_grace(raw)
    return {**grace_result, **status_result}


def check_modem(raw: str = "") -> Dict[str, Any]:
    """Check modem online status (used after ATZ restart)."""
    return {"modem_online": True}


def parse_cpin_response_wrapper(raw: str) -> Dict[str, Any]:
    """Wrap domain parse_cpin_response for registry consistency."""
    return {"cpin_state": _domain_parse_cpin(raw).value}


class ParserRegistry:
    """Central registry for all response parsers.

    Parsers are pure functions: raw_response -> parsed_data dict.
    """

    def __init__(self) -> None:
        self._parsers: Dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register all built-in parsers."""
        defaults = {
            "parse_cnum": parse_cnum,
            "extract_number_from_ussd": extract_number_from_ussd,
            "extract_grace_date": extract_grace_date,
            "classify_card_status_from_grace": classify_card_status_from_grace,
            "extract_nik": extract_nik,
            "extract_kk": extract_kk,
            "classify_injection_response": classify_injection_response,
            "verify_grace_response": verify_grace_response,
            "check_modem": check_modem,
            "parse_cpin_response": parse_cpin_response_wrapper,
        }
        for name, func in defaults.items():
            self._parsers[name] = func

    def get(self, name: str) -> Optional[Callable]:
        """Get parser function by name."""
        return self._parsers.get(name)

    def register(self, name: str, func: Callable) -> None:
        """Register a new parser function."""
        self._parsers[name] = func

    def parse(self, name: str, raw: str) -> Dict[str, Any]:
        """Execute a parser by name."""
        parser = self.get(name)
        if not parser:
            return {"error": f"Unknown parser: {name}"}
        try:
            return parser(raw)
        except Exception as e:
            return {"error": f"Parser error: {e}"}

    def list_all(self) -> list:
        """List all registered parser names."""
        return list(self._parsers.keys())
