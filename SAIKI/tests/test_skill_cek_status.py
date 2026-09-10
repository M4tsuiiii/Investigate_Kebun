"""Tests for worker.skills.cek_status — CekStatusSkill.

CekStatusSkill checks SIM/CPIN status via AT+CPIN? command.
Input: port, timeout (default 3.0)
Output: cpin_state (str), raw_response (str), sim_ready (bool)

Uses parse_cpin_response to classify the AT+CPIN? response.
"""

import unittest
from unittest.mock import MagicMock, patch

from worker.skills.cek_status import CekStatusSkill
from app.domain.enums import CpinState


def _mock_at_response(*, success: bool = True, raw: str = "+CPIN: READY") -> MagicMock:
    """Create a mock AT response with success and raw attributes."""
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


class TestCekStatusSkillSuccess(unittest.TestCase):
    """Test CekStatusSkill success paths."""

    @patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.READY)
    def test_success_when_ready(self, mock_parse: MagicMock) -> None:
        """CPIN READY → skill succeeds."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="+CPIN: READY")
        skill = CekStatusSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    @patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.READY)
    def test_returns_sim_ready_true_when_ready(self, mock_parse: MagicMock) -> None:
        """data['sim_ready'] should be True when CPIN is READY."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="+CPIN: READY")
        skill = CekStatusSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.data["sim_ready"])

    @patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.READY)
    def test_returns_cpin_state_value(self, mock_parse: MagicMock) -> None:
        """data['cpin_state'] should be the CpinState enum value."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="+CPIN: READY")
        skill = CekStatusSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertEqual(result.data["cpin_state"], "READY")


class TestCekStatusSkillFailure(unittest.TestCase):
    """Test CekStatusSkill failure paths."""

    @patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.NOT_INSERTED)
    def test_failure_when_not_inserted(self, mock_parse: MagicMock) -> None:
        """CPIN NOT_INSERTED → skill fails."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="SIM NOT INSERTED")
        skill = CekStatusSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("SIM not inserted", result.error)

    @patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.PIN_REQUIRED)
    def test_failure_when_pin_required(self, mock_parse: MagicMock) -> None:
        """CPIN PIN_REQUIRED → skill fails."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="SIM PIN")
        skill = CekStatusSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("SIM PIN required", result.error)

    @patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.NOT_READY)
    def test_failure_when_not_ready(self, mock_parse: MagicMock) -> None:
        """CPIN NOT_READY → skill fails."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="NOT READY")
        skill = CekStatusSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("SIM not ready", result.error)

    def test_failure_when_no_at_client(self) -> None:
        """at_client=None → skill fails with missing dependency."""
        skill = CekStatusSkill(at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No AT client available")

    @patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.NOT_INSERTED)
    def test_returns_empty_data_on_failure(self, mock_parse: MagicMock) -> None:
        """data should be empty when CPIN is not READY (failure path)."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response(raw="SIM NOT INSERTED")
        skill = CekStatusSkill(at_client=mock_client)
        result = skill.execute("COM3")
        self.assertEqual(result.data, {})


class TestCekStatusSkillTimeout(unittest.TestCase):
    """Test CekStatusSkill timeout handling."""

    def test_custom_timeout_passed(self) -> None:
        """Custom timeout kwarg should be forwarded to send_command."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        with patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.READY):
            skill = CekStatusSkill(at_client=mock_client)
            skill.execute("COM3", timeout=10.0)
        mock_client.send_command.assert_called_once_with("AT+CPIN?", timeout=10.0)

    @patch("worker.skills.cek_status.CPIN_POLL_TIMEOUT", 5.0)
    def test_default_timeout_uses_constant(self) -> None:
        """Default timeout should come from CPIN_POLL_TIMEOUT constant."""
        mock_client = MagicMock()
        mock_client.send_command.return_value = _mock_at_response()
        with patch("worker.skills.cek_status.parse_cpin_response", return_value=CpinState.READY):
            skill = CekStatusSkill(at_client=mock_client)
            skill.execute("COM3")
        mock_client.send_command.assert_called_once_with("AT+CPIN?", timeout=5.0)


class TestCekStatusSkillName(unittest.TestCase):
    """Test CekStatusSkill identity."""

    def test_skill_name_is_cek_status(self) -> None:
        """name property should return 'cek_status'."""
        mock_client = MagicMock()
        skill = CekStatusSkill(at_client=mock_client)
        self.assertEqual(skill.name, "cek_status")

    def test_description_not_empty(self) -> None:
        """description should be a non-empty string."""
        mock_client = MagicMock()
        skill = CekStatusSkill(at_client=mock_client)
        self.assertIsInstance(skill.description, str)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
