"""Tests for worker.command_registry — CommandRegistry and CommandProfile.

CommandRegistry stores and retrieves command profiles.
Pre-registers 7 built-in commands on init.
"""

import unittest

from worker.command_registry import CommandProfile, CommandRegistry


class TestCommandProfile(unittest.TestCase):
    """Test CommandProfile dataclass."""

    def test_creation_with_defaults(self) -> None:
        profile = CommandProfile(name="test", command_type="at")
        self.assertEqual(profile.name, "test")
        self.assertEqual(profile.command_type, "at")
        self.assertEqual(profile.at_command, "")
        self.assertEqual(profile.ussd_code, "")
        self.assertEqual(profile.ussd_template, "")
        self.assertEqual(profile.parser_name, "")
        self.assertEqual(profile.output_fields, ())
        self.assertEqual(profile.timeout, 5.0)
        self.assertEqual(profile.description, "")

    def test_creation_with_all_fields(self) -> None:
        profile = CommandProfile(
            name="cek_nik",
            command_type="ussd",
            ussd_code="*888*4444*1#",
            parser_name="extract_nik",
            output_fields=("nik",),
            timeout=30.0,
            description="Cek NIK",
        )
        self.assertEqual(profile.name, "cek_nik")
        self.assertEqual(profile.ussd_code, "*888*4444*1#")
        self.assertEqual(profile.parser_name, "extract_nik")
        self.assertEqual(profile.output_fields, ("nik",))
        self.assertEqual(profile.timeout, 30.0)

    def test_frozen(self) -> None:
        profile = CommandProfile(name="test", command_type="at")
        with self.assertRaises(AttributeError):
            profile.name = "changed"


class TestCommandRegistryDefaults(unittest.TestCase):
    """Test pre-registered commands."""

    def test_default_commands_registered(self) -> None:
        reg = CommandRegistry()
        names = reg.list_all()
        self.assertEqual(len(names), 7)
        self.assertIn("cek_nomor", names)
        self.assertIn("cek_status", names)
        self.assertIn("cek_nik", names)
        self.assertIn("cek_kk", names)
        self.assertIn("inject_reaktivasi", names)
        self.assertIn("verify_grace", names)
        self.assertIn("restart_hardware", names)

    def test_get_returns_profile(self) -> None:
        reg = CommandRegistry()
        profile = reg.get("cek_nik")
        self.assertIsNotNone(profile)
        self.assertIsInstance(profile, CommandProfile)
        self.assertEqual(profile.name, "cek_nik")

    def test_get_returns_none_for_unknown(self) -> None:
        reg = CommandRegistry()
        self.assertIsNone(reg.get("nonexistent"))


class TestCommandRegistryRegistration(unittest.TestCase):
    """Test register and list."""

    def test_register_new_command(self) -> None:
        reg = CommandRegistry()
        profile = CommandProfile(
            name="custom",
            command_type="at",
            at_command="ATI",
        )
        reg.register(profile)
        self.assertIn("custom", reg.list_all())
        self.assertEqual(reg.get("custom").at_command, "ATI")

    def test_register_overwrites_existing(self) -> None:
        reg = CommandRegistry()
        profile = CommandProfile(
            name="cek_nik",
            command_type="ussd",
            ussd_code="*999#",
        )
        reg.register(profile)
        self.assertEqual(reg.get("cek_nik").ussd_code, "*999#")


class TestCommandRegistryGetUSSDCode(unittest.TestCase):
    """Test get_ussd_code method."""

    def test_get_ussd_code_for_ussd_command(self) -> None:
        reg = CommandRegistry()
        code = reg.get_ussd_code("cek_nik")
        self.assertEqual(code, "*888*4444*1#")

    def test_get_ussd_code_for_template_command(self) -> None:
        reg = CommandRegistry()
        code = reg.get_ussd_code("inject_reaktivasi", NIK="1234567890123456", KK="1234567890123456")
        self.assertEqual(code, "*888*89*1*1234567890123456*1234567890123456#")

    def test_get_ussd_code_for_at_command(self) -> None:
        reg = CommandRegistry()
        code = reg.get_ussd_code("cek_status")
        self.assertEqual(code, "")

    def test_get_ussd_code_for_unknown(self) -> None:
        reg = CommandRegistry()
        code = reg.get_ussd_code("nonexistent")
        self.assertEqual(code, "")

    def test_get_ussd_code_for_cache_command(self) -> None:
        reg = CommandRegistry()
        code = reg.get_ussd_code("cek_kk")
        self.assertEqual(code, "")


if __name__ == "__main__":
    unittest.main()
