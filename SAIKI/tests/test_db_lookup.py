"""Tests for worker/db_lookup.py — database lookup for NIK and KK."""

import os
import sqlite3
import tempfile
import threading
import unittest

from worker.db_lookup import DbLookup


class TestDbLookupConnect(unittest.TestCase):
    """Tests for DbLookup.connect."""

    def test_connect_creates_connection(self):
        """connect should create a sqlite3 connection object."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            self.assertIsNotNone(lookup._conn)
            self.assertIsInstance(lookup._conn, sqlite3.Connection)
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_connect_sets_row_factory(self):
        """connect should set row_factory to sqlite3.Row."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            self.assertEqual(lookup._conn.row_factory, sqlite3.Row)
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_connect_idempotent(self):
        """connect called twice should reuse the same connection."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            first_conn = lookup._conn
            lookup.connect()
            self.assertIs(lookup._conn, first_conn)
            lookup.close()
        finally:
            os.unlink(db_path)


class TestDbLookupClose(unittest.TestCase):
    """Tests for DbLookup.close."""

    def test_close_closes_connection(self):
        """close should close the connection and set _conn to None."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.close()
            self.assertIsNone(lookup._conn)
        finally:
            os.unlink(db_path)

    def test_close_when_not_connected(self):
        """close when not connected should not raise an exception."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.close()
            self.assertIsNone(lookup._conn)
        finally:
            os.unlink(db_path)


class TestDbLookupEnsureTable(unittest.TestCase):
    """Tests for DbLookup.ensure_table."""

    def test_ensure_table_creates_cards_table(self):
        """ensure_table should create the cards table."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()

            cursor = lookup._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cards'"
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_ensure_table_idempotent(self):
        """ensure_table called twice should not raise an error."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()
            lookup.ensure_table()
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_ensure_table_no_connection(self):
        """ensure_table without connection should return silently."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.ensure_table()
            self.assertIsNone(lookup._conn)
        finally:
            os.unlink(db_path)


class TestDbLookupSaveCard(unittest.TestCase):
    """Tests for DbLookup.save_card."""

    def test_save_card_inserts_data(self):
        """save_card should insert card data into the cards table."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()
            lookup.save_card(
                nomor="08123456789",
                nik="3201234567890001",
                kk="3201234567890002",
                masa_aktif="2025-12-31",
                status="AKTIF",
            )

            cursor = lookup._conn.execute(
                "SELECT * FROM cards WHERE nomor = ?", ("08123456789",)
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["nik"], "3201234567890001")
            self.assertEqual(row["kk"], "3201234567890002")
            self.assertEqual(row["masa_aktif"], "2025-12-31")
            self.assertEqual(row["status"], "AKTIF")
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_save_card_replaces_on_conflict(self):
        """save_card should replace existing record on nomor conflict."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()
            lookup.save_card(nomor="08123", nik="nik1", kk="kk1")
            lookup.save_card(nomor="08123", nik="nik2", kk="kk2")

            cursor = lookup._conn.execute(
                "SELECT nik, kk FROM cards WHERE nomor = ?", ("08123",)
            )
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["nik"], "nik2")
            self.assertEqual(rows[0]["kk"], "kk2")
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_save_card_no_connection(self):
        """save_card without connection should return silently."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.save_card(nomor="08123", nik="nik1")
        finally:
            os.unlink(db_path)


class TestDbLookupLookupNik(unittest.TestCase):
    """Tests for DbLookup.lookup_nik."""

    def test_lookup_nik_returns_data_when_found(self):
        """lookup_nik should return dict with NIK data when MSISDN is found."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()
            lookup.save_card(
                nomor="08123456789",
                nik="3201234567890001",
                masa_aktif="2025-12-31",
            )

            result = lookup.lookup_nik("08123456789")
            self.assertIsNotNone(result)
            self.assertEqual(result["nik"], "3201234567890001")
            self.assertEqual(result["msisdn"], "08123456789")
            self.assertEqual(result["masa_aktif"], "2025-12-31")
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_lookup_nik_returns_none_when_not_found(self):
        """lookup_nik should return None when MSISDN is not in the database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()

            result = lookup.lookup_nik("99999999999")
            self.assertIsNone(result)
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_lookup_nik_no_connection(self):
        """lookup_nik without connection should return None."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            result = lookup.lookup_nik("08123456789")
            self.assertIsNone(result)
        finally:
            os.unlink(db_path)


class TestDbLookupLookupKk(unittest.TestCase):
    """Tests for DbLookup.lookup_kk."""

    def test_lookup_kk_returns_data_when_found(self):
        """lookup_kk should return dict with KK number when NIK is found."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()
            lookup.save_card(
                nomor="08123456789",
                nik="3201234567890001",
                kk="3201234567890002",
            )

            result = lookup.lookup_kk("3201234567890001")
            self.assertIsNotNone(result)
            self.assertEqual(result["nik"], "3201234567890001")
            self.assertEqual(result["kk"], "3201234567890002")
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_lookup_kk_returns_none_when_not_found(self):
        """lookup_kk should return None when NIK is not in the database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()

            result = lookup.lookup_kk("9999999999999999")
            self.assertIsNone(result)
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_lookup_kk_no_connection(self):
        """lookup_kk without connection should return None."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            result = lookup.lookup_kk("3201234567890001")
            self.assertIsNone(result)
        finally:
            os.unlink(db_path)


class TestDbLookupThreadSafe(unittest.TestCase):
    """Thread safety tests for DbLookup."""

    def test_concurrent_read_access(self):
        """Concurrent lookup_nik calls should not raise exceptions or corrupt data."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()
            for i in range(10):
                lookup.save_card(nomor=f"081{i:09d}", nik=f"nik{i}", kk=f"kk{i}")

            barrier = threading.Barrier(5)
            results = []

            def lookup_thread(msisdn):
                barrier.wait()
                result = lookup.lookup_nik(msisdn)
                results.append(result)

            threads = [
                threading.Thread(target=lookup_thread, args=(f"081{i:09d}",))
                for i in range(5)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            self.assertEqual(len(results), 5)
            for r in results:
                self.assertIsNotNone(r)
            lookup.close()
        finally:
            os.unlink(db_path)

    def test_concurrent_mixed_operations(self):
        """Concurrent reads and writes should not corrupt the database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            lookup = DbLookup(db_path)
            lookup.connect()
            lookup.ensure_table()

            barrier = threading.Barrier(4)
            errors = []

            def writer():
                barrier.wait()
                try:
                    for i in range(5):
                        lookup.save_card(
                            nomor=f"081{i:09d}",
                            nik=f"nik{i}",
                            kk=f"kk{i}",
                        )
                except Exception as e:
                    errors.append(e)

            def reader():
                barrier.wait()
                try:
                    for i in range(5):
                        lookup.lookup_nik(f"081{i:09d}")
                except Exception as e:
                    errors.append(e)

            threads = [
                threading.Thread(target=writer),
                threading.Thread(target=writer),
                threading.Thread(target=reader),
                threading.Thread(target=reader),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            self.assertEqual(errors, [])
            lookup.close()
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
