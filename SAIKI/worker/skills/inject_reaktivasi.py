"""Skill: Inject Reaktivasi — Send reactivation via USSD.

Sprint 15T: Added forensic instrumentation.
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

    def __init__(self, ussd_runtime: object) -> None:
        self._ussd_runtime = ussd_runtime

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

        ussd_code: str = kwargs.get("ussd_code", "*185#")
        timeout: float = kwargs.get("timeout", 30.0)

        if not self._ussd_runtime:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No USSD runtime available")

        # Resolve per-port USSD runtime (Sprint 15S.2)
        ussd_runtime = self._ussd_runtime
        resolver = kwargs.get("skill_resolver")
        if resolver:
            resolved = resolver.get_ussd_runtime()
            if resolved:
                ussd_runtime = resolved
            resolver.log_binding("inject_reaktivasi", "USSD",
                                 resolver.port if hasattr(resolver, 'port') else port)

        logger.info("[MODEM ACTION] PORT=%s COMMAND=USSD PAYLOAD=%s", port, ussd_code)
        raw = ussd_runtime.dial(ussd_code, timeout=timeout)

        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                     port, repr(raw),
                     repr(raw[:50]) if raw and raw.strip() else "None",
                     "SUCCESS" if raw and raw.strip() else "EMPTY")

        data: Dict[str, Any] = {
            "raw_response": raw,
            "injected": bool(raw and raw.strip()),
            "ussd_code": ussd_code,
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=inject_reaktivasi PORT=%s DURATION_MS=%d", port, _dur_ms)

        if raw is None:
            return self._failure(port, "USSD dial failed — no response")

        if raw and raw.strip():
            return self._success(port, data)
        else:
            return self._failure(port, "Empty response after injection")
