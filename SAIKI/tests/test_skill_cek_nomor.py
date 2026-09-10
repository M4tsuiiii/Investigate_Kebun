"""Tests for worker.skills.cek_nomor — CekNomorSkill.

CekNomorSkill verifies modem responsiveness by sending AT command.
Input: port, timeout (default 3.0)
Output: modem_responsive (bool), raw_response (str)
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.cek_nomor import CekNomorSkill


def _mock_at_response(*, success: bool = True, raw: str = "OK") -> MagicMock:
    """Create a mock AT response with success and raw attributes."""
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


class TestCekNomorSkillSuccess(unittest.TestCase):
    """Test CekNomorSkill success paths."""

    def test_success_when_modem_responsive(self) -> None:
        """AT command returns OK → skill succeeds."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True, raw="OK")
        skill = CekNomorSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_modem_responsive_true(self) -> None:
        """data['modem_responsive'] should be True when AT returns OK."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True, raw="OK")
        skill = CekNomorSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.data["modem_responsive"])

    def test_returns_raw_response(self) -> None:
        """data['raw_response'] should carry the raw AT response string."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=True, raw="OK")
        skill = CekNomorSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertEqual(result.data["raw_response"], "OK")

    def test_skill_name_is_cek_nomor(self) -> None:
        """skill_name should be 'cek_nomor'."""
        mock_client = MagicMock()
        skill = CekNomorSkill(at_client=mock_client)
        self.assertEqual(skill.name, "cek_nomor")

    def test_description_not_empty(self) -> None:
        """description should be a non-empty string."""
        mock_client = MagicMock()
        skill = CekNomorSkill(at_client=mock_client)
        self.assertIsInstance(skill.description, str)
        self.assertTrue(len(skill.description) > 0)


class TestCekNomorSkillFailure(unittest.TestCase):
    """Test CekNomorSkill failure paths."""

    def test_failure_when_modem_not_responsive(self) -> None:
        """AT command returns error → skill fails."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=False, raw="ERROR")
        skill = CekNomorSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Modem not responsive", result.error)

    def test_failure_when_no_at_client(self) -> None:
        """at_client=None → skill fails with missing dependency."""
        skill = CekNomorSkill(at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No AT client available")

    def test_returns_empty_data_on_failure(self) -> None:
        """data should be empty when skill fails (failure path does not populate data)."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(success=False, raw="ERROR")
        skill = CekNomorSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertEqual(result.data, {})


class TestCekNomorSkillTimeout(unittest.TestCase):
    """Test CekNomorSkill timeout handling."""

    def test_custom_timeout_passed(self) -> None:
        """Custom timeout kwarg should be forwarded to send_command."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        skill = CekNomorSkill(at_client=mock_client)
        skill.execute("COM3", timeout=10.0)
        mock_client.send_command.assert_called_once_with("AT", timeout=10.0)

    def test_default_timeout_is_3(self) -> None:
        """Default timeout should be 3.0 seconds."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        skill = CekNomorSkill(at_client=mock_client)
        skill.execute("COM3")
        mock_client.send_command.assert_called_once_with("AT", timeout=3.0)


if __name__ == "__main__":
    unittest.main()
