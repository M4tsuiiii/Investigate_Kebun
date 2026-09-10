"""Tests for app/infrastructure/serial/modem_detector.py — ModemDetector.

ModemDetector detects modem presence and state via AT commands.
Tests use mocked at_client — no real hardware access.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.domain.enums import CpinState
from app.infrastructure.serial.modem_detector import ModemDetector, ModemInfo


def _make_at_client(modem_ok: bool = True, sim_response: str = "+CPIN: READY") -> MagicMock:
    mock_at = MagicMock()
    mock_at.check_modem.return_value = modem_ok
    mock_at.check_sim.return_value = sim_response

    mock_serial = MagicMock()
    mock_serial.port_name = "COM3"
    mock_at._serial = mock_serial

    resp = MagicMock()
    resp.success = True
    resp.lines = ["SIMCOM A7600", "OK"]
    mock_at.send_command.return_value = resp

    return mock_at


class TestModemDetector(unittest.TestCase):
    """Test ModemDetector — modem detection and state tracking."""

    def setUp(self) -> None:
        self.detector = ModemDetector()

    def test_detect_modem_returns_info_when_online(self) -> None:
        mock_at = _make_at_client(modem_ok=True)
        info = self.detector.detect_modem(mock_at)
        self.assertIsNotNone(info)
        self.assertIsInstance(info, ModemInfo)

    def test_detect_modem_returns_none_when_offline(self) -> None:
        mock_at = _make_at_client(modem_ok=False)
        info = self.detector.detect_modem(mock_at)
        self.assertIsNone(info)

    def test_detect_modem_caches_info(self) -> None:
        mock_at = _make_at_client()
        self.detector.detect_modem(mock_at)
        cached = self.detector.get_modem_info("COM3")
        self.assertIsNotNone(cached)

    def test_check_sim_state_returns_cpin_state(self) -> None:
        mock_at = _make_at_client(sim_response="+CPIN: READY")
        state = self.detector.check_sim_state(mock_at)
        self.assertEqual(state, CpinState.READY)

    def test_is_modem_online_true_when_responds(self) -> None:
        mock_at = _make_at_client(modem_ok=True)
        result = self.detector.is_modem_online(mock_at)
        self.assertTrue(result)

    def test_is_modem_online_false_when_no_response(self) -> None:
        mock_at = _make_at_client(modem_ok=False)
        result = self.detector.is_modem_online(mock_at)
        self.assertFalse(result)

    def test_get_modem_info_returns_cached(self) -> None:
        mock_at = _make_at_client()
        self.detector.detect_modem(mock_at)
        info = self.detector.get_modem_info("COM3")
        self.assertIsNotNone(info)
        self.assertEqual(info.port_name, "COM3")

    def test_get_modem_info_returns_none_when_not_found(self) -> None:
        info = self.detector.get_modem_info("COM99")
        self.assertIsNone(info)

    def test_modem_info_repr(self) -> None:
        info = ModemInfo(port_name="COM3", baud_rate=115200, sim_state=CpinState.READY)
        r = repr(info)
        self.assertIn("COM3", r)
        self.assertIn("115200", r)
        self.assertIn("READY", r)

    def test_detect_modem_sets_model(self) -> None:
        mock_at = _make_at_client()
        info = self.detector.detect_modem(mock_at)
        self.assertEqual(info.model, "SIMCOM A7600")

    def test_detect_modem_unknown_model(self) -> None:
        mock_at = _make_at_client()
        resp = MagicMock()
        resp.success = False
        resp.lines = []
        mock_at.send_command.return_value = resp
        info = self.detector.detect_modem(mock_at)
        self.assertEqual(info.model, "Unknown")

    def test_check_sim_state_not_inserted(self) -> None:
        mock_at = _make_at_client(sim_response="+CPIN: NOT INSERTED")
        state = self.detector.check_sim_state(mock_at)
        self.assertEqual(state, CpinState.NOT_INSERTED)

    def test_check_sim_state_unknown_response(self) -> None:
        mock_at = _make_at_client(sim_response="SOME GARBAGE")
        state = self.detector.check_sim_state(mock_at)
        self.assertEqual(state, CpinState.NOT_READY)


if __name__ == "__main__":
    unittest.main()
