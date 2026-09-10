"""Tests for worker.skills.cek_nik — CekNikSkill.

CekNikSkill checks NIK via USSD *888*4444*1#.
Commands and parsers come from CommandRegistry and ParserRegistry.
FIX: Was testing *185# (wrong). Now tests *888*4444*1# (correct).
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.cek_nik import CekNikSkill


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.ussd_code = "*888*4444*1#"
    profile.parser_name = "extract_nik"
    profile.timeout = 30.0
    reg.get.return_value = profile
    return reg


def _mock_parser_registry(nik="3175055412345678"):
    reg = MagicMock()
    reg.parse.return_value = {"nik": nik}
    return reg


class TestCekNikSkillSuccess(unittest.TestCase):

    def test_success_with_payload(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Nomor IM3 kamu telah terdaftar dengan NIK : 3175055412345678"
        skill = CekNikSkill(ussd_runtime=mock_runtime,
                            command_registry=_mock_command_registry(),
                            parser_registry=_mock_parser_registry())
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_nik(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Nomor IM3 kamu telah terdaftar dengan NIK : 3175055412345678"
        skill = CekNikSkill(ussd_runtime=mock_runtime,
                            command_registry=_mock_command_registry(),
                            parser_registry=_mock_parser_registry())
        result = skill.execute("COM3")
        self.assertEqual(result.data["nik"], "3175055412345678")

    def test_returns_ussd_code_from_registry(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "NIK info"
        skill = CekNikSkill(ussd_runtime=mock_runtime,
                            command_registry=_mock_command_registry(),
                            parser_registry=_mock_parser_registry())
        result = skill.execute("COM3")
        self.assertEqual(result.data["ussd_code"], "*888*4444*1#")


class TestCekNikSkillFailure(unittest.TestCase):

    def test_failure_when_empty_response(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = ""
        skill = CekNikSkill(ussd_runtime=mock_runtime,
                            command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Empty USSD response", result.error)

    def test_failure_when_dial_returns_none(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = None
        skill = CekNikSkill(ussd_runtime=mock_runtime,
                            command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "USSD dial failed")

    def test_failure_when_no_ussd_runtime(self) -> None:
        skill = CekNikSkill(ussd_runtime=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No USSD runtime available")


class TestCekNikSkillTimeout(unittest.TestCase):

    def test_custom_timeout_passed(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "NIK info"
        skill = CekNikSkill(ussd_runtime=mock_runtime,
                            command_registry=_mock_command_registry())
        skill.execute("COM3", timeout=15.0)
        mock_runtime.dial.assert_called_once_with("*888*4444*1#", timeout=15.0)

    def test_default_timeout_is_30(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "NIK info"
        skill = CekNikSkill(ussd_runtime=mock_runtime,
                            command_registry=_mock_command_registry())
        skill.execute("COM3")
        mock_runtime.dial.assert_called_once_with("*888*4444*1#", timeout=30.0)


class TestCekNikSkillName(unittest.TestCase):

    def test_skill_name_is_cek_nik(self) -> None:
        mock_runtime = MagicMock()
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        self.assertEqual(skill.name, "cek_nik")

    def test_description_not_empty(self) -> None:
        mock_runtime = MagicMock()
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
