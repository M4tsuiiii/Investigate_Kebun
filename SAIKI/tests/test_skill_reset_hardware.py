"""Tests for worker.skills.reset_hardware — ResetHardwareSkill.

ResetHardwareSkill performs full hardware reset cycle:
close serial → wait → reopen → check modem → detect SIM.
Input: port, wait_seconds (default 15.0)
Output: modem_online (bool), cpin_state (str), ready (bool)

Patches time.sleep and parse_cpin_response to avoid real waits/hardware.
"""

import unittest
from unittest.mock import MagicMock, patch

from worker.skills.reset_hardware import ResetHardwareSkill
from app.domain.enums import CpinState


def _mock_at_response(*, success: bool = True, raw: str = "+CPIN: READY") -> MagicMock:
    """Create a mock AT response with success and raw attributes."""
    resp = MagicMock()
    resp.success = success
    resp.raw = raw
    return resp


class TestResetHardwareSkillSuccess(unittest.TestCase):
    """Test ResetHardwareSkill success paths."""

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.READY)
    def test_success_when_ready_after_reset(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Full cycle succeeds: close → reopen → modem online → SIM READY."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response(raw="+CPIN: READY")
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.READY)
    def test_returns_modem_online(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """data['modem_online'] should be True when modem responds after reset."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertTrue(result.data["modem_online"])

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.READY)
    def test_returns_cpin_state(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """data['cpin_state'] should be the parsed CpinState value."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertEqual(result.data["cpin_state"], "READY")


class TestResetHardwareSkillFailure(unittest.TestCase):
    """Test ResetHardwareSkill failure paths."""

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    def test_failure_when_reopen_fails(self, mock_sleep: MagicMock) -> None:
        """serial.open() returns False → skill fails."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = False
        mock_client = MagicMock()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Failed to reopen serial port", result.error)

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    def test_failure_when_modem_offline(self, mock_sleep: MagicMock) -> None:
        """Modem doesn't come back after reset → skill fails."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = False
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Modem offline after reset", result.error)

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.NOT_INSERTED)
    def test_failure_when_sim_not_ready(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Modem online but SIM not READY → skill fails."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response(raw="SIM NOT INSERTED")
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("SIM not ready", result.error)

    def test_failure_when_no_serial_adapter(self) -> None:
        """serial_adapter=None → skill fails with missing dependency."""
        mock_client = MagicMock()
        skill = ResetHardwareSkill(serial_adapter=None, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("No serial adapter or AT client", result.error)

    def test_failure_when_no_at_client(self) -> None:
        """at_client=None → skill fails with missing dependency."""
        mock_serial = MagicMock()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("No serial adapter or AT client", result.error)

    def test_failure_when_both_none(self) -> None:
        """Both dependencies None → skill fails."""
        skill = ResetHardwareSkill(serial_adapter=None, at_client=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.NOT_INSERTED)
    def test_returns_empty_data_when_sim_not_ready(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """data should be empty when SIM is not READY (failure path)."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response(raw="SIM NOT INSERTED")
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        result = skill.execute("COM3")
        self.assertEqual(result.data, {})


class TestResetHardwareSkillSerialOperations(unittest.TestCase):
    """Test ResetHardwareSkill serial close/reopen sequence."""

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.READY)
    def test_closes_serial(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """serial.close() should be called during reset cycle."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        skill.execute("COM3")
        mock_serial.close.assert_called_once()

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.READY)
    def test_reopens_serial(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """serial.open() should be called after close."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        skill.execute("COM3")
        mock_serial.open.assert_called_once()


class TestResetHardwareSkillTiming(unittest.TestCase):
    """Test ResetHardwareSkill wait handling."""

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.READY)
    def test_custom_wait_seconds(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Custom wait_seconds should control the sleep duration."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        skill.execute("COM3", wait_seconds=25.0)
        mock_sleep.assert_called_once_with(25.0)

    @patch("worker.skills.reset_hardware.time.sleep", return_value=None)
    @patch("worker.skills.reset_hardware.parse_cpin_response", return_value=CpinState.READY)
    def test_default_wait_seconds(
        self, mock_parse: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Default wait_seconds should be STABILIZATION_SECONDS (15.0)."""
        mock_serial = MagicMock()
        mock_serial.open.return_value = True
        mock_client = MagicMock()
        mock_client.check_modem.return_value = True
        mock_client.send_command.return_value = _mock_at_response()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        skill.execute("COM3")
        mock_sleep.assert_called_once_with(15.0)


class TestResetHardwareSkillName(unittest.TestCase):
    """Test ResetHardwareSkill identity."""

    def test_skill_name_is_reset_hardware(self) -> None:
        """name property should return 'reset_hardware'."""
        mock_serial = MagicMock()
        mock_client = MagicMock()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        self.assertEqual(skill.name, "reset_hardware")

    def test_description_not_empty(self) -> None:
        """description should be a non-empty string."""
        mock_serial = MagicMock()
        mock_client = MagicMock()
        skill = ResetHardwareSkill(serial_adapter=mock_serial, at_client=mock_client)
        self.assertIsInstance(skill.description, str)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
