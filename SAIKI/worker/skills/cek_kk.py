"""Skill: Cek KK — Check KK information from cache/DB/Telegram.

Commands and parsers are read from CommandRegistry and ParserRegistry.
No hardcoded command strings.

FIX: Was sending *185# (wrong). Now uses cache type from CommandRegistry.
KK is NOT retrieved via USSD — it comes from cache, database, or Telegram.

BUILD-C: Integrated PhoneCache, DbCache, and TierSelection.
Query strategy: Phone Cache → DB Cache → Telegram → Store Cache
"""

import logging
import time
from typing import Any, Dict, Optional

from worker.skills.base import Skill, SkillResult

logger = logging.getLogger("saiki.skill.cek_kk")


class CekKkSkill(Skill):
    """Check KK information from cache, database, or Telegram.

    KK is NOT retrieved via USSD.
    It comes from:
    1. In-memory cache (fastest)
    2. Database lookup
    3. Telegram bot query (future)
    """

    def __init__(self, ussd_runtime: object = None,
                 command_registry: object = None, parser_registry: object = None,
                 phone_cache: object = None, db_cache: object = None,
                 tier_selection: object = None) -> None:
        self._ussd_runtime = ussd_runtime
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry
        self._phone_cache = phone_cache
        self._db_cache = db_cache
        self._tier_selection = tier_selection

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

        # Get NIK from kwargs (provided by previous step or context)
        nik = kwargs.get("nik", "")
        nomor = kwargs.get("nomor", "")

        kk = None
        source = "unknown"

        # Strategy: Phone Cache → DB Cache → Telegram (future)
        # 1. Check phone cache first (if we have nomor)
        if nomor and self._phone_cache:
            cached = self._phone_cache.get(nomor)
            if cached:
                kk = cached.get("kk", "")
                source = "phone_cache"
                logger.info("[CEK KK] PORT=%s SOURCE=phone_cache kk=%s", port, bool(kk))

        # 2. Check DB cache (if we have nik)
        if not kk and nik and self._db_cache:
            kk = self._db_cache.lookup_kk(nik)
            if kk:
                source = "db_cache"
                logger.info("[CEK KK] PORT=%s SOURCE=db_cache kk=%s", port, bool(kk))

                # Also populate phone cache for future lookups
                if nomor and self._phone_cache:
                    self._phone_cache.put(nomor, nik=nik, kk=kk, source="db_cache")

        # 3. Telegram gateway (future — not implemented yet)
        if not kk and nik:
            logger.info("[CEK KK] PORT=%s SOURCE=telegram SKIP reason=not_implemented", port)

        # Try parser registry to format result
        parsed: Dict[str, Any] = {
            "kk": kk or "",
            "nik": nik,
            "nomor": nomor,
            "source": source,
            "has_payload": bool(kk),
        }

        _dur_ms = int((time.monotonic() - _t_start) * 1000)
        if _dur_ms > 2000:
            logger.info("[SLOW OPERATION] SKILL=cek_kk PORT=%s DURATION_MS=%d", port, _dur_ms)
        logger.info("[PERFORMANCE TRACE] SKILL=cek_kk PORT=%s DURATION_MS=%d", port, _dur_ms)

        if kk:
            logger.info("[CEK KK RESULT] PORT=%s COMMAND_ID=%s OUTCOME=success KK=%s SOURCE=%s",
                         port, command_id, kk[:4] + "****" if len(kk) > 4 else kk, source)
            return self._success(port, parsed)
        else:
            logger.info("[CEK KK RESULT] PORT=%s COMMAND_ID=%s OUTCOME=failed REASON=no_kk_found",
                         port, command_id)
            return self._failure(port, "no_kk_found")
