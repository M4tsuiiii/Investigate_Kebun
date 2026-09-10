"""Tests for worker.skills.verify_grace — VerifyGraceSkill.

VerifyGraceSkill verifies card grace period via USSD *185#.
Commands and parsers come from CommandRegistry and ParserRegistry.
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.verify_grace import VerifyGraceSkill


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.ussd_code = "*185#"
    profile.parser_name = "verify_grace_response"
    profile.timeout = 30.0
    reg.get.return_value = profile
    return reg


def _mock_parser_registry(card_status="AKTIF", grace_date="24-08-2026"):
    reg = MagicMock()
    reg.parse.return_value = {"card_status": card_status, "grace_date": grace_date}
    return reg


class TestVerifyGraceSkillSuccess(unittest.TestCase):

    def test_success_when_aktif(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Good Morning, Your number 085861112222, Balance Rp.0 Active 24-08-2026"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry("AKTIF"))
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_success_when_tenggang(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: TENGGANG"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry("TENGGANG"))
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_card_status(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Active 24-08-2026"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry("AKTIF"))
        result = skill.execute("COM3")
        self.assertEqual(result.data["card_status"], "AKTIF")

    def test_returns_grace_date(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Active 24-08-2026"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry("AKTIF", "24-08-2026"))
        result = skill.execute("COM3")
        self.assertEqual(result.data["grace_date"], "24-08-2026")


class TestVerifyGraceSkillFailure(unittest.TestCase):

    def test_failure_when_hangus(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: HANGUS"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry("HANGUS"))
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("HANGUS", result.error)

    def test_failure_when_unknown_status(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "random gibberish"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry("UNKNOWN"))
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Unknown card status", result.error)

    def test_failure_when_no_ussd_runtime(self) -> None:
        skill = VerifyGraceSkill(ussd_runtime=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No USSD runtime available")

    def test_failure_when_dial_returns_none(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = None
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("USSD dial failed", result.error)


class TestVerifyGraceSkillTimeout(unittest.TestCase):

    def test_custom_timeout_passed(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Active 24-08-2026"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry())
        skill.execute("COM3", timeout=15.0)
        mock_runtime.dial.assert_called_once_with("*185#", timeout=15.0)

    def test_default_timeout_is_30(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Active 24-08-2026"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime,
                                 command_registry=_mock_command_registry(),
                                 parser_registry=_mock_parser_registry())
        skill.execute("COM3")
        mock_runtime.dial.assert_called_once_with("*185#", timeout=30.0)


class TestVerifyGraceSkillName(unittest.TestCase):

    def test_skill_name_is_verify_grace(self) -> None:
        mock_runtime = MagicMock()
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        self.assertEqual(skill.name, "verify_grace")

    def test_description_not_empty(self) -> None:
        mock_runtime = MagicMock()
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
