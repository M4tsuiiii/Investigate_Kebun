"""Tests for worker.parser_registry — Individual parser functions.

Tests each parser function directly for correctness.
"""

import unittest
from datetime import date, timedelta

from worker.parser_registry import (
    parse_cnum,
    extract_number_from_ussd,
    extract_grace_date,
    classify_card_status_from_grace,
    extract_nik,
    extract_kk,
    classify_injection_response,
    verify_grace_response,
    check_modem,
    parse_cpin_response_wrapper,
)


class TestParseCnum(unittest.TestCase):
    """Test parse_cnum parser."""

    def test_valid_cnum(self) -> None:
        result = parse_cnum('+CNUM: "","081234567890",129')
        self.assertEqual(result["number"], "081234567890")

    def test_empty_response(self) -> None:
        result = parse_cnum("")
        self.assertIsNone(result["number"])

    def test_no_match(self) -> None:
        result = parse_cnum("OK")
        self.assertIsNone(result["number"])

    def test_none_input(self) -> None:
        result = parse_cnum(None)
        self.assertIsNone(result["number"])


class TestExtractNumberFromUSSD(unittest.TestCase):
    """Test extract_number_from_ussd parser."""

    def test_indonesian_number(self) -> None:
        result = extract_number_from_ussd("Your number is 081234567890")
        self.assertEqual(result["number"], "081234567890")

    def test_international_number(self) -> None:
        result = extract_number_from_ussd("Number: +6281234567890")
        self.assertEqual(result["number"], "+6281234567890")

    def test_empty_response(self) -> None:
        result = extract_number_from_ussd("")
        self.assertIsNone(result["number"])

    def test_no_number(self) -> None:
        result = extract_number_from_ussd("No number here")
        self.assertIsNone(result["number"])


class TestExtractGraceDate(unittest.TestCase):
    """Test extract_grace_date parser."""

    def test_valid_grace_date(self) -> None:
        result = extract_grace_date("Good Morning, Your number 085861112222, Balance Rp.0 Active 24-08-2026")
        self.assertEqual(result["grace_date"], "24-08-2026")

    def test_empty_response(self) -> None:
        result = extract_grace_date("")
        self.assertIsNone(result["grace_date"])

    def test_no_date(self) -> None:
        result = extract_grace_date("No date here")
        self.assertIsNone(result["grace_date"])


class TestClassifyCardStatusFromGrace(unittest.TestCase):
    """Test classify_card_status_from_grace parser."""

    def test_aktif_card(self) -> None:
        future_date = date.today() + timedelta(days=30)
        raw = f"Active {future_date.strftime('%d-%m-%Y')}"
        result = classify_card_status_from_grace(raw)
        self.assertEqual(result["card_status"], "AKTIF")
        self.assertGreater(result["masa_aktif_days"], 0)

    def test_tenggang_card(self) -> None:
        tenggang_date = date.today() + timedelta(days=-15)
        raw = f"Active {tenggang_date.strftime('%d-%m-%Y')}"
        result = classify_card_status_from_grace(raw)
        self.assertEqual(result["card_status"], "TENGGANG")
        self.assertLessEqual(result["masa_aktif_days"], 0)

    def test_hangus_card(self) -> None:
        hangus_date = date.today() + timedelta(days=-60)
        raw = f"Active {hangus_date.strftime('%d-%m-%Y')}"
        result = classify_card_status_from_grace(raw)
        self.assertEqual(result["card_status"], "HANGUS")

    def test_no_date(self) -> None:
        result = classify_card_status_from_grace("No date here")
        self.assertEqual(result["card_status"], "UNKNOWN")

    def test_invalid_date_format(self) -> None:
        result = classify_card_status_from_grace("Active 2026/08/24")
        self.assertEqual(result["card_status"], "UNKNOWN")


class TestExtractNik(unittest.TestCase):
    """Test extract_nik parser."""

    def test_valid_nik(self) -> None:
        result = extract_nik("Nomor IM3 kamu telah terdaftar dengan NIK : 3175055412345678")
        self.assertEqual(result["nik"], "3175055412345678")

    def test_empty_response(self) -> None:
        result = extract_nik("")
        self.assertIsNone(result["nik"])

    def test_no_nik(self) -> None:
        result = extract_nik("No NIK here")
        self.assertIsNone(result["nik"])


class TestExtractKk(unittest.TestCase):
    """Test extract_kk parser."""

    def test_valid_kk(self) -> None:
        result = extract_kk("KK : 3201234567890123")
        self.assertEqual(result["kk"], "3201234567890123")
        self.assertEqual(result["source"], "ussd")

    def test_empty_response(self) -> None:
        result = extract_kk("")
        self.assertIsNone(result["kk"])
        self.assertEqual(result["source"], "none")


class TestClassifyInjectionResponse(unittest.TestCase):
    """Test classify_injection_response parser."""

    def test_hangus_provisional(self) -> None:
        result = classify_injection_response("Permintaan kamu sedang di proses")
        self.assertTrue(result["injected"])
        self.assertTrue(result["provisional"])
        self.assertEqual(result["card_status"], "HANGUS")

    def test_tenggang_direct(self) -> None:
        result = classify_injection_response("Nomor 085861112222 sedang dalam masa tenggang")
        self.assertTrue(result["injected"])
        self.assertFalse(result["provisional"])
        self.assertEqual(result["card_status"], "TENGGANG")

    def test_aktif_failed(self) -> None:
        result = classify_injection_response("Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus")
        self.assertFalse(result["injected"])
        self.assertFalse(result["provisional"])
        self.assertEqual(result["card_status"], "AKTIF")

    def test_empty_response(self) -> None:
        result = classify_injection_response("")
        self.assertFalse(result["injected"])

    def test_unknown_response(self) -> None:
        result = classify_injection_response("Something else")
        self.assertFalse(result["injected"])
        self.assertEqual(result["card_status"], "unknown")


class TestVerifyGraceResponse(unittest.TestCase):
    """Test verify_grace_response parser."""

    def test_valid_response(self) -> None:
        future_date = date.today() + timedelta(days=30)
        raw = f"Good Morning, Your number 085861112222, Balance Rp.0 Active {future_date.strftime('%d-%m-%Y')}"
        result = verify_grace_response(raw)
        self.assertEqual(result["grace_date"], future_date.strftime("%d-%m-%Y"))
        self.assertEqual(result["card_status"], "AKTIF")

    def test_empty_response(self) -> None:
        result = verify_grace_response("")
        self.assertIsNone(result["grace_date"])
        self.assertEqual(result["card_status"], "UNKNOWN")


class TestCheckModem(unittest.TestCase):
    """Test check_modem parser."""

    def test_always_online(self) -> None:
        result = check_modem("")
        self.assertTrue(result["modem_online"])

    def test_default_parameter(self) -> None:
        result = check_modem()
        self.assertTrue(result["modem_online"])


class TestParseCpinResponseWrapper(unittest.TestCase):
    """Test parse_cpin_response_wrapper parser."""

    def test_ready(self) -> None:
        result = parse_cpin_response_wrapper("+CPIN: READY")
        self.assertEqual(result["cpin_state"], "READY")

    def test_not_inserted(self) -> None:
        result = parse_cpin_response_wrapper("+CME ERROR: 10")
        # Domain parser maps +CME ERROR: 10 to NOT_READY or NOT_INSERTED
        self.assertIn(result["cpin_state"], ("NOT_INSERTED", "NOT_READY"))


if __name__ == "__main__":
    unittest.main()
