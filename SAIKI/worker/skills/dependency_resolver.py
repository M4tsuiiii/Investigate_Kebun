"""Skill Dependency Resolver — resolves per-port hardware dependencies.

Sprint 15S.2: Eliminates global skill-map overwrite. Each workflow run
resolves dependencies for its exact target port using this resolver.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger("saiki.skill_resolver")


class SkillDependencyResolver:
    """Resolves per-port hardware dependencies from WorkerManager.

    Created per-workflow-run for a specific target port.
    Skills use this to get ATClient/UssdRuntime for their target port,
    never for a different port.
    """

    def __init__(self, worker_manager: Any, port: str) -> None:
        self._worker_manager = worker_manager
        self._port = port
        self._worker = worker_manager.get_worker(port)

    @property
    def port(self) -> str:
        return self._port

    @property
    def is_valid(self) -> bool:
        return self._worker is not None

    def get_at_client(self) -> Optional[Any]:
        if self._worker is None:
            logger.warning("[SKILL PORT BINDING] PORT=%s SKILL=? MATCH=NO REASON=no_worker", self._port)
            return None
        return getattr(self._worker, "_at_client", None)

    def get_ussd_runtime(self) -> Optional[Any]:
        if self._worker is None:
            return None
        return getattr(self._worker, "_ussd_runtime", None)

    def get_serial(self) -> Optional[Any]:
        if self._worker is None:
            return None
        return getattr(self._worker, "_serial", None)

    def get_cpin_runtime(self) -> Optional[Any]:
        if self._worker is None:
            return None
        return getattr(self._worker, "_cpin_runtime", None)

    def log_binding(self, skill_name: str, component: str, dep_port: str) -> None:
        match = "YES" if dep_port == self._port else "NO"
        serial = self.get_serial()
        serial_id = id(serial) if serial else 0
        logger.info(
            "[SKILL PORT BINDING] PORT=%s SKILL=%s %s_PORT=%s SERIAL_ID=%d MATCH=%s",
            self._port, skill_name, component, dep_port, serial_id, match,
        )
        if match == "NO":
            logger.error(
                "[SKILL PORT BINDING] PORT=%s SKILL=%s MISMATCH DETECTED — dependency belongs to %s not %s",
                self._port, skill_name, dep_port, self._port,
            )
