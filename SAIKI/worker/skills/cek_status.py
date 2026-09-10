"""Skill: Cek Status — Check SIM/CPIN status via AT+CPIN?.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.
"""

import logging
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult
from app.domain.enums import CpinState
from app.domain.constants import CPIN_POLL_TIMEOUT

logger = logging.getLogger("saiki.skill.cek_status")


class CekStatusSkill(Skill):
    """Check SIM card status via AT+CPIN? command.

    Classifies response into CpinState enum:
    READY, NOT_INSERTED, PIN_REQUIRED, NOT_READY, UNKNOWN
    """

    def __init__(self, at_client: object,
                 command_registry: object = None, parser_registry: object = None) -> None:
        self._at_client = at_client
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry

    @property
    def name(self) -> str:
        return "cek_status"

    @property
    def description(self) -> str:
        return "Check SIM/CPIN status via AT+CPIN?"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=cek_status", command_id, port)

        timeout: float = kwargs.get("timeout", CPIN_POLL_TIMEOUT)

        if not self._at_client:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=cek_status PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No AT client available")

        # Resolve per-port AT client
        at_client = self._at_client
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_at_client()
            if resolved:
                at_client = resolved
            resolver.log_binding("cek_status", "AT_CLIENT",
                                 resolver.port if hasattr(resolver, 'port') else port)

        # Get command from registry
        at_command = "AT+CPIN?"
        parser_name = "parse_cpin_response"
        if self._cmd_reg:
            profile = self._cmd_reg.get("cek_status")
            if profile:
                at_command = profile.at_command or at_command
                parser_name = profile.parser_name or parser_name

        logger.info("[MODEM ACTION] PORT=%s COMMAND=%s PAYLOAD=%s", port, at_command, at_command)
        response = at_client.send_command(at_command, timeout=timeout)
        raw = response.raw if response else ""

        # Parse via registry
        cpin_state = CpinState.UNKNOWN
        if self._parser_reg:
            parsed = self._parser_reg.parse(parser_name, raw)
            cpin_state_value = parsed.get("cpin_state", "UNKNOWN")
            try:
                cpin_state = CpinState(cpin_state_value)
            except ValueError:
                cpin_state = CpinState.UNKNOWN
        else:
            from app.domain.classifier import parse_cpin_response
            cpin_state = parse_cpin_response(raw)

        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                     port, repr(raw), cpin_state.value,
                     "SUCCESS" if cpin_state == CpinState.READY else cpin_state.value)

        data: Dict[str, Any] = {
            "cpin_state": cpin_state.value,
            "raw_response": raw,
            "sim_ready": cpin_state == CpinState.READY,
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=cek_status PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=cek_status PORT=%s DURATION_MS=%d", port, _dur_ms)

        if cpin_state == CpinState.READY:
            return self._success(port, data)
        elif cpin_state == CpinState.NOT_INSERTED:
            return self._failure(port, "SIM not inserted")
        elif cpin_state == CpinState.PIN_REQUIRED:
            return self._failure(port, "SIM PIN required")
        else:
            return self._failure(port, f"SIM not ready: {cpin_state.value}")
