"""Tests for worker.skills.inject_reaktivasi — InjectReaktivasiSkill.

InjectReaktivasiSkill sends reactivation command via USSD.
Input: port, ussd_code (default "*185#"), timeout (default 30.0)
Output: raw_response (str), injected (bool), ussd_code (str)
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.inject_reaktivasi import InjectReaktivasiSkill


class TestInjectReaktivasiSkillSuccess(unittest.TestCase):
    """Test InjectReaktivasiSkill success paths."""

    def test_success_when_injected(self) -> None:
        """USSD dial returns non-empty text → skill succeeds."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Reaktivasi berhasil"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_raw_response(self) -> None:
        """data['raw_response'] should carry the raw USSD response."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Reaktivasi berhasil"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["raw_response"], "Reaktivasi berhasil")

    def test_returns_injected_true(self) -> None:
        """data['injected'] should be True when response is non-empty."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Reaktivasi berhasil"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertTrue(result.data["injected"])

    def test_returns_ussd_code(self) -> None:
        """data['ussd_code'] should be the dialled code."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Reaktivasi berhasil"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["ussd_code"], "*185#")


class TestInjectReaktivasiSkillFailure(unittest.TestCase):
    """Test InjectReaktivasiSkill failure paths."""

    def test_failure_when_empty_response(self) -> None:
        """USSD dial returns empty string → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = ""
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Empty response after injection", result.error)

    def test_failure_when_dial_returns_none(self) -> None:
        """USSD dial returns None → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = None
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("USSD dial failed", result.error)

    def test_failure_when_no_ussd_runtime(self) -> None:
        """ussd_runtime=None → skill fails with missing dependency."""
        skill = InjectReaktivasiSkill(ussd_runtime=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No USSD runtime available")

    def test_failure_when_response_is_whitespace(self) -> None:
        """USSD dial returns whitespace-only string → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "   "
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Empty response after injection", result.error)


class TestInjectReaktivasiSkillCustomCode(unittest.TestCase):
    """Test InjectReaktivasiSkill custom USSD code handling."""

    def test_custom_ussd_code(self) -> None:
        """Custom ussd_code kwarg should be forwarded to dial."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "OK"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        skill.execute("COM3", ussd_code="*123#")
        mock_runtime.dial.assert_called_once_with("*123#", timeout=30.0)

    def test_custom_ussd_code_in_output(self) -> None:
        """data['ussd_code'] should reflect the custom code used."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "OK"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3", ussd_code="*123#")
        self.assertEqual(result.data["ussd_code"], "*123#")


class TestInjectReaktivasiSkillTimeout(unittest.TestCase):
    """Test InjectReaktivasiSkill timeout handling."""

    def test_custom_timeout_passed(self) -> None:
        """Custom timeout kwarg should be forwarded to dial."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "OK"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        skill.execute("COM3", timeout=15.0)
        mock_runtime.dial.assert_called_once_with("*185#", timeout=15.0)

    def test_default_timeout_is_30(self) -> None:
        """Default timeout should be 30.0 seconds."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "OK"
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        skill.execute("COM3")
        mock_runtime.dial.assert_called_once_with("*185#", timeout=30.0)


class TestInjectReaktivasiSkillName(unittest.TestCase):
    """Test InjectReaktivasiSkill identity."""

    def test_skill_name_is_inject_reaktivasi(self) -> None:
        """name property should return 'inject_reaktivasi'."""
        mock_runtime = MagicMock()
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        self.assertEqual(skill.name, "inject_reaktivasi")

    def test_description_not_empty(self) -> None:
        """description should be a non-empty string."""
        mock_runtime = MagicMock()
        skill = InjectReaktivasiSkill(ussd_runtime=mock_runtime)
        self.assertIsInstance(skill.description, str)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
