"""Tests for worker.skills.verify_grace — VerifyGraceSkill.

VerifyGraceSkill verifies card grace period by reading USSD response.
Input: port, timeout (default 30.0)
Output: raw_response (str), card_status (str), grace_date (str)

Uses internal classification to map USSD text to CardStatus enum.
"""

import unittest
from unittest.mock import MagicMock

from worker.skills.verify_grace import VerifyGraceSkill
from app.domain.enums import CardStatus


class TestVerifyGraceSkillSuccess(unittest.TestCase):
    """Test VerifyGraceSkill success paths."""

    def test_success_when_aktif(self) -> None:
        """USSD response contains 'aktif' → card is AKTIF → skill succeeds."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: AKTIF, masa aktif sampai 2026-12-31"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_success_when_tenggang(self) -> None:
        """USSD response contains 'tenggang' → card is TENGGANG → skill succeeds."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: TENGGANG, masa tenggang sampai 2026-10-15"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertTrue(result.success)

    def test_returns_raw_response(self) -> None:
        """data['raw_response'] should carry the full USSD response."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: AKTIF"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["raw_response"], "Status: AKTIF")

    def test_returns_card_status(self) -> None:
        """data['card_status'] should be the CardStatus enum value."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: AKTIF"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["card_status"], "AKTIF")

    def test_extracts_grace_date(self) -> None:
        """data['grace_date'] should extract date pattern from response."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: TENGGANG, masa tenggang sampai 15-10-2026"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["grace_date"], "15-10-2026")

    def test_extracts_date_yyyy_mm_dd(self) -> None:
        """data['grace_date'] should extract YYYY-MM-DD pattern."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: AKTIF, active until 2026-12-31"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["grace_date"], "2026-12-31")

    def test_extracts_date_with_slashes(self) -> None:
        """data['grace_date'] should extract DD/MM/YYYY pattern."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: AKTIF, aktif sampai 31/12/2026"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["grace_date"], "31/12/2026")


class TestVerifyGraceSkillFailure(unittest.TestCase):
    """Test VerifyGraceSkill failure paths."""

    def test_failure_when_hangus(self) -> None:
        """USSD response contains 'hangus' → card is HANGUS → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: HANGUS, nomor sudah hangus"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("HANGUS", result.error)

    def test_failure_when_unknown_status(self) -> None:
        """USSD response with no recognized keywords → UNKNOWN → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: TIDAK DIKENAL"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("Unknown card status", result.error)

    def test_failure_when_empty_response(self) -> None:
        """USSD dial returns empty string → classified as UNKNOWN → fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = ""
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)

    def test_failure_when_dial_returns_none(self) -> None:
        """USSD dial returns None → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = None
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertIn("USSD dial failed", result.error)

    def test_failure_when_no_ussd_runtime(self) -> None:
        """ussd_runtime=None → skill fails with missing dependency."""
        skill = VerifyGraceSkill(ussd_runtime=None)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No USSD runtime available")

    def test_card_status_hangus_not_in_data(self) -> None:
        """data should be empty on HANGUS failure (failure path does not populate data)."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: HANGUS"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data, {})

    def test_card_status_unknown_not_in_data(self) -> None:
        """data should be empty on UNKNOWN failure (failure path does not populate data)."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "random gibberish"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data, {})


class TestVerifyGraceSkillClassification(unittest.TestCase):
    """Test VerifyGraceSkill card status classification edge cases."""

    def test_english_active(self) -> None:
        """USSD response with 'active' → AKTIF."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Your card is active"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["card_status"], "AKTIF")
        self.assertTrue(result.success)

    def test_english_grace(self) -> None:
        """USSD response with 'grace' → TENGGANG."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Grace period until 2026-10-01"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertEqual(result.data["card_status"], "TENGGANG")
        self.assertTrue(result.success)

    def test_english_burned(self) -> None:
        """USSD response with 'burned' → HANGUS → skill fails."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Card is burned"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        result = skill.execute("COM3")
        self.assertFalse(result.success)
        self.assertEqual(result.data, {})


class TestVerifyGraceSkillTimeout(unittest.TestCase):
    """Test VerifyGraceSkill timeout handling."""

    def test_custom_timeout_passed(self) -> None:
        """Custom timeout kwarg should be forwarded to dial."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: AKTIF"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        skill.execute("COM3", timeout=15.0)
        mock_runtime.dial.assert_called_once_with("*185#", timeout=15.0)

    def test_default_timeout_is_30(self) -> None:
        """Default timeout should be 30.0 seconds."""
        mock_runtime = MagicMock()
        mock_runtime.dial.return_value = "Status: AKTIF"
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        skill.execute("COM3")
        mock_runtime.dial.assert_called_once_with("*185#", timeout=30.0)


class TestVerifyGraceSkillName(unittest.TestCase):
    """Test VerifyGraceSkill identity."""

    def test_skill_name_is_verify_grace(self) -> None:
        """name property should return 'verify_grace'."""
        mock_runtime = MagicMock()
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        self.assertEqual(skill.name, "verify_grace")

    def test_description_not_empty(self) -> None:
        """description should be a non-empty string."""
        mock_runtime = MagicMock()
        skill = VerifyGraceSkill(ussd_runtime=mock_runtime)
        self.assertIsInstance(skill.description, str)
        self.assertTrue(len(skill.description) > 0)


if __name__ == "__main__":
    unittest.main()
