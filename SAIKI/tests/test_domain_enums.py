"""Tests for all SAIKI domain enums — single source of truth."""

import unittest
from enum import Enum

from app.domain.enums import (
    BusinessOutcome,
    CpinState,
    CardStatus,
    FailureCode,
    UssdClass,
    UssdIntent,
    FlowStatus,
    PortStatus,
    KkSource,
)


class TestBusinessOutcome(unittest.TestCase):
    """Test BusinessOutcome enum (I-01 canonical name)."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(BusinessOutcome.SUKSES.value, "SUKSES")
        self.assertEqual(BusinessOutcome.TENGGANG.value, "TENGGANG")
        self.assertEqual(BusinessOutcome.FAILED.value, "FAILED")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(BusinessOutcome.SUKSES, Enum))
        self.assertTrue(isinstance(BusinessOutcome.SUKSES, str))

    def test_no_duplicates(self):
        """Verify no duplicate values (single source of truth)."""
        values = [m.value for m in BusinessOutcome]
        self.assertEqual(len(values), len(set(values)))

    def test_comparison(self):
        """Verify enum comparison works."""
        self.assertEqual(BusinessOutcome.SUKSES, BusinessOutcome.SUKSES)
        self.assertNotEqual(BusinessOutcome.SUKSES, BusinessOutcome.FAILED)

    def test_str_representation(self):
        """Verify value string representation."""
        self.assertEqual(BusinessOutcome.SUKSES.value, "SUKSES")

    def test_member_count(self):
        """Verify expected member count."""
        self.assertEqual(len(BusinessOutcome), 3)


class TestCpinState(unittest.TestCase):
    """Test CpinState enum — SIM CPIN states."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(CpinState.READY.value, "READY")
        self.assertEqual(CpinState.NOT_INSERTED.value, "NOT_INSERTED")
        self.assertEqual(CpinState.PIN_REQUIRED.value, "PIN_REQUIRED")
        self.assertEqual(CpinState.NOT_READY.value, "NOT_READY")
        self.assertEqual(CpinState.UNKNOWN.value, "UNKNOWN")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(CpinState.READY, Enum))
        self.assertTrue(isinstance(CpinState.READY, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in CpinState]
        self.assertEqual(len(values), len(set(values)))

    def test_member_count(self):
        """Verify expected member count."""
        self.assertEqual(len(CpinState), 5)


class TestCardStatus(unittest.TestCase):
    """Test CardStatus enum — derived card status."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(CardStatus.AKTIF.value, "AKTIF")
        self.assertEqual(CardStatus.TENGGANG.value, "TENGGANG")
        self.assertEqual(CardStatus.HANGUS.value, "HANGUS")
        self.assertEqual(CardStatus.UNKNOWN.value, "UNKNOWN")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(CardStatus.AKTIF, Enum))
        self.assertTrue(isinstance(CardStatus.AKTIF, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in CardStatus]
        self.assertEqual(len(values), len(set(values)))


class TestFailureCode(unittest.TestCase):
    """Test FailureCode enum — failure classification."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(FailureCode.GAGAL_CEK_NIK.value, "GAGAL_CEK_NIK")
        self.assertEqual(FailureCode.GAGAL_KK.value, "GAGAL_KK")
        self.assertEqual(FailureCode.GAGAL_INJEKSI.value, "GAGAL_INJEKSI")
        self.assertEqual(FailureCode.GAGAL_VERIFIKASI.value, "GAGAL_VERIFIKASI")
        self.assertEqual(FailureCode.GAGAL.value, "GAGAL")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(FailureCode.GAGAL, Enum))
        self.assertTrue(isinstance(FailureCode.GAGAL, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in FailureCode]
        self.assertEqual(len(values), len(set(values)))

    def test_comparison(self):
        """Verify enum comparison works."""
        self.assertEqual(FailureCode.GAGAL_CEK_NIK, FailureCode.GAGAL_CEK_NIK)
        self.assertNotEqual(FailureCode.GAGAL_KK, FailureCode.GAGAL)


class TestUssdClass(unittest.TestCase):
    """Test UssdClass enum — USSD raw response classification."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(UssdClass.PAYLOAD.value, "USSD_PAYLOAD")
        self.assertEqual(UssdClass.EMPTY_PAYLOAD.value, "USSD_EMPTY_PAYLOAD")
        self.assertEqual(UssdClass.ERROR.value, "ERROR")
        self.assertEqual(UssdClass.TIMEOUT.value, "TIMEOUT")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(UssdClass.PAYLOAD, Enum))
        self.assertTrue(isinstance(UssdClass.PAYLOAD, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in UssdClass]
        self.assertEqual(len(values), len(set(values)))

    def test_member_count(self):
        """Verify expected member count."""
        self.assertEqual(len(UssdClass), 11)


class TestUssdIntent(unittest.TestCase):
    """Test UssdIntent enum — semantic intent of a USSD payload."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(UssdIntent.SUCCESS.value, "SUCCESS_MESSAGE")
        self.assertEqual(UssdIntent.REQUEST_ACCEPTED.value, "REQUEST_ACCEPTED")
        self.assertEqual(UssdIntent.MENU.value, "MENU_RESPONSE")
        self.assertEqual(UssdIntent.NUMBER_INFO.value, "NUMBER_INFO")
        self.assertEqual(UssdIntent.EMPTY.value, "EMPTY_RESPONSE")
        self.assertEqual(UssdIntent.UNKNOWN.value, "UNKNOWN")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(UssdIntent.SUCCESS, Enum))
        self.assertTrue(isinstance(UssdIntent.SUCCESS, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in UssdIntent]
        self.assertEqual(len(values), len(set(values)))


class TestFlowStatus(unittest.TestCase):
    """Test FlowStatus enum — reactivation flow progress."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(FlowStatus.STABILISASI.value, "STABILISASI")
        self.assertEqual(FlowStatus.CEK_NOMOR.value, "CEK_NOMOR")
        self.assertEqual(FlowStatus.CEK_STATUS.value, "CEK_STATUS")
        self.assertEqual(FlowStatus.CEK_NIK.value, "CEK_NIK")
        self.assertEqual(FlowStatus.CEK_KK.value, "CEK_KK")
        self.assertEqual(FlowStatus.INJECTING.value, "INJECTING")
        self.assertEqual(FlowStatus.VERIFYING.value, "VERIFYING")
        self.assertEqual(FlowStatus.DONE.value, "DONE")
        self.assertEqual(FlowStatus.GAGAL.value, "GAGAL")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(FlowStatus.STABILISASI, Enum))
        self.assertTrue(isinstance(FlowStatus.STABILISASI, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in FlowStatus]
        self.assertEqual(len(values), len(set(values)))

    def test_member_count(self):
        """Verify expected member count."""
        self.assertEqual(len(FlowStatus), 9)


class TestPortStatus(unittest.TestCase):
    """Test PortStatus enum — port UI status tags."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(PortStatus.IDLE.value, "IDLE")
        self.assertEqual(PortStatus.READY.value, "READY")
        self.assertEqual(PortStatus.BUSY.value, "BUSY")
        self.assertEqual(PortStatus.OFF.value, "OFF")
        self.assertEqual(PortStatus.RESET.value, "RESET")
        self.assertEqual(PortStatus.CHECKING.value, "CHECKING")
        self.assertEqual(PortStatus.GAGAL.value, "GAGAL")
        self.assertEqual(PortStatus.PIN_LOCK.value, "PIN_LOCK")
        self.assertEqual(PortStatus.SUKSES.value, "SUKSES")
        self.assertEqual(PortStatus.DONE.value, "DONE")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(PortStatus.IDLE, Enum))
        self.assertTrue(isinstance(PortStatus.IDLE, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in PortStatus]
        self.assertEqual(len(values), len(set(values)))

    def test_member_count(self):
        """Verify expected member count."""
        self.assertEqual(len(PortStatus), 10)


class TestKkSource(unittest.TestCase):
    """Test KkSource enum — KK resolution source."""

    def test_values(self):
        """Verify correct enum values."""
        self.assertEqual(KkSource.NIK_MODE.value, "NIK_MODE")
        self.assertEqual(KkSource.LOCAL_DB.value, "LOCAL_DB")
        self.assertEqual(KkSource.TELEGRAM.value, "TELEGRAM")
        self.assertEqual(KkSource.NONE.value, "NONE")

    def test_inheritance(self):
        """Verify str, Enum inheritance."""
        self.assertTrue(isinstance(KkSource.NIK_MODE, Enum))
        self.assertTrue(isinstance(KkSource.NIK_MODE, str))

    def test_no_duplicates(self):
        """Verify no duplicate values."""
        values = [m.value for m in KkSource]
        self.assertEqual(len(values), len(set(values)))


class TestEnumSerialization(unittest.TestCase):
    """Test enum serialization and lookup behavior across all enums."""

    def test_value_from_string(self):
        """Verify enum can be created from value string."""
        self.assertEqual(BusinessOutcome("SUKSES"), BusinessOutcome.SUKSES)
        self.assertEqual(CpinState("READY"), CpinState.READY)
        self.assertEqual(FlowStatus("DONE"), FlowStatus.DONE)

    def test_key_lookup(self):
        """Verify enum can be accessed by name."""
        self.assertEqual(BusinessOutcome["SUKSES"], BusinessOutcome.SUKSES)
        self.assertEqual(CpinState["READY"], CpinState.READY)
        self.assertEqual(FlowStatus["DONE"], FlowStatus.DONE)

    def test_all_enums_injective(self):
        """Verify all enums have injective value-to-member mapping."""
        all_enums = [
            BusinessOutcome, CpinState, CardStatus, FailureCode,
            UssdClass, UssdIntent, FlowStatus, PortStatus, KkSource,
        ]
        for enum_cls in all_enums:
            values = [m.value for m in enum_cls]
            self.assertEqual(
                len(values), len(set(values)),
                f"{enum_cls.__name__} has duplicate values",
            )

    def test_all_enums_iterable(self):
        """Verify all enums can be iterated."""
        all_enums = [
            BusinessOutcome, CpinState, CardStatus, FailureCode,
            UssdClass, UssdIntent, FlowStatus, PortStatus, KkSource,
        ]
        for enum_cls in all_enums:
            for member in enum_cls:
                self.assertIsInstance(member, Enum)

    def test_total_member_count(self):
        """Verify total member count across all 9 enums."""
        all_enums = [
            BusinessOutcome, CpinState, CardStatus, FailureCode,
            UssdClass, UssdIntent, FlowStatus, PortStatus, KkSource,
        ]
        total = sum(len(e) for e in all_enums)
        # 3 + 5 + 4 + 5 + 11 + 6 + 9 + 10 + 4 = 57
        self.assertEqual(total, 57)


if __name__ == "__main__":
    unittest.main()
