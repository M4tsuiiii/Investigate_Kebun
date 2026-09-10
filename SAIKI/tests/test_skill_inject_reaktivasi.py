"""Tests for worker.skills.inject_reaktivasi — InjectReaktivasiSkill.

InjectReaktivasiSkill sends reactivation command via USSD.
Commands and parsers come from CommandRegistry and ParserRegistry.
Uses template: *888*89*1*{NIK}*{KK}#
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.inject_reaktivasi import InjectReaktivasiSkill


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.ussd_code = ""
    profile.ussd_template = "*888*89*1*{NIK}*{KK}#"
    profile.parser_name = "classify_injection_response"
    profile.timeout = 30.0
    reg.get.return_value = profile
    reg.get_ussd_code.return_value = "*888*89*1*1234567890123456*1234567890123456#"
    return reg


def _mock_parser_registry():
    reg = MagicMock()
    reg.parse.return_value = {"injected": True, "provisional": True, "card_status": "HANGUS"}
    return reg


class TestInjectReaktivasiSkillSuccess(unittest.TestCase):

    def test_success_when_injected(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Permintaan kamu sedang di proses"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime,
                                      command_registry=_mock_command_registry(),
                                      parser_registry=_mock_parser_registry())
        result = skill.execute("COM3", NIK="1234567890123456", KK="1234567890123456")
        self.assertTrue(result.success)

    def test_returns_injected(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Permintaan kamu sedang di proses"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime,
                                      command_registry=_mock_command_registry(),
                                      parser_registry=_mock_parser_registry())
        result = skill.execute("COM3", NIK="1234567890123456", KK="1234567890123456")
        self.assertTrue(result.data["injected"])

    def test_returns_provisional(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Permintaan kamu sedang di proses"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime,
                                      command_registry=_mock_command_registry(),
                                      parser_registry=_mock_parser_registry())
        result = skill.execute("COM3", NIK="1234567890123456", KK="1234567890123456")
        self.assertTrue(result.data["provisional"])


class TestInjectReaktivasiSkillFailure(unittest.TestCase):

    def test_failure_when_empty_response(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = ""
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime,
                                      command_registry=_mock_command_registry())
        result = skill.execute("COM3", NIK="1234567890123456", KK="1234567890123456")
        self.assertFalse(result.success)
        self.assertIn("Empty response", result.error)

    def test_failure_when_no_ussd_runtime(self) -> None:
        skill = InjectReaktivasiSkill(ussd_runtime=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No USSD runtime available")


class TestInjectReaktivasiSkillName(unittest.TestCase):

    def test_skill_name_is_inject_reaktivasi(self) -> None:
        mock_runtime = MagicMock()
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        self.assertEqual(skill.name, "inject_reaktivasi")

    def test_description_not_empty(self) -> None:
        mock_runtime = MagicMock()
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
