"""DbCache — SQLite-backed cache for NIK → KK lookup.

Adopted from GOOD: db_cache[nik] = kk, backed by panen_raya table.
Faster than Telegram, works offline.

Flow: Phone Cache → Local DB → Telegram → Store Cache
"""

import sqlite3
import threading
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("saiki.intelligence.db_cache")


class DbCache:
    """SQLite-backed NIK→KK cache.

    Provides fast local lookup before falling back to Telegram.
    Thread-safe via per-connection lock.
    """

    def __init__(self, db_path: str = "kebun.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        # In-memory mirror for fast reads (populated on connect)
        self._nik_to_kk: Dict[str, str] = {}
        self._loaded = False

    def connect(self) -> None:
        """Open database and load NIK→KK mirror."""
        with self._lock:
            if self._conn is not None:
                return
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._ensure_table()
            self._load_mirror()

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
            self._nik_to_kk.clear()
            self._loaded = False

    def lookup_kk(self, nik: str) -> Optional[str]:
        """Lookup KK by NIK.

        Returns KK string if found, else None.
        """
        nik = str(nik or "").strip()
        if not nik:
            return None

        # Fast path: in-memory mirror
        with self._lock:
            kk = self._nik_to_kk.get(nik)
            if kk:
                logger.info("[DB_CACHE] LOOKUP nik=%s RESULT=HIT kk=%s", nik, kk[:4] + "****")
                return kk

        # Slow path: SQLite query
        with self._lock:
            if self._conn is None:
                return None
            try:
                cursor = self._conn.execute(
                    "SELECT kk FROM cards WHERE nik = ?", (nik,)
                )
                row = cursor.fetchone()
                if row and row["kk"]:
                    kk = str(row["kk"])
                    # Update mirror
                    self._nik_to_kk[nik] = kk
                    logger.info("[DB_CACHE] LOOKUP nik=%s RESULT=DB_HIT kk=%s", nik, kk[:4] + "****")
                    return kk
            except Exception as e:
                logger.warning("[DB_CACHE] LOOKUP nik=%s ERROR=%s", nik, e)

        logger.info("[DB_CACHE] LOOKUP nik=%s RESULT=MISS", nik)
        return None

    def lookup_nik_by_nomor(self, nomor: str) -> Optional[Dict[str, str]]:
        """Lookup NIK and KK by phone number (MSISDN).

        Returns {"nik": ..., "kk": ...} if found, else None.
        """
        nomor = str(nomor or "").strip()
        if not nomor:
            return None

        with self._lock:
            if self._conn is None:
                return None
            try:
                cursor = self._conn.execute(
                    "SELECT nik, kk FROM cards WHERE nomor = ?", (nomor,)
                )
                row = cursor.fetchone()
                if row and row["nik"]:
                    nik = str(row["nik"])
                    kk = str(row["kk"]) if row["kk"] else ""
                    # Update mirror
                    if nik and kk:
                        self._nik_to_kk[nik] = kk
                    logger.info("[DB_CACHE] LOOKUP_NOMOR nomor=%s RESULT=HIT nik=%s",
                                nomor, nik[:4] + "****")
                    return {"nik": nik, "kk": kk}
            except Exception as e:
                logger.warning("[DB_CACHE] LOOKUP_NOMOR nomor=%s ERROR=%s", nomor, e)

        logger.info("[DB_CACHE] LOOKUP_NOMOR nomor=%s RESULT=MISS", nomor)
        return None

    def store(self, nomor: str, nik: str, kk: str) -> bool:
        """Store NIK/KK to database and update mirror.

        Returns True if stored successfully.
        """
        nomor = str(nomor or "").strip()
        nik = str(nik or "").strip()
        kk = str(kk or "").strip()

        if not nomor or not nik:
            return False

        with self._lock:
            if self._conn is None:
                return False
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO cards (nomor, nik, kk, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (nomor, nik, kk),
                )
                self._conn.commit()
                # Update mirror
                if nik and kk:
                    self._nik_to_kk[nik] = kk
                logger.info("[DB_CACHE] STORE nomor=%s nik=%s kk=%s",
                            nomor, nik[:4] + "****", kk[:4] + "****" if kk else "")
                return True
            except Exception as e:
                logger.warning("[DB_CACHE] STORE nomor=%s ERROR=%s", nomor, e)
                return False

    def size(self) -> int:
        """Number of entries in the in-memory mirror."""
        with self._lock:
            return len(self._nik_to_kk)

    def _ensure_table(self) -> None:
        """Create cards table if it doesn't exist."""
        if self._conn is None:
            return
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                nomor TEXT PRIMARY KEY,
                nik TEXT,
                kk TEXT,
                masa_aktif TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def _load_mirror(self) -> None:
        """Load all NIK→KK pairs into memory for fast reads."""
        if self._conn is None:
            return
        try:
            cursor = self._conn.execute("SELECT nik, kk FROM cards WHERE nik IS NOT NULL AND kk IS NOT NULL")
            for row in cursor:
                nik = str(row["nik"])
                kk = str(row["kk"])
                if nik and kk:
                    self._nik_to_kk[nik] = kk
            self._loaded = True
            logger.info("[DB_CACHE] MIRROR_LOADED count=%d", len(self._nik_to_kk))
        except Exception:
            pass
