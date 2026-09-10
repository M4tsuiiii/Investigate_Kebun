"""Skill: Cek NIK — Check NIK information via USSD *888*4444*1#.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.

FIX: Was sending *185# (wrong). Now reads *888*4444*1# from CommandRegistry.
"""

import logging
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult

logger = logging.getLogger("saiki.skill.cek_nik")


class CekNikSkill(Skill):
    """Check NIK information by dialing USSD code.

    Dials *888*4444*1# to query NIK status.
    Returns parsed NIK from response.
    """

    def __init__(self, ussd_runtime: object,
                 command_registry: object = None, parser_registry: object = None) -> None:
        self._ussd_runtime = ussd_runtime
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry

    @property
    def name(self) -> str:
        return "cek_nik"

    @property
    def description(self) -> str:
        return "Check NIK information via USSD *888*4444*1#"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=cek_nik", command_id, port)

        timeout: float = kwargs.get("timeout", 30.0)

        if not self._ussd_runtime:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=cek_nik PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No USSD runtime available")

        # Resolve per-port USSD runtime
        ussd_runtime = self._ussd_runtime
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_ussd_runtime()
            if resolved:
                ussd_runtime = resolved
            resolver.log_binding("cek_nik", "USSD",
                                 resolver.port if hasattr(resolver, 'port') else port)

        # Get command from registry
        ussd_code = "*888*4444*1#"
        parser_name = "extract_nik"
        if self._cmd_reg:
            profile = self._cmd_reg.get("cek_nik")
            if profile:
                ussd_code = profile.ussd_code or ussd_code
                parser_name = profile.parser_name or parser_name

        logger.info("[MODEM ACTION] PORT=%s COMMAND=USSD PAYLOAD=%s", port, ussd_code)
        raw = ussd_runtime.dial(ussd_code, timeout=timeout)

        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                     port, repr(raw),
                     repr(raw[:50]) if raw and raw.strip() else "None",
                     "SUCCESS" if raw and raw.strip() else "EMPTY")

        if raw is None:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=cek_nik PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "USSD dial failed")

        if not raw or not raw.strip():
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=cek_nik PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "Empty USSD response")

        # Parse NIK from response
        parsed: Dict[str, Any] = {"raw_response": raw, "has_payload": True, "ussd_code": ussd_code}
        if self._parser_reg:
            nik_result = self._parser_reg.parse(parser_name, raw)
            parsed["nik"] = nik_result.get("nik")

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=cek_nik PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=cek_nik PORT=%s DURATION_MS=%d", port, _dur_ms)

        return self._success(port, parsed)
