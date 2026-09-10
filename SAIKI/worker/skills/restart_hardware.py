"""Skill: Restart Hardware — Send ATZ and wait for modem.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.

Restart types:
- Tunggal: restart 1 port
- Massal: restart semua port
"""

import logging
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult
from app.domain.constants import STABILIZATION_SECONDS

logger = logging.getLogger("saiki.skill.restart_hardware")


class RestartHardwareSkill(Skill):
    """Restart modem hardware via ATZ command.

    Sends ATZ, waits for stabilization, then checks if modem is back online.
    """

    def __init__(self, at_client: object,
                 command_registry: object = None, parser_registry: object = None) -> None:
        self._at_client = at_client
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry

    @property
    def name(self) -> str:
        return "restart_hardware"

    @property
    def description(self) -> str:
        return "Restart modem via ATZ and wait for online"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=restart_hardware", command_id, port)

        wait_seconds: float = kwargs.get("wait_seconds", STABILIZATION_SECONDS)
        timeout: float = kwargs.get("timeout", 5.0)

        if not self._at_client:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=restart_hardware PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No AT client available")

        # Resolve per-port AT client
        at_client = self._at_client
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_at_client()
            if resolved:
                at_client = resolved
            resolver.log_binding("restart_hardware", "AT_CLIENT",
                                 resolver.port if hasattr(resolver, 'port') else port)

        # Get command from registry
        at_command = "ATZ"
        parser_name = "check_modem"
        if self._cmd_reg:
            profile = self._cmd_reg.get("restart_hardware")
            if profile:
                at_command = profile.at_command or at_command
                parser_name = profile.parser_name or parser_name

        # Send restart command
        logger.info("[MODEM ACTION] PORT=%s COMMAND=%s PAYLOAD=%s", port, at_command, at_command)
        response = at_client.send_command(at_command, timeout=timeout)
        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                     port, repr(response.raw if response else ""),
                     "success" if response and response.success else "failed",
                     "SUCCESS" if response and response.success else "FAILED")

        # Wait for modem to stabilize
        logger.info("[MODEM ACTION] PORT=%s COMMAND=WAIT PAYLOAD=%.1fs", port, wait_seconds)
        time.sleep(wait_seconds)

        # Check if modem came back
        logger.info("[MODEM ACTION] PORT=%s COMMAND=CHECK_MODEM PAYLOAD=check_modem", port)
        online = at_client.check_modem()
        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=check_modem PARSED=%s RESULT=%s",
                     port, str(online), "ONLINE" if online else "OFFLINE")

        data: Dict[str, Any] = {
            "restart_sent": response.success if response else False,
            "modem_online": online,
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=restart_hardware PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=restart_hardware PORT=%s DURATION_MS=%d", port, _dur_ms)

        if online:
            return self._success(port, data)
        else:
            return self._failure(port, "Modem did not come back online after restart")
