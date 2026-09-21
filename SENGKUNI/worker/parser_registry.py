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

# GOOD parity: extract payload from +CUSD wrapper before searching for data
_PAYLOAD_PATTERN = re.compile(r'\+CUSD:\s*\d+,"(.*)"', re.DOTALL)


def _extract_payload_text(raw: str) -> str:
    """Extract human-readable text from +CUSD wrapper.

    +CUSD: 0,"Good Morning , Your number 085...,Balance Rp.0 Active 24-08-2026",15
    → "Good Morning , Your number 085...,Balance Rp.0 Active 24-08-2026"

    If no +CUSD wrapper found, returns raw as-is (already payload text).
    """
    if not raw:
        return ""
    m = _PAYLOAD_PATTERN.search(raw)
    if m:
        return m.group(1)
    return raw


def parse_cnum(raw: str) -> Dict[str, Any]:
    """Parse MSISDN from +CNUM response.

    Format: +CNUM: "","number",type
    """
    if not raw:
        return {"number": None}
    match = re.search(r'\+CNUM:\s*"",\s*"(\d+)"', raw)
    return {"number": match.group(1).strip() if match else None}


def extract_number_from_ussd(raw: str) -> Dict[str, Any]:
    """Extract phone number from USSD response text.

    First extracts payload from +CUSD wrapper, then searches for number.
    This prevents matching digits in the +CUSD status code or stale buffer data.
    """
    if not raw:
        return {"number": None}

    payload = _extract_payload_text(raw)
    match = re.search(r"(0\d{9,12})", payload)
    if match:
        return {"number": match.group(1)}
    match = re.search(r"(\+62\d{9,12})", payload)
    return {"number": match.group(1) if match else None}


def extract_grace_date(raw: str) -> Dict[str, Any]:
    """Extract grace date from *185# response.

    Pattern: 'Active 24-08-2026' or dates in DD-MM-YYYY / YYYY-MM-DD
    First extracts payload from +CUSD wrapper.
    """
    if not raw:
        return {"grace_date": None}
    payload = _extract_payload_text(raw)
    match_act = re.search(r"Active\s+(\d{2}[-/]\d{2}[-/]\d{4})", payload, re.IGNORECASE)
    if match_act:
        return {"grace_date": match_act.group(1).replace("/", "-")}
    m_iso = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", payload)
    if m_iso:
        parts = m_iso.group(1).replace("/", "-").split("-")
        return {"grace_date": f"{parts[2]}-{parts[1]}-{parts[0]}"}
    m_loc = re.search(r"(\d{2}[-/]\d{2}[-/]\d{4})", payload)
    if m_loc:
        return {"grace_date": m_loc.group(1).replace("/", "-")}
    return {"grace_date": None}


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

    Pattern: 'NIK : 31750554xxxxxxxx' or any 16-digit ID number.
    First extracts payload from +CUSD wrapper.
    """
    if not raw:
        return {"nik": None}
    payload = _extract_payload_text(raw)
    match = re.search(r"NIK\s*:\s*(\d{16})", payload)
    if match:
        return {"nik": match.group(1)}
    match_alt = re.search(r"NIK\s*[:\s]\s*(\d{16})", payload, re.IGNORECASE)
    if match_alt:
        return {"nik": match_alt.group(1)}
    match_16 = re.search(r"\b(\d{16})\b", payload)
    if match_16:
        return {"nik": match_16.group(1)}
    return {"nik": None}


def extract_kk(raw: str) -> Dict[str, Any]:
    """Extract KK from response (if available).
    First extracts payload from +CUSD wrapper.
    """
    if not raw:
        return {"kk": None, "source": "none"}
    payload = _extract_payload_text(raw)
    match = re.search(r"KK\s*:\s*(\d{16})", payload)
    return {"kk": match.group(1) if match else None, "source": "ussd"}


def classify_injection_response(raw: str) -> Dict[str, Any]:
    """Classify injection response from *888*89*1*{NIK}*{KK}#.

    Rules:
    - HANGUS -> 'Permintaan kamu sedang di proses' -> provisional
    - TENGGANG -> 'Nomor xxx sedang dalam masa tenggang' -> direct success
    - AKTIF -> 'Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus' -> failed
    First extracts payload from +CUSD wrapper.
    """
    if not raw:
        return {"injected": False, "provisional": False, "card_status": "unknown"}

    payload = _extract_payload_text(raw).lower()

    if "sedang di proses" in payload or "diproses" in payload:
        return {"injected": True, "provisional": True, "card_status": "HANGUS"}

    if "masa tenggang" in payload:
        return {"injected": True, "provisional": False, "card_status": "TENGGANG"}

    if "kartu hangus" in payload or "kartu hanggus" in payload:
        return {"injected": False, "provisional": False, "card_status": "AKTIF"}

    if "berhasil" in payload or "success" in payload:
        return {"injected": True, "provisional": False, "card_status": "unknown"}

    return {"injected": False, "provisional": False, "card_status": "unknown"}


def parse_185_response(raw: str) -> Dict[str, Any]:
    """Parse combined number + grace_date + card_status from *185# response.

    Response format:
    "Good Morning , Your number 0858612345678, Balance Rp.0 Active 24-08-2026 ..."
    """
    number_result = extract_number_from_ussd(raw)
    grace_result = extract_grace_date(raw)
    status_result = classify_card_status_from_grace(raw)
    return {**number_result, **grace_result, **status_result}


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
            "parse_185_response": parse_185_response,
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
