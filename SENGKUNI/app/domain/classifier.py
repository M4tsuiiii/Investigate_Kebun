"""Classifier — Shared parsing functions for modem responses.

Anti-false-positive CPIN parser:
- Checks NOT_READY BEFORE READY (prevents substring collision)
- Requires +CPIN: prefix for all state matches
- All +CME ERROR → NOT_INSERTED
- Fallback → UNKNOWN (not NOT_READY)
"""
import re

from app.domain.enums import CpinState

# Exact line-level patterns — NOT substring match on concatenated response
_CPIN_READY_RE = re.compile(r'(?:^|\n)\s*\+CPIN:\s*READY\s*(?:\n|$)', re.IGNORECASE)
_CPIN_NOT_READY_RE = re.compile(r'(?:^|\n)\s*\+CPIN:\s*NOT\s+READY\s*(?:\n|$)', re.IGNORECASE)
_CPIN_NOT_INSERTED_RE = re.compile(r'(?:^|\n)\s*\+CPIN:\s*(?:SIM\s+)?NOT\s+INSERTED\s*(?:\n|$)', re.IGNORECASE)
_CPIN_PIN_REQUIRED_RE = re.compile(r'(?:^|\n)\s*\+CPIN:\s*(?:SIM\s+)?PIN(?:\s+REQUIRED)?\s*(?:\n|$)', re.IGNORECASE)
_CME_ERROR_RE = re.compile(r'(?:^|\n)\s*\+CME\s+ERROR\s*:\s*\d+\s*(?:\n|$)', re.IGNORECASE)


def parse_cpin_response(response: str) -> CpinState:
    """Parse AT+CPIN? response into CpinState with anti-false-positive guards.

    Check order (critical):
    1. None/empty → UNKNOWN
    2. +CME ERROR → NOT_INSERTED (SIM not available = all errors = not inserted)
    3. NOT INSERTED → NOT_INSERTED
    4. NOT READY → NOT_READY (must check BEFORE READY to prevent substring collision)
    5. PIN REQUIRED → PIN_REQUIRED
    6. READY (with +CPIN: prefix validation) → READY
    7. Fallback → UNKNOWN (never assume NOT_READY without explicit signal)
    """
    if response is None:
        return CpinState.UNKNOWN

    raw = response.strip()
    if not raw:
        return CpinState.UNKNOWN

    # Check +CME ERROR first — SIM not available
    if _CME_ERROR_RE.search(raw):
        return CpinState.NOT_INSERTED

    # Check NOT INSERTED — explicit missing SIM
    if _CPIN_NOT_INSERTED_RE.search(raw):
        return CpinState.NOT_INSERTED

    # Check NOT READY — BEFORE READY to prevent substring collision
    if _CPIN_NOT_READY_RE.search(raw):
        return CpinState.NOT_READY

    # Check PIN REQUIRED
    if _CPIN_PIN_REQUIRED_RE.search(raw):
        return CpinState.PIN_REQUIRED

    # Check READY — with +CPIN: prefix validation
    # This prevents false positive from stale USSD data containing "READY"
    if _CPIN_READY_RE.search(raw):
        return CpinState.READY

    # Fallback: UNKNOWN (not NOT_READY — we need explicit signal)
    return CpinState.UNKNOWN
