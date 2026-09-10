"""Tests for worker.skills.cek_status — CekStatusSkill.

CekStatusSkill checks SIM/CPIN status via AT+CPIN? command.
Commands and parsers come from CommandRegistry and ParserRegistry.
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.cek_status import CekStatusSkill
from app.domain.enums import CpinState


def _mock_at_response(*, success: bool = True, raw: str = "+CPIN: READY") -> MagicMock:
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.at_command = "AT+CPIN?"
    profile.parser_name = "parse_cpin_response"
    profile.timeout = 3.0
    reg.get.return_value = profile
    return reg


def _mock_parser_registry(cpin_state="READY"):
    reg = MagicMock()
    reg.parse.return_value = {"cpin_state": cpin_state}
    return reg


class TestCekStatusSkillSuccess(unittest.TestCase):

    def test_success_when_ready(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="+CPIN: READY")
        skill = CekStatusSkill(at_client=mock_client,
                               command_registry=_mock_command_registry(),
                               parser_registry=_mock_parser_registry("READY"))
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_sim_ready_true_when_ready(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="+CPIN: READY")
        skill = CekStatusSkill(at_client=mock_client,
                               command_registry=_mock_command_registry(),
                               parser_registry=_mock_parser_registry("READY"))
        result = skill.execute("COM3")
        self.assertTrue(result.data["sim_ready"])

    def test_returns_cpin_state_value(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="+CPIN: READY")
        skill = CekStatusSkill(at_client=mock_client,
                               command_registry=_mock_command_registry(),
                               parser_registry=_mock_parser_registry("READY"))
        result = skill.execute("COM3")
        self.assertEqual(result.data["cpin_state"], "READY")


class TestCekStatusSkillFailure(unittest.TestCase):

    def test_failure_when_not_inserted(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="NOT INSERTED")
        skill = CekStatusSkill(at_client=mock_client,
                               command_registry=_mock_command_registry(),
                               parser_registry=_mock_parser_registry("NOT_INSERTED"))
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("SIM not inserted", result.error)

    def test_failure_when_pin_required(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="SIM PIN")
        skill = CekStatusSkill(at_client=mock_client,
                               command_registry=_mock_command_registry(),
                               parser_registry=_mock_parser_registry("PIN_REQUIRED"))
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("SIM PIN required", result.error)

    def test_failure_when_no_at_client(self) -> None:
        skill = CekStatusSkill(at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No AT client available")


class TestCekStatusSkillTimeout(unittest.TestCase):

    def test_custom_timeout_passed(self) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        skill = CekStatusSkill(at_client=mock_client,
                               command_registry=_mock_command_registry(),
                               parser_registry=_mock_parser_registry("READY"))
        skill.execute("COM3", timeout=10.0)
        mock_client.send_command.assert_called_once_with("AT+CPIN?", timeout=10.0)


class TestCekStatusSkillName(unittest.TestCase):

    def test_skill_name_is_cek_status(self) -> None:
        mock_client = MagicMock()
        skill = CekStatusSkill(at_client=mock_client)
        self.assertEqual(skill.name, "cek_status")

    def test_description_not_empty(self) -> None:
        mock_client = MagicMock()
        skill = CekStatusSkill(at_client=mock_client)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
