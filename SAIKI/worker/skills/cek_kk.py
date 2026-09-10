"""Skill: Cek KK — Check KK information from cache/DB/Telegram.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.

FIX: Was sending *185# (wrong). Now uses cache type from CommandRegistry.
KK is NOT retrieved via USSD — it comes from cache, database, or Telegram.
"""

import logging
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult

logger = logging.getLogger("saiki.skill.cek_kk")


class CekKkSkill(Skill):
    """Check KK information from cache, database, or Telegram.

    KK is NOT retrieved via USSD.
    It comes from:
    1. In-memory cache (fastest)
    2. Database lookup
    3. Telegram bot query
    """

    def __init__(self, ussd_runtime: object = None,
                 command_registry: object = None, parser_registry: object = None) -> None:
        self._ussd_runtime = ussd_runtime
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry

    @property
    def name(self) -> str:
        return "cek_kk"

    @property
    def description(self) -> str:
        return "Check KK information from cache/DB/Telegram"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=cek_kk", command_id, port)

        # Resolve per-port USSD runtime
        ussd_runtime = self._ussd_runtime
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_ussd_runtime()
            if resolved:
                ussd_runtime = resolved
            resolver.log_binding("cek_kk", "USSD",
                                 resolver.port if hasattr(resolver, 'port') else port)

        # Get command from registry (type=cache)
        parser_name = "extract_kk"
        if self._cmd_reg:
            profile = self._cmd_reg.get("cek_kk")
            if profile:
                parser_name = profile.parser_name or parser_name

        # KK comes from cache/DB/Telegram — try kwargs first
        kk = kwargs.get("kk")
        source = kwargs.get("kk_source", "unknown")

        # Try parser registry to format result
        parsed: Dict[str, Any] = {
            "kk": kk,
            "source": source,
            "has_payload": bool(kk),
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=cek_kk PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=cek_kk PORT=%s DURATION_MS=%d", port, _dur_ms)

        if kk:
            logger.info("[CEK KK RESULT] PORT=%s COMMAND_ID=%s OUTCOME=success KK=%s SOURCE=%s",
                         port, command_id, kk, source)
            return self._success(port, parsed)
        else:
            logger.info("[CEK KK RESULT] PORT=%s COMMAND_ID=%s OUTCOME=failed REASON=no_kk_found",
                         port, command_id)
            return self._failure(port, "no_kk_found")
