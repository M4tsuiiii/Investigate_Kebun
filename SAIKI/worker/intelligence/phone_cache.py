"""PhoneCache — In-memory cache for phone number → NIK/KK mapping.

Adopted from GOOD: phone_cache[nomor] = {nik, kk, updated_at}
Thread-safe, per-port, with TTL support.

Flow: Phone Cache → Local DB → Telegram → Store Cache
"""

import re
import time
import threading
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("saiki.intelligence.phone_cache")

# NIK/KK must be exactly 16 digits
_VALID_16_DIGIT = re.compile(r"^\d{16}$")


class PhoneCacheEntry:
    """Single cache entry for a phone number."""

    __slots__ = ("nomor", "nik", "kk", "last_updated", "source")

    def __init__(
        self,
        nomor: str,
        nik: str = "",
        kk: str = "",
        source: str = "",
    ) -> None:
        self.nomor = nomor
        self.nik = nik
        self.kk = kk
        self.last_updated = time.time()
        self.source = source  # "ussd", "db", "telegram"

    def is_complete(self) -> bool:
        """Both NIK and KK are present and valid 16-digit strings."""
        return (
            bool(self.nik)
            and bool(self.kk)
            and _VALID_16_DIGIT.match(self.nik)
            and _VALID_16_DIGIT.match(self.kk)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nomor": self.nomor,
            "nik": self.nik,
            "kk": self.kk,
            "last_updated": self.last_updated,
            "source": self.source,
        }


class PhoneCache:
    """Thread-safe in-memory phone cache.

    Stores nomor → {nik, kk} mappings.
    Adopted from GOOD: lookup_phone_cache / update_phone_cache.
    """

    def __init__(self, max_size: int = 10000, ttl_seconds: float = 0.0) -> None:
        """
        Args:
            max_size: Maximum cache entries (0 = unlimited)
            ttl_seconds: Cache entry TTL in seconds (0 = no expiry)
        """
        self._cache: Dict[str, PhoneCacheEntry] = {}
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def get(self, nomor: str) -> Optional[Dict[str, str]]:
        """Lookup cached NIK/KK for a phone number.

        Returns {"nik": ..., "kk": ...} if found and valid, else None.
        """
        nomor = str(nomor or "").strip()
        if not nomor:
            return None

        with self._lock:
            entry = self._cache.get(nomor)
            if entry is None:
                logger.info("[PHONE_CACHE] LOOKUP PORT=? NOMOR=%s RESULT=MISS", nomor)
                return None

            # Check TTL
            if self._ttl > 0 and (time.time() - entry.last_updated) > self._ttl:
                del self._cache[nomor]
                logger.info("[PHONE_CACHE] LOOKUP PORT=? NOMOR=%s RESULT=EXPIRED", nomor)
                return None

            if not entry.is_complete():
                logger.info("[PHONE_CACHE] LOOKUP PORT=? NOMOR=%s RESULT=INCOMPLETE nik=%s kk=%s",
                            nomor, bool(entry.nik), bool(entry.kk))
                return None

            logger.info("[PHONE_CACHE] LOOKUP PORT=? NOMOR=%s RESULT=HIT nik=%s kk=%s source=%s",
                        nomor, entry.nik[:4] + "****", entry.kk[:4] + "****", entry.source)
            return {"nik": entry.nik, "kk": entry.kk}

    def put(
        self,
        nomor: str,
        nik: str = "",
        kk: str = "",
        source: str = "ussd",
    ) -> bool:
        """Store NIK/KK for a phone number.

        Returns True if stored, False if validation fails.
        """
        nomor = str(nomor or "").strip()
        nik = str(nik or "").strip()
        kk = str(kk or "").strip()

        if not nomor:
            return False

        # Validate inputs (GOOD pattern: only store valid data)
        if nik and not _VALID_16_DIGIT.match(nik):
            logger.warning("[PHONE_CACHE] REJECT NOMOR=%s nik=%s reason=invalid_nik", nomor, nik)
            return False
        if kk and not _VALID_16_DIGIT.match(kk):
            logger.warning("[PHONE_CACHE] REJECT NOMOR=%s kk=%s reason=invalid_kk", nomor, kk)
            return False

        if not nik and not kk:
            return False

        with self._lock:
            # Evict if at capacity
            if self._max_size > 0 and len(self._cache) >= self._max_size:
                self._evict_oldest()

            existing = self._cache.get(nomor)
            if existing:
                # Merge — keep existing values if new ones are empty
                if nik:
                    existing.nik = nik
                if kk:
                    existing.kk = kk
                if source:
                    existing.source = source
                existing.last_updated = time.time()
            else:
                self._cache[nomor] = PhoneCacheEntry(
                    nomor=nomor, nik=nik, kk=kk, source=source,
                )

            logger.info("[PHONE_CACHE] STORE NOMOR=%s nik=%s kk=%s source=%s total=%d",
                        nomor, bool(nik), bool(kk), source, len(self._cache))
            return True

    def invalidate(self, nomor: str) -> bool:
        """Remove a phone number from cache."""
        with self._lock:
            removed = self._cache.pop(nomor, None) is not None
            if removed:
                logger.info("[PHONE_CACHE] INVALIDATE NOMOR=%s", nomor)
            return removed

    def clear(self) -> int:
        """Clear entire cache. Returns number of entries removed."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info("[PHONE_CACHE] CLEAR count=%d", count)
            return count

    def size(self) -> int:
        """Current cache size."""
        with self._lock:
            return len(self._cache)

    def _evict_oldest(self) -> None:
        """Remove the oldest entry (called under lock)."""
        if not self._cache:
            return
        oldest_key = min(self._cache, key=lambda k: self._cache[k].last_updated)
        del self._cache[oldest_key]

    def snapshot(self) -> Dict[str, Any]:
        """Return cache stats for debugging."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl,
            }
