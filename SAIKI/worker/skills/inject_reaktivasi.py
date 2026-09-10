"""Skill: Inject Reaktivasi — Send reactivation via USSD.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.

Uses USSD template: *888*89*1*{NIK}*{KK}#
"""

import logging
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult

logger = logging.getLogger("saiki.skill.inject_reaktivasi")


class InjectReaktivasiSkill(Skill):
    """Inject reactivation command via USSD.

    Sends the reactivation USSD code and captures the response.
    Does NOT verify — verification is a separate skill.
    """

    def __init__(self, ussd_runtime: object,
                 command_registry: object = None, parser_registry: object = None,
                 bypass_flags: object = None) -> None:
        self._ussd_runtime = ussd_runtime
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry
        self._bypass = bypass_flags

    @property
    def name(self) -> str:
        return "inject_reaktivasi"

    @property
    def description(self) -> str:
        return "Send reactivation command via USSD"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=inject_reaktivasi", command_id, port)

        timeout: float = kwargs.get("timeout", 30.0)

        # BUILD-C: Check bypass flags before injection
        if self._bypass:
            card_status = kwargs.get("card_status", "")
            skip_reason = self._bypass.should_skip_injection(card_status)
            if skip_reason:
                logger.info("[INJECT REAKTIVASI] PORT=%s SKIP reason=%s card_status=%s",
                             port, skip_reason, card_status)
                _dur_ms = int((time.monotonic() - _t_start) * 1000)
                logger.info("[PERFORMANCE TRACE] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)
                return self._success(port, {
                    "injected": False,
                    "skipped": True,
                    "skip_reason": skip_reason,
                    "card_status": card_status,
                })

        if not self._ussd_runtime:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No USSD runtime available")

        # Resolve per-port USSD runtime
        ussd_runtime = self._ussd_runtime
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_ussd_runtime()
            if resolved:
                ussd_runtime = resolved
            resolver.log_binding("inject_reaktivasi", "USSD",
                                 resolver.port if hasattr(resolver, 'port') else port)

        # Get command from registry — resolve template with NIK/KK
        ussd_code = "*185#"
        parser_name = "classify_injection_response"
        if self._cmd_reg:
            profile = self._cmd_reg.get("inject_reaktivasi")
            if profile:
                parser_name = profile.parser_name or parser_name
                # Resolve USSD template with NIK and KK from kwargs
                nik = kwargs.get("nik", "")
                kk = kwargs.get("kk", "")
                if profile.ussd_template:
                    ussd_code = self._cmd_reg.get_ussd_code("inject_reaktivasi", NIK=nik, KK=kk)
                elif profile.ussd_code:
                    ussd_code = profile.ussd_code

        logger.info("[MODEM ACTION] PORT=%s COMMAND=USSD PAYLOAD=%s", port, ussd_code)
        raw = ussd_runtime.dial(ussd_code, timeout=timeout)

        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                     port, repr(raw),
                     repr(raw[:50]) if raw and raw.strip() else "None",
                     "SUCCESS" if raw and raw.strip() else "EMPTY")

        if raw is None:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "USSD dial failed — no response")

        if not raw or not raw.strip():
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "Empty response after injection")

        # Parse injection response
        parsed: Dict[str, Any] = {
            "raw_response": raw,
            "injected": bool(raw and raw.strip()),
            "ussd_code": ussd_code,
        }
        if self._parser_reg:
            inject_result = self._parser_reg.parse(parser_name, raw)
            parsed.update(inject_result)

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)

        return self._success(port, parsed)
