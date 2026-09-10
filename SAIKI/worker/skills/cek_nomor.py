"""Skill: Cek Nomor — Retrieve SIM phone number via AT+CNUM or USSD fallback.

Sprint 15S.2: Real number retrieval, not just AT alive check.
1. Send AT+CNUM through target port's ATClient.
2. Parse MSISDN from +CNUM response.
3. If CNUM has no usable number, use configured USSD fallback.
4. Update NOMOR column via result data.

Sprint 15T: Added forensic instrumentation.
"""

import logging
import re
import time
from typing import Any, Dict, Optional

from worker.skills.base import Skill, SkillResult

logger = logging.getLogger("saiki.skill.cek_nomor")


class CekNomorSkill(Skill):
    """Retrieve SIM phone number.

    Execution order:
    1. AT+CNUM → parse MSISDN
    2. If no number from CNUM → configured USSD fallback
    3. Parse number from USSD response
    """

    def __init__(self, at_client: object, ussd_runtime: object = None) -> None:
        self._at_client = at_client
        self._ussd_runtime = ussd_runtime

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

        logger.info("[CEK NOMOR START] PORT=%s COMMAND_ID=%s", port, command_id)

        # Resolve per-port AT client and USSD runtime (Sprint 15S.2)
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

        # Step 1: AT+CNUM
        logger.info("[CEK NOMOR CNUM] PORT=%s COMMAND_ID=%s SENDING AT+CNUM", port, command_id)
        logger.info("[MODEM ACTION] PORT=%s COMMAND=AT+CNUM PAYLOAD=AT+CNUM", port)
        try:
            response = at_client.send_command("AT+CNUM", timeout=timeout)
        except Exception as e:
            logger.info("[CEK NOMOR CNUM] PORT=%s COMMAND_ID=%s EXCEPTION=%s", port, command_id, e)
            response = None

        # Parse MSISDN from +CNUM response
        parsed_number = None
        raw_cnum = ""
        if response and response.success:
            raw_cnum = response.raw or ""
            parsed_number = self._parse_cnum(raw_cnum)
            logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                         port, repr(raw_cnum), repr(parsed_number),
                         "SUCCESS" if parsed_number else "NO_NUMBER")
            if parsed_number:
                logger.info("[CEK NOMOR CNUM] PORT=%s COMMAND_ID=%s NUMBER=%s", port, command_id, parsed_number)
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
                        parsed_number = self._parse_ussd_number(ussd_response)
                        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                                     port, repr(ussd_response), repr(parsed_number),
                                     "SUCCESS" if parsed_number else "NO_NUMBER")
                        if parsed_number:
                            logger.info("[CEK NOMOR PARSED] PORT=%s COMMAND_ID=%s NUMBER=%s SOURCE=USSD",
                                         port, command_id, parsed_number)
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
            return self._success(port, data)
        else:
            logger.info("[CEK NOMOR RESULT] PORT=%s COMMAND_ID=%s OUTCOME=failed REASON=no_number_found",
                         port, command_id)
            return self._failure(port, "no_number_found")

    def _parse_cnum(self, raw: str) -> Optional[str]:
        """Parse MSISDN from +CNUM response.

        Format: +CNUM: "","number",type
        Example: +CNUM: "","081234567890",129
        """
        if not raw:
            return None
        match = re.search(r'\+CNUM:\s*"",\s*"(\d+)"', raw)
        if match:
            return match.group(1).strip()
        return None

    def _parse_ussd_number(self, raw: str) -> Optional[str]:
        """Extract phone number from USSD response text."""
        if not raw:
            return None
        # Look for common phone number patterns (10-13 digits)
        match = re.search(r'(0\d{9,12})', raw)
        if match:
            return match.group(1)
        match = re.search(r'(\+62\d{9,12})', raw)
        if match:
            return match.group(1)
        return None

    def _get_ussd_code(self, kwargs: Dict[str, Any]) -> Optional[str]:
        """Get configured number-check USSD code from settings."""
        settings = kwargs.get("settings", {})
        workflow_cfg = settings.get("workflow", {})
        return workflow_cfg.get("number_ussd_code", "")
