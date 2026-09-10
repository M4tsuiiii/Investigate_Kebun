"""Tests for worker.skills.cek_nik — CekNikSkill.

CekNikSkill checks NIK information by dialing USSD code *185#.
Input: port, timeout (default 30.0)
Output: raw_response (str), has_payload (bool), ussd_code (str)
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.cek_nik import CekNikSkill


class TestCekNikSkillSuccess(unittest.TestCase):
    """Test CekNikSkill success paths."""

    def test_success_with_payload(self) -> None:
        """USSD dial returns non-empty text → skill succeeds."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Data NIK: 3201xxxx"
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_raw_response(self) -> None:
        """data['raw_response'] should carry the raw USSD response."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Data NIK: 3201xxxx"
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["raw_response"], "Data NIK: 3201xxxx")

    def test_returns_has_payload_true(self) -> None:
        """data['has_payload'] should be True when response is non-empty."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Data NIK: 3201xxxx"
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertTrue(result.data["has_payload"])

    def test_returns_ussd_code(self) -> None:
        """data['ussd_code'] should be the dialled USSD code."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Data NIK: 3201xxxx"
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["ussd_code"], "*185#")


class TestCekNikSkillFailure(unittest.TestCase):
    """Test CekNikSkill failure paths."""

    def test_failure_when_empty_response(self) -> None:
        """USSD dial returns empty string → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = ""
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Empty USSD response", result.error)

    def test_failure_when_dial_returns_none(self) -> None:
        """USSD dial returns None → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = None
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "USSD dial failed")

    def test_failure_when_no_ussd_runtime(self) -> None:
        """ussd_runtime=None → skill fails with missing dependency."""
        skill = CekNikSkill(ussd_runtime=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No USSD runtime available")

    def test_failure_when_response_is_whitespace(self) -> None:
        """USSD dial returns whitespace-only string → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "   "
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Empty USSD response", result.error)


class TestCekNikSkillTimeout(unittest.TestCase):
    """Test CekNikSkill timeout handling."""

    def test_custom_timeout_passed(self) -> None:
        """Custom timeout kwarg should be forwarded to dial."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "NIK info"
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        skill.execute("COM3", timeout=15.0)
        mock_runtime.dial.assert_called_once_with("*185#", timeout=15.0)

    def test_default_timeout_is_30(self) -> None:
        """Default timeout should be 30.0 seconds."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "NIK info"
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        skill.execute("COM3")
        mock_runtime.dial.assert_called_once_with("*185#", timeout=30.0)


class TestCekNikSkillName(unittest.TestCase):
    """Test CekNikSkill identity."""

    def test_skill_name_is_cek_nik(self) -> None:
        """name property should return 'cek_nik'."""
        mock_runtime = MagicMock()
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        self.assertEqual(skill.name, "cek_nik")

    def test_description_not_empty(self) -> None:
        """description should be a non-empty string."""
        mock_runtime = MagicMock()
        skill = CekNikSkill(ussd_runtime=mock_runtime)
        self.assertIsInstance(skill.description, str)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
