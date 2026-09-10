"""DbLookup — Database lookup for context menu actions.

Requirement 4: Add Lookup NIK and Lookup KK to context menu.
Source: local database.
"""

import sqlite3
import threading
from typing import Optional, Dict, Any


class DbLookup:
    """Handles database lookups for NIK and KK.
    
    Responsibilities:
    - Connect to SQLite database
    - Lookup NIK by MSISDN (phone number)
    - Lookup KK by NIK
    - Thread-safe connection management
    """
    
    def __init__(self, db_path: str = "kebun.db") -> None:
        self._db_path: str = db_path
        self._lock: threading.Lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
    
    def connect(self) -> None:
        """Open database connection."""
        with self._lock:
            if self._conn is None:
                self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
    
    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
    
    def lookup_nik(self, msisdn: str) -> Optional[Dict[str, Any]]:
        """Lookup NIK by MSISDN (phone number).
        
        Returns dict with NIK and card data, or None if not found.
        """
        with self._lock:
            if self._conn is None:
                return None
            
            try:
                cursor = self._conn.execute(
                    "SELECT nik, nomor, masa_aktif FROM cards WHERE nomor = ?",
                    (msisdn,),
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "msisdn": row["nomor"],
                        "nik": row["nik"],
                        "masa_aktif": row["masa_aktif"],
                    }
                return None
            except Exception:
                return None
    
    def lookup_kk(self, nik: str) -> Optional[Dict[str, Any]]:
        """Lookup KK (Kartu Keluarga) by NIK.
        
        Returns dict with KK number, or None if not found.
        """
        with self._lock:
            if self._conn is None:
                return None
            
            try:
                cursor = self._conn.execute(
                    "SELECT kk FROM cards WHERE nik = ?",
                    (nik,),
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "nik": nik,
                        "kk": row["kk"],
                    }
                return None
            except Exception:
                return None
    
    def ensure_table(self) -> None:
        """Create cards table if it doesn't exist."""
        with self._lock:
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
    
    def save_card(
        self,
        nomor: str,
        nik: Optional[str] = None,
        kk: Optional[str] = None,
        masa_aktif: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        """Save or update card data."""
        with self._lock:
            if self._conn is None:
                return
            
            self._conn.execute("""
                INSERT OR REPLACE INTO cards (nomor, nik, kk, masa_aktif, status, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (nomor, nik, kk, masa_aktif, status))
            self._conn.commit()
