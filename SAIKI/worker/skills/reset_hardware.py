"""Skill: Reset Hardware — Full hardware reset cycle.

Sprint 15T: Added forensic instrumentation.
"""

import logging
import time
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult
from app.domain.classifier import parse_cpin_response
from app.domain.enums import CpinState
from app.domain.constants import STABILIZATION_SECONDS, CPIN_POLL_TIMEOUT

logger = logging.getLogger("saiki.skill.reset_hardware")


class ResetHardwareSkill(Skill):
    """Full hardware reset cycle (Sprint 15O: pause CpinRuntime).

    Steps:
    1. Stop CpinRuntime (pause polling)
    2. Close serial connection
    3. Wait for stabilization
    4. Reopen serial connection
    5. Start CpinRuntime (resume polling)
    6. Detect SIM state
    7. Evaluate readiness
    """

    def __init__(self, serial_adapter: object, at_client: object, cpin_runtime: object = None) -> None:
        self._serial = serial_adapter
        self._at_client = at_client
        self._cpin_runtime = cpin_runtime

    @property
    def name(self) -> str:
        return "reset_hardware"

    @property
    def description(self) -> str:
        return "Full hardware reset: pause cpin → close → wait → reopen → resume cpin → detect SIM"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        _t_start = time.monotonic()
        command_id = kwargs.get("command_id", "N/A")
        logger.info("[SKILL ENTRY] COMMAND_ID=%s PORT=%s SKILL=reset_hardware", command_id, port)

        wait_seconds: float = kwargs.get("wait_seconds", STABILIZATION_SECONDS)

        if not self._serial or not self._at_client:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=reset_hardware PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "No serial adapter or AT client available")

        serial_id = id(self._serial)

        # 1. Stop CPIN runtime (Sprint 15O: prevent concurrent polling)
        logger.info("[RESET SEQUENCE] PORT=%s STEP=CPIN_STOP SERIAL_ID=%d", port, serial_id)
        if self._cpin_runtime:
            self._cpin_runtime.stop(timeout=5.0)
            logger.info("[RESET SEQUENCE] PORT=%s STEP=CPIN_STOPPED", port)
        else:
            logger.info("[RESET SEQUENCE] PORT=%s STEP=CPIN_STOP SKIPPED=no_runtime", port)

        # 2. Close serial
        logger.info("[MODEM ACTION] PORT=%s COMMAND=SERIAL_CLOSE PAYLOAD=close", port)
        logger.info("[RESET SEQUENCE] PORT=%s STEP=SERIAL_CLOSE SERIAL_ID=%d", port, serial_id)
        logger.info("[PORT CLOSED TRACE] PORT=%s SERIAL_ID=%d CALLER=ResetHardwareSkill REASON=reset_hardware",
                    port, serial_id)
        logger.info("[PORT OWNERSHIP] ROLE=RESET_HARDWARE PORT=%s SERIAL_ID=%d ACTION=close IS_OPEN=%s",
                    port, serial_id, self._serial.is_open if hasattr(self._serial, 'is_open') else 'unknown')
        self._serial.close()
        logger.info("[PORT OWNERSHIP] ROLE=RESET_HARDWARE PORT=%s SERIAL_ID=%d ACTION=closed",
                    port, serial_id)

        # 3. Wait
        logger.info("[MODEM ACTION] PORT=%s COMMAND=WAIT PAYLOAD=%.1fs", port, wait_seconds)
        logger.info("[RESET SEQUENCE] PORT=%s STEP=MODEM_RESET WAIT=%.1f", port, wait_seconds)
        time.sleep(wait_seconds)

        # 4. Reopen serial
        logger.info("[MODEM ACTION] PORT=%s COMMAND=SERIAL_REOPEN PAYLOAD=open", port)
        logger.info("[RESET SEQUENCE] PORT=%s STEP=SERIAL_REOPEN SERIAL_ID=%d", port, serial_id)
        logger.info("[PORT OWNERSHIP] ROLE=RESET_HARDWARE PORT=%s SERIAL_ID=%d ACTION=reopen",
                    port, serial_id)
        reopened = self._serial.open()
        logger.info("[PORT OWNERSHIP] ROLE=RESET_HARDWARE PORT=%s SERIAL_ID=%d ACTION=reopened IS_OPEN=%s",
                    port, serial_id, reopened)
        if not reopened:
            _dur_ms = int((time.monotonic() - _t_start) * 1000)
            logger.info("[PERFORMANCE TRACE] SKILL=reset_hardware PORT=%s DURATION_MS=%d", port, _dur_ms)
            return self._failure(port, "Failed to reopen serial port")

        # 5. Start CPIN runtime (Sprint 15O: resume polling)
        logger.info("[RESET SEQUENCE] PORT=%s STEP=CPIN_START", port)
        if self._cpin_runtime:
            self._cpin_runtime.reset_stabilization()
            self._cpin_runtime.start()
            logger.info("[RESET SEQUENCE] PORT=%s STEP=CPIN_STARTED", port)
        else:
            logger.info("[RESET SEQUENCE] PORT=%s STEP=CPIN_START SKIPPED=no_runtime", port)

        # 6. Check modem
        logger.info("[MODEM ACTION] PORT=%s COMMAND=CHECK_MODEM PAYLOAD=check_modem", port)
        online = self._at_client.check_modem()
        logger.info("[MODEM INTERPRETATION] PORT=%s RAW=check_modem PARSED=%s RESULT=%s",
                     port, str(online), "ONLINE" if online else "OFFLINE")

        # 7. Detect SIM
        sim_state = CpinState.UNKNOWN
        if online:
            logger.info("[MODEM ACTION] PORT=%s COMMAND=AT+CPIN? PAYLOAD=AT+CPIN?", port)
            response = self._at_client.send_command("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
            raw = response.raw if response else ""
            sim_state = parse_cpin_response(raw)
            logger.info("[MODEM INTERPRETATION] PORT=%s RAW=%s PARSED=%s RESULT=%s",
                         port, repr(raw), sim_state.value, sim_state.value)

        ready = online and sim_state == CpinState.READY

        data: Dict[str, Any] = {
            "modem_online": online,
            "cpin_state": sim_state.value,
            "ready": ready,
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=reset_hardware PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=reset_hardware PORT=%s DURATION_MS=%d", port, _dur_ms)

        if ready:
            return self._success(port, data)
        elif not online:
            return self._failure(port, "Modem offline after reset")
        else:
            return self._failure(port, f"SIM not ready: {sim_state.value}")
