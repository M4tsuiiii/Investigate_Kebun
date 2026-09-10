"""Tests for worker.skills.cek_kk — CekKkSkill.

CekKkSkill checks KK from cache/DB/Telegram (NOT USSD).
Commands and parsers come from CommandRegistry and ParserRegistry.
FIX: Was testing USSD dial (wrong). Now tests cache-based retrieval.
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.cek_kk import CekKkSkill


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.command_type = "cache"
    profile.parser_name = "extract_kk"
    reg.get.return_value = profile
    return reg


class TestCekKkSkillSuccess(unittest.TestCase):

    def test_success_with_kk_from_kwargs(self) -> None:
        skill = CekKkSkill(command_registry=_mock_command_registry())
        result = skill.execute("COM3", kk="3201234567890123", kk_source="cache")
        self.assertTrue(result.success)

    def test_returns_kk(self) -> None:
        skill = CekKkSkill(command_registry=_mock_command_registry())
        result = skill.execute("COM3", kk="3201234567890123", kk_source="cache")
        self.assertEqual(result.data["kk"], "3201234567890123")

    def test_returns_source(self) -> None:
        skill = CekKkSkill(command_registry=_mock_command_registry())
        result = skill.execute("COM3", kk="3201234567890123", kk_source="database")
        self.assertEqual(result.data["source"], "database")


class TestCekKkSkillFailure(unittest.TestCase):

    def test_failure_when_no_kk(self) -> None:
        skill = CekKkSkill(command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("no_kk_found", result.error)


class TestCekKkSkillName(unittest.TestCase):

    def test_skill_name_is_cek_kk(self) -> None:
        skill = CekKkSkill()
        self.assertEqual(skill.name, "cek_kk")

    def test_description_not_empty(self) -> None:
        skill = CekKkSkill()
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
