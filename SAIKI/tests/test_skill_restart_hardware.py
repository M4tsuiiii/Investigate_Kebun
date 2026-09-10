"""Tests for worker.skills.restart_hardware — RestartHardwareSkill.

RestartHardwareSkill restarts modem hardware via ATZ command.
Commands and parsers come from CommandRegistry and ParserRegistry.
"""

import unittest
from unittest.mock import MagicMock, patch

from worker.skills.restart_hardware import RestartHardwareSkill


def _mock_at_response(*, success: bool = True, raw: str = "OK") -> MagicMock:
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


def _mock_command_registry():
    reg = MagicMock()
    profile = MagicMock()
    profile.at_command = "ATZ"
    profile.parser_name = "check_modem"
    profile.timeout = 5.0
    reg.get.return_value = profile
    return reg


class TestRestartHardwareSkillSuccess(unittest.TestCase):

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_success_when_modem_comes_back(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client,
                                     command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_returns_modem_online_true(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client,
                                     command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertTrue(result.data["modem_online"])

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_returns_restart_sent_true(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client,
                                     command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertTrue(result.data["restart_sent"])

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_sends_atz_command(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client,
                                     command_registry=_mock_command_registry())
        skill.execute("COM3")
        mock_client.send_command.assert_called_once_with("ATZ", timeout=5.0)


class TestRestartHardwareSkillFailure(unittest.TestCase):

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_failure_when_modem_offline(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = False
        skill = RestartHardwareSkill(at_client=mock_client,
                                     command_registry=_mock_command_registry())
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Modem did not come back online", result.error)

    def test_failure_when_no_at_client(self) -> None:
        skill = RestartHardwareSkill(at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No AT client available")


class TestRestartHardwareSkillTiming(unittest.TestCase):

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_custom_wait_seconds(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client,
                                     command_registry=_mock_command_registry())
        skill.execute("COM3", wait_seconds=25.0)
        mock_sleep.assert_called_once_with(25.0)

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_default_wait_seconds(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client,
                                     command_registry=_mock_command_registry())
        skill.execute("COM3")
        mock_sleep.assert_called_once_with(15.0)


class TestRestartHardwareSkillName(unittest.TestCase):

    def test_skill_name_is_restart_hardware(self) -> None:
        mock_client = MagicMock()
        skill = RestartHardwareSkill(at_client=mock_client)
        self.assertEqual(skill.name, "restart_hardware")

    def test_description_not_empty(self) -> None:
        mock_client = MagicMock()
        skill = RestartHardwareSkill(at_client=mock_client)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
