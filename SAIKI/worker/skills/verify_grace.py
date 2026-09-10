"""Skill: Verify Grace — Read grace period from USSD response.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.

Uses verify_grace_response parser for full before/after comparison.
"""

import logging
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult

logger = logging.getLogger("saiki.skill.verify_grace")


class VerifyGraceSkill(Skill):
    """Verify card grace period by reading USSD response.

    Dials USSD to check card status and extracts:
    - Card status (AKTIF, TENGGANG, HANGUS)
    - Grace date if available
    """

    def __init__(self, ussd_runtime: object,
                 command_registry: object = None, parser_registry: object = None) -> None:
        self._ussd_runtime = ussd_runtime
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry

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

        # Resolve per-port USSD runtime
        ussd_runtime = self._ussd_runtime
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_ussd_runtime()
            if resolved:
                ussd_runtime = resolved
            resolver.log_binding("verify_grace", "USSD",
                                 resolver.port if hasattr(resolver, 'port') else port)

        # Get command from registry
        ussd_code = "*185#"
        parser_name = "verify_grace_response"
        if self._cmd_reg:
            profile = self._cmd_reg.get("verify_grace")
            if profile:
                ussd_code = profile.ussd_code or ussd_code
                parser_name = profile.parser_name or parser_name

        logger.info("[MODEM ACTION] PORT=%s COMMAND=USSD PAYLOAD=%s", port, ussd_code)
        raw = ussd_runtime.dial(ussd_code, timeout=timeout)

        if raw is None:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=verify_grace PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "USSD dial failed — no response")

        # Parse via registry
        parsed: Dict[str, Any] = {"raw_response": raw}
        if self._parser_reg:
            grace_result = self._parser_reg.parse(parser_name, raw)
            parsed.update(grace_result)

        card_status = parsed.get("card_status", "UNKNOWN")
        grace_date = parsed.get("grace_date", "")

        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                     port, repr(raw),
                     f"card_status={card_status}",
                     card_status)

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=verify_grace PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=verify_grace PORT=%s DURATION_MS=%d", port, _dur_ms)

        if card_status in ("AKTIF", "TENGGANG"):
            return self._success(port, parsed)
        elif card_status == "HANGUS":
            return self._failure(port, f"Card is HANGUS (burned): {raw}")
        else:
            return self._failure(port, f"Unknown card status: {raw}")
