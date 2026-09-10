"""Tests for worker.skills.cek_nomor — CekNomorSkill.

CekNomorSkill retrieves SIM phone number via AT+CNUM with USSD fallback.
Commands and parsers come from CommandRegistry and ParserRegistry.
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.cek_nomor import CekNomorSkill


def _mock_at_response(*, success: bool = True, raw: str = "OK") -> MagicMock:
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.at_command = "AT+CNUM"
    profile.ussd_code = ""
    profile.parser_name = "parse_cnum"
    profile.timeout = 5.0
    reg.get.return_value = profile
    return reg


def _mock_parser_registry():
    reg = MagicMock()
    reg.parse.return_value = {"number": "081234567890"}
    return reg


class TestCekNomorSkillSuccess(unittest.TestCase):

    def test_success_when_number_found(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True, raw='+CNUM: "","081234567890",129')
        skill = CekNomorSkill(at_client=mock_client,
                              command_registry=_mock_command_registry(),
                              parser_registry=_mock_parser_registry())
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_modem_responsive_true(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True, raw='+CNUM: "","081234567890",129')
        skill = CekNomorSkill(at_client=mock_client,
                              command_registry=_mock_command_registry(),
                              parser_registry=_mock_parser_registry())
        result = skill.execute("COM3")
        self.assertTrue(result.data["modem_responsive"])

    def test_returns_number(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True, raw='+CNUM: "","081234567890",129')
        skill = CekNomorSkill(at_client=mock_client,
                              command_registry=_mock_command_registry(),
                              parser_registry=_mock_parser_registry())
        result = skill.execute("COM3")
        self.assertEqual(result.data["number"], "081234567890")

    def test_skill_name_is_cek_nomor(self) -> None:
        mock_client = MagicMock()
        skill = CekNomorSkill(at_client=mock_client)
        self.assertEqual(skill.name, "cek_nomor")

    def test_description_not_empty(self) -> None:
        mock_client = MagicMock()
        skill = CekNomorSkill(at_client=mock_client)
        self.assertTrue(len(skill.description) > 0)


class TestCekNomorSkillFailure(unittest.TestCase):

    def test_failure_when_no_at_client(self) -> None:
        skill = CekNomorSkill(at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No AT client available")


class TestCekNomorSkillTimeout(unittest.TestCase):

    def test_custom_timeout_passed(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        skill = CekNomorSkill(at_client=mock_client,
                              command_registry=_mock_command_registry(),
                              parser_registry=_mock_parser_registry())
        skill.execute("COM3", timeout=10.0)
        mock_client.send_command.assert_called_once_with("AT+CNUM", timeout=10.0)


if __name__ == "__main__":
    unittest.main()
