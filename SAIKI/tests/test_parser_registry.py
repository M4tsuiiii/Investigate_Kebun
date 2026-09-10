"""Tests for worker.parser_registry — ParserRegistry.

ParserRegistry stores and retrieves parser functions.
Pre-registers 10 built-in parsers on init.
"""

import unittest

from worker.parser_registry import ParserRegistry


class TestParserRegistryDefaults(unittest.TestCase):
    """Test pre-registered parsers."""

    def test_default_parsers_registered(self) -> None:
        reg = ParserRegistry()
        names = reg.list_all()
        self.assertEqual(len(names), 10)
        self.assertIn("parse_cnum", names)
        self.assertIn("extract_number_from_ussd", names)
        self.assertIn("extract_grace_date", names)
        self.assertIn("classify_card_status_from_grace", names)
        self.assertIn("extract_nik", names)
        self.assertIn("extract_kk", names)
        self.assertIn("classify_injection_response", names)
        self.assertIn("verify_grace_response", names)
        self.assertIn("check_modem", names)
        self.assertIn("parse_cpin_response", names)

    def test_get_returns_callable(self) -> None:
        reg = ParserRegistry()
        parser = reg.get("extract_nik")
        self.assertIsNotNone(parser)
        self.assertTrue(callable(parser))

    def test_get_returns_none_for_unknown(self) -> None:
        reg = ParserRegistry()
        self.assertIsNone(reg.get("nonexistent"))


class TestParserRegistryRegistration(unittest.TestCase):
    """Test register and parse."""

    def test_register_new_parser(self) -> None:
        reg = ParserRegistry()
        custom = lambda raw: {"custom": True}
        reg.register("custom_parser", custom)
        self.assertIn("custom_parser", reg.list_all())

    def test_parse_executes_parser(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("check_modem", "")
        self.assertEqual(result, {"modem_online": True})

    def test_parse_unknown_returns_error(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("nonexistent", "raw")
        self.assertIn("error", result)
        self.assertIn("Unknown parser", result["error"])

    def test_parse_handles_exception(self) -> None:
        reg = ParserRegistry()

        def bad_parser(raw):
            raise ValueError("bad")

        reg.register("bad", bad_parser)
        result = reg.parse("bad", "raw")
        self.assertIn("error", result)
        self.assertIn("Parser error", result["error"])


class TestParserRegistryParse(unittest.TestCase):
    """Test parse method with built-in parsers."""

    def test_parse_parse_cnum(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("parse_cnum", '+CNUM: "","081234567890",129')
        self.assertEqual(result["number"], "081234567890")

    def test_parse_parse_cnum_empty(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("parse_cnum", "")
        self.assertIsNone(result["number"])

    def test_parse_extract_nik(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("extract_nik", "Nomor IM3 kamu telah terdaftar dengan NIK : 3175055412345678")
        self.assertEqual(result["nik"], "3175055412345678")

    def test_parse_extract_grace_date(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("extract_grace_date", "Good Morning, Your number 085861112222, Balance Rp.0 Active 24-08-2026")
        self.assertEqual(result["grace_date"], "24-08-2026")

    def test_parse_classify_injection_response_hangus(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("classify_injection_response", "Permintaan kamu sedang di proses")
        self.assertTrue(result["injected"])
        self.assertTrue(result["provisional"])
        self.assertEqual(result["card_status"], "HANGUS")

    def test_parse_classify_injection_response_tenggang(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("classify_injection_response", "Nomor 085861112222 sedang dalam masa tenggang")
        self.assertTrue(result["injected"])
        self.assertFalse(result["provisional"])
        self.assertEqual(result["card_status"], "TENGGANG")


if __name__ == "__main__":
    unittest.main()
