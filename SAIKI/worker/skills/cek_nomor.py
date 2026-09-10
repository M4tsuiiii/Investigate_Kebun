"""Skill: Cek Nomor — Retrieve SIM phone number via AT+CNUM or USSD fallback.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.
"""

import logging
import time
from typing import Any, Dict, Optional

from worker.skills.base import Skill, SkillResult

logger = logging.getLogger("saiki.skill.cek_nomor")


class CekNomorSkill(Skill):
    """Retrieve SIM phone number.

    Execution order:
    1. AT+CNUM -> parse MSISDN
    2. If no number from CNUM -> configured USSD fallback
    3. Parse number from USSD response
    """

    def __init__(self, at_client: object, ussd_runtime: object = None,
                 command_registry: object = None, parser_registry: object = None,
                 phone_cache: object = None) -> None:
        self._at_client = at_client
        self._ussd_runtime = ussd_runtime
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry
        self._phone_cache = phone_cache

    @property
    def name(self) -> str:
        return "cek_nomor"

    @property
    def description(self) -> str:
        return "Retrieve SIM phone number via AT+CNUM with USSD fallback"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=cek_nomor", command_id, port)

        timeout: float = kwargs.get("timeout", 5.0)

        # Resolve per-port dependencies
        at_client = self._at_client
        ussd_runtime = self._ussd_runtime
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved_at = resolver.get_at_client()
            resolved_ussd = resolver.get_ussd_runtime()
            if resolved_at:
                at_client = resolved_at
            if resolved_ussd:
                ussd_runtime = resolved_ussd
            resolver.log_binding("cek_nomor", "AT_CLIENT",
                                 resolver.port if hasattr(resolver, 'port') else port)

        if not at_client:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=cek_nomor PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No AT client available")

        # Get command from registry
        at_command = "AT+CNUM"
        ussd_code = ""
        parser_name = "parse_cnum"
        if self._cmd_reg:
            profile = self._cmd_reg.get("cek_nomor")
            if profile:
                at_command = profile.at_command or at_command
                parser_name = profile.parser_name or parser_name

        # Step 1: AT+CNUM
        logger.info("[CEK NOMOR CNUM] PORT=%s COMMAND_ID=%s SENDING %s", port, command_id, at_command)
        logger.info("[MODEM ACTION] PORT=%s COMMAND=%s PAYLOAD=%s", port, at_command, at_command)
        try:
            response = at_client.send_command(at_command, timeout=timeout)
        except Exception as e:
            logger.info("[CEK NOMOR CNUM] PORT=%s COMMAND_ID=%s EXCEPTION=%s", port, command_id, e)
            response = None

        # Parse MSISDN from +CNUM response
        parsed_number = None
        raw_cnum = ""
        if response and response.success:
            raw_cnum = response.raw or ""
            if self._parser_reg:
                parsed = self._parser_reg.parse(parser_name, raw_cnum)
                parsed_number = parsed.get("number")
            logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                         port, repr(raw_cnum), repr(parsed_number),
                         "SUCCESS" if parsed_number else "NO_NUMBER")
        else:
            raw_resp = response.raw if response else "None"
            logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=None RESULT=FAILED", port, repr(raw_resp))

        # Step 2: USSD fallback if no number from CNUM
        if not parsed_number:
            logger.info("[CEK NOMOR USSD FALLBACK] PORT=%s COMMAND_ID=%s", port, command_id)
            if ussd_runtime:
                ussd_code = self._get_ussd_code(kwargs)
                if ussd_code:
                    logger.info("[USSD DIAL] PORT=%s CODE=%s COMMAND_ID=%s", port, ussd_code, command_id)
                    logger.info("[MODEM ACTION] PORT=%s COMMAND=USSD PAYLOAD=%s", port, ussd_code)
                    ussd_response = ussd_runtime.dial(ussd_code, timeout=30.0)
                    if ussd_response:
                        if self._parser_reg:
                            parsed = self._parser_reg.parse("extract_number_from_ussd", ussd_response)
                            parsed_number = parsed.get("number")
                        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                                     port, repr(ussd_response), repr(parsed_number),
                                     "SUCCESS" if parsed_number else "NO_NUMBER")
                    else:
                        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=None PARSED=None RESULT=USSD_NO_RESPONSE", port)
                else:
                    logger.info("[CEK NOMOR USSD FALLBACK] PORT=%s COMMAND_ID=%s REASON=number_ussd_not_configured",
                                 port, command_id)
                    _dur_ms = int((time.monotonic() - _t_start) * 1000)
                    logger.info("[PERFORMANCE TRACE] SKILL=cek_nomor PORT=%s DURATION_MS=%d", port, _dur_ms)
                    return self._failure(port, "number_ussd_not_configured")
            else:
                logger.info("[CEK NOMOR USSD FALLBACK] PORT=%s COMMAND_ID=%s REASON=no_ussd_runtime", port, command_id)

        # Build result
        data: Dict[str, Any] = {
            "modem_responsive": True,
            "raw_cnum": raw_cnum,
            "number": parsed_number or "-",
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=cek_nomor PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=cek_nomor PORT=%s DURATION_MS=%d", port, _dur_ms)

        if parsed_number:
            logger.info("[CEK NOMOR RESULT] PORT=%s COMMAND_ID=%s OUTCOME=success NOMOR=%s",
                         port, command_id, parsed_number)
            # BUILD-C: Save to phone cache
            if self._phone_cache and parsed_number and parsed_number != "-":
                self._phone_cache.put(parsed_number, source="at_cnum")
            return self._success(port, data)
        else:
            logger.info("[CEK NOMOR RESULT] PORT=%s COMMAND_ID=%s OUTCOME=failed REASON=no_number_found",
                         port, command_id)
            return self._failure(port, "no_number_found")

    def _get_ussd_code(self, kwargs: Dict[str, Any]) -> Optional[str]:
        """Get configured number-check USSD code from settings."""
        settings = kwargs.get("settings", {})
        workflow_cfg = settings.get("workflow", {})
        return workflow_cfg.get("number_ussd_code", "")
