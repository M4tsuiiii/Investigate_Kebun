"""Skill: Verify Grace — Read grace period from USSD response.

Sprint 15T: Added forensic instrumentation.
"""

import logging
import re
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult
from app.domain.enums import CardStatus

logger = logging.getLogger("saiki.skill.verify_grace")


class VerifyGraceSkill(Skill):
    """Verify card grace period by reading USSD response.
    
    Dials USSD to check card status and extracts:
    - Card status (AKTIF, TENGGANG, HANGUS)
    - Grace date if available
    """

    def __init__(self, ussd_runtime: object) -> None:
        self._ussd_runtime = ussd_runtime

    @property
    def name(self) -> str:
        return "verify_grace"

    @property
    def description(self) -> str:
        return "Verify card grace period via USSD"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=verify_grace", command_id, port)

        timeout: float = kwargs.get("timeout", 30.0)

        if not self._ussd_runtime:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=verify_grace PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No USSD runtime available")

        # Resolve per-port USSD runtime (Sprint 15S.2)
        ussd_runtime = self._ussd_runtime
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_ussd_runtime()
            if resolved:
                ussd_runtime = resolved
            resolver.log_binding("verify_grace", "USSD",
                                 resolver.port if hasattr(resolver, 'port') else port)

        logger.info("[MODEM ACTION] PORT=%s COMMAND=USSD PAYLOAD=*185#", port)
        raw = ussd_runtime.dial("*185#", timeout=timeout)

        card_status = self._classify_card_status(raw or "")
        grace_date = self._extract_grace_date(raw or "")

        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                     port, repr(raw),
                     f"card_status={card_status.value}",
                     card_status.value)

        data: Dict[str, Any] = {
            "raw_response": raw,
            "card_status": card_status.value,
            "grace_date": grace_date,
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=verify_grace PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=verify_grace PORT=%s DURATION_MS=%d", port, _dur_ms)

        if raw is None:
            return self._failure(port, "USSD dial failed — no response")

        if card_status in (CardStatus.AKTIF, CardStatus.TENGGANG):
            return self._success(port, data)
        elif card_status == CardStatus.HANGUS:
            return self._failure(port, f"Card is HANGUS (burned): {raw}")
        else:
            return self._failure(port, f"Unknown card status: {raw}")

    def _classify_card_status(self, raw: str) -> CardStatus:
        """Classify card status from raw USSD response."""
        raw_lower = raw.lower()
        if "hangus" in raw_lower or "burned" in raw_lower:
            return CardStatus.HANGUS
        if "tenggang" in raw_lower or "grace" in raw_lower:
            return CardStatus.TENGGANG
        if "aktif" in raw_lower or "active" in raw_lower:
            return CardStatus.AKTIF
        return CardStatus.UNKNOWN

    def _extract_grace_date(self, raw: str) -> str:
        """Extract grace date from raw response if present."""
        date_patterns = [
            r"(\d{2}[-/]\d{2}[-/]\d{4})",
            r"(\d{4}[-/]\d{2}[-/]\d{2})",
        ]
        for pattern in date_patterns:
            match = re.search(pattern, raw)
            if match:
                return match.group(1)
        return ""
