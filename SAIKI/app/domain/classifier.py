"""Classifier — Shared parsing functions for modem responses."""
from app.domain.enums import CpinState

def parse_cpin_response(response: str) -> CpinState:
    """Parse AT+CPIN? response into CpinState."""
    if response is None:
        return CpinState.UNKNOWN
    response_upper = response.upper()
    # Check "NOT READY" before "READY" (substring match: "READY" in "NOT READY")
    if "NOT READY" in response_upper:
        return CpinState.NOT_READY
    elif "READY" in response_upper:
        return CpinState.READY
    elif "NOT INSERTED" in response_upper or "SIM NOT INSERTED" in response_upper:
        return CpinState.NOT_INSERTED
    elif "PIN REQUIRED" in response_upper or "SIM PIN" in response_upper:
        return CpinState.PIN_REQUIRED
    else:
        return CpinState.NOT_READY
