"""Tests for worker.skills.cek_kk — CekKkSkill.

CekKkSkill checks KK from cache/DB/Telegram (NOT USSD).
Commands and parsers come from CommandRegistry and ParserRegistry.
BUILD-C: Updated to test PhoneCache, DbCache integration.
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.cek_kk import CekKkSkill
from worker.intelligence.phone_cache import PhoneCache
from worker.intelligence.db_cache import DbCache


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.command_type = "cache"
    profile.parser_name = "extract_kk"
    reg.get.return_value = profile
    return reg


class TestCekKkSkillSuccess(unittest.TestCase):

    def test_success_with_kk_from_phone_cache(self) -> None:
        """KK found in phone cache."""
        cache = PhoneCache()
        cache.put("081234567890", nik="3201234567890123", kk="3201234567890123", source="ussd")
        skill = CekKkSkill(command_registry=_mock_command_registry(), phone_cache=cache)
        result = skill.execute("COM3", nomor="081234567890", nik="3201234567890123")
        self.assertTrue(result.success)
        self.assertEqual(result.data["kk"], "3201234567890123")
        self.assertEqual(result.data["source"], "phone_cache")

    def test_success_with_kk_from_db_cache(self) -> None:
        """KK found in DB cache (not in phone cache)."""
        db_cache = MagicMock(spec=DbCache)
        db_cache.lookup_kk.return_value = "3201234567890123"
        skill = CekKkSkill(command_registry=_mock_command_registry(), db_cache=db_cache)
        result = skill.execute("COM3", nomor="081234567890", nik="3201234567890123")
        self.assertTrue(result.success)
        self.assertEqual(result.data["kk"], "3201234567890123")
        self.assertEqual(result.data["source"], "db_cache")

    def test_returns_nik_and_nomor(self) -> None:
        """Result includes nik and nomor from kwargs."""
        cache = PhoneCache()
        cache.put("081234567890", nik="3201234567890123", kk="3201234567890123")
        skill = CekKkSkill(command_registry=_mock_command_registry(), phone_cache=cache)
        result = skill.execute("COM3", nomor="081234567890", nik="3201234567890123")
        self.assertEqual(result.data["nik"], "3201234567890123")
        self.assertEqual(result.data["nomor"], "081234567890")


class TestCekKkSkillFailure(unittest.TestCase):

    def test_failure_when_no_kk(self) -> None:
        skill = CekKkSkill(command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("no_kk_found", result.error)

    def test_failure_when_no_nik(self) -> None:
        """No NIK provided, no cache hit."""
        skill = CekKkSkill(command_registry=_mock_command_registry())
        result = skill.execute("COM3", nomor="081234567890")
        self.assertFalse(result.success)


class TestCekKkSkillName(unittest.TestCase):

    def test_skill_name_is_cek_kk(self) -> None:
        skill = CekKkSkill()
        self.assertEqual(skill.name, "cek_kk")

    def test_description_not_empty(self) -> None:
        skill = CekKkSkill()
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
