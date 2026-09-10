"""Tests for worker.skills.restart_hardware — RestartHardwareSkill.

RestartHardwareSkill restarts modem hardware via ATZ command.
Input: port, wait_seconds (default 15.0), timeout (default 5.0)
Output: restart_sent (bool), modem_online (bool)

Patches time.sleep to avoid real waits.
"""

import unittest
from unittest.mock import MagicMock, patch

from worker.skills.restart_hardware import RestartHardwareSkill


def _mock_at_response(*, success: bool = True, raw: str = "OK") -> MagicMock:
    """Create a mock AT response with success and raw attributes."""
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


class TestRestartHardwareSkillSuccess(unittest.TestCase):
    """Test RestartHardwareSkill success paths."""

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_success_when_modem_comes_back(self, mock_sleep: MagicMock) -> None:
        """ATZ sent + modem back online → skill succeeds."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_returns_modem_online_true(self, mock_sleep: MagicMock) -> None:
        """data['modem_online'] should be True when modem comes back."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.data["modem_online"])

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_returns_restart_sent_true(self, mock_sleep: MagicMock) -> None:
        """data['restart_sent'] should be True when ATZ succeeds."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.data["restart_sent"])

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_sends_atz_command(self, mock_sleep: MagicMock) -> None:
        """send_command should be called with 'ATZ'."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client)
        skill.execute("COM3")
        mock_client.send_command.assert_called_once_with("ATZ", timeout=5.0)


class TestRestartHardwareSkillFailure(unittest.TestCase):
    """Test RestartHardwareSkill failure paths."""

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_failure_when_modem_offline(self, mock_sleep: MagicMock) -> None:
        """ATZ sent but modem doesn't come back → skill fails."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = False
        skill = RestartHardwareSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Modem did not come back online", result.error)

    def test_failure_when_no_at_client(self) -> None:
        """at_client=None → skill fails with missing dependency."""
        skill = RestartHardwareSkill(at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No AT client available")

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_returns_empty_data_when_offline(self, mock_sleep: MagicMock) -> None:
        """data should be empty when modem doesn't come back (failure path)."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True)
        mock_client.check_modem.return_value = False
        skill = RestartHardwareSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertEqual(result.data, {})


class TestRestartHardwareSkillTiming(unittest.TestCase):
    """Test RestartHardwareSkill wait and timeout handling."""

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_custom_wait_seconds(self, mock_sleep: MagicMock) -> None:
        """Custom wait_seconds kwarg should control the sleep duration."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client)
        skill.execute("COM3", wait_seconds=25.0)
        mock_sleep.assert_called_once_with(25.0)

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_default_wait_seconds(self, mock_sleep: MagicMock) -> None:
        """Default wait_seconds should be STABILIZATION_SECONDS (15.0)."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client)
        skill.execute("COM3")
        mock_sleep.assert_called_once_with(15.0)

    @patch("worker.skills.restart_hardware.time.sleep", return_value=None)
    def test_custom_timeout_passed(self, mock_sleep: MagicMock) -> None:
        """Custom timeout kwarg should be forwarded to send_command."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        mock_client.check_modem.return_value = True
        skill = RestartHardwareSkill(at_client=mock_client)
        skill.execute("COM3", timeout=10.0)
        mock_client.send_command.assert_called_once_with("ATZ", timeout=10.0)


class TestRestartHardwareSkillName(unittest.TestCase):
    """Test RestartHardwareSkill identity."""

    def test_skill_name_is_restart_hardware(self) -> None:
        """name property should return 'restart_hardware'."""
        mock_client = MagicMock()
        skill = RestartHardwareSkill(at_client=mock_client)
        self.assertEqual(skill.name, "restart_hardware")

    def test_description_not_empty(self) -> None:
        """description should be a non-empty string."""
        mock_client = MagicMock()
        skill = RestartHardwareSkill(at_client=mock_client)
        self.assertIsInstance(skill.description, str)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
