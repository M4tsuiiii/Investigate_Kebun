import importlib.util
import sys
import types
import unittest
from pathlib import Path


class UssdResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_path = Path(__file__).with_name("kebun_reaktivasi(rev).py")
        spec = importlib.util.spec_from_file_location("kebun_reaktivasi_rev", module_path)
        cls.module = importlib.util.module_from_spec(spec)

        customtkinter_mod = types.ModuleType("customtkinter")
        customtkinter_mod.CTk = object
        customtkinter_mod.set_appearance_mode = lambda *args, **kwargs: None
        customtkinter_mod.set_default_color_theme = lambda *args, **kwargs: None
        sys.modules["customtkinter"] = customtkinter_mod

        serial_mod = types.ModuleType("serial")
        serial_mod.Serial = object
        serial_tools_mod = types.ModuleType("serial.tools")
        serial_tools_mod.list_ports = types.SimpleNamespace(comports=lambda: [])
        sys.modules["serial"] = serial_mod
        sys.modules["serial.tools"] = serial_tools_mod
        sys.modules["serial.tools.list_ports"] = serial_tools_mod.list_ports

        telethon_mod = types.ModuleType("telethon")
        telethon_sync_mod = types.ModuleType("telethon.sync")
        telethon_sync_mod.TelegramClient = object
        telethon_errors_mod = types.ModuleType("telethon.errors")
        telethon_errors_mod.SessionPasswordNeededError = Exception
        telethon_errors_mod.PasswordHashInvalidError = Exception
        telethon_errors_mod.PhoneCodeInvalidError = Exception
        telethon_errors_mod.PhoneCodeExpiredError = Exception
        telethon_errors_mod.FloodWaitError = Exception
        telethon_mod.sync = telethon_sync_mod
        telethon_mod.errors = telethon_errors_mod
        sys.modules["telethon"] = telethon_mod
        sys.modules["telethon.sync"] = telethon_sync_mod
        sys.modules["telethon.errors"] = telethon_errors_mod

        spec.loader.exec_module(cls.module)

    def test_payload_complete_detection_requires_quiet_period(self):
        self.assertFalse(self.module.is_ussd_payload_complete('+CUSD: 2'))
        self.assertTrue(self.module.is_ussd_payload_complete('+CUSD: 2,"Nomor Anda 081234567890"'))
        self.assertTrue(self.module.is_ussd_payload_complete('+CME ERROR: 10'))
        self.assertTrue(self.module.is_ussd_payload_complete('Silakan pilih 1 untuk konfirmasi'))

    def test_classify_ussd_response_at_ok(self):
        kind, payload = self.module.classify_ussd_response('AT+CUSD=1,"*185#",15\r\nOK\r\n')
        self.assertEqual(kind, 'AT_OK')
        self.assertIn('OK', payload)

    def test_classify_ussd_response_extracts_ussd_payload(self):
        sample = '+CUSD: 0,"Your number 085860925937, Balance Rp.0 Active 24-08-2026",15\r\n'
        kind, payload = self.module.classify_ussd_response(sample)
        self.assertEqual(kind, 'USSD_PAYLOAD')
        self.assertIn('085860925937', payload)
        self.assertIn('Active 24-08-2026', payload)

    def test_classify_ussd_response_partial(self):
        sample = '+CUSD: 0,"Your number 085860925937, Balance Rp.0 Active'
        kind, payload = self.module.classify_ussd_response(sample)
        self.assertEqual(kind, 'PARTIAL_RESPONSE')
        self.assertIn('Your number', payload)

    def test_classify_card_status_raw_tenggang(self):
        kategori, hari = self.module.classify_card_status("-", "Nomor sedang dalam masa tenggang")
        self.assertEqual(kategori, 'TENGGANG')
        self.assertIsNone(hari)

    def test_classify_ussd_evidence_captures_success_processing_and_tenggang(self):
        evidence = self.module.classify_ussd_evidence("Permintaan berhasil diproses dan sedang dalam masa tenggang")
        self.assertTrue(evidence["has_success_evidence"])
        self.assertTrue(evidence["has_processing_evidence"])
        self.assertTrue(evidence["has_tenggang_evidence"])

    def test_send_ussd_does_not_issue_duplicate_command_on_retry(self):
        worker = self.module.PortWorker.__new__(self.module.PortWorker)
        worker.port_name = "COM1"
        worker.next_dial_allowed_at = 0.0
        worker.ussd_internal_state = "IDLE"
        worker.log = lambda *args, **kwargs: None
        worker._log_ussd_flow_decision = lambda *args, **kwargs: None
        self.module.USSD_RETRY_DELAY_SECONDS = 0.0

        class FakeSerial:
            def __init__(self):
                self.buffer = []
                self.writes = []

            def reset_input_buffer(self):
                self.buffer = []

            def write(self, data):
                self.writes.append(data.decode("utf-8", errors="ignore"))
                if data.startswith(b"AT+CUSD=1"):
                    self.buffer.append("AT+CUSD=1,\"OK\"\r\n")
                    self.buffer.append("OK\r\n")

            def read(self, size):
                chunk = "".join(self.buffer[:size])
                if size <= len(self.buffer):
                    self.buffer = self.buffer[size:]
                else:
                    self.buffer = []
                return chunk.encode("utf-8")

            @property
            def in_waiting(self):
                return len(self.buffer)

            @property
            def is_open(self):
                return True

        serial = FakeSerial()
        response = worker.send_ussd(serial, "*123#")

        self.assertEqual(response, "timeout")
        self.assertEqual(serial.writes.count("AT+CUSD=1,\"*123#\",15\r\n"), 1)

    def test_send_ussd_discards_stale_payload_before_new_dial(self):
        worker = self.module.PortWorker.__new__(self.module.PortWorker)
        worker.port_name = "COM1"
        worker.next_dial_allowed_at = 0.0
        worker.ussd_internal_state = "IDLE"
        worker.log = lambda *args, **kwargs: None
        worker._log_ussd_flow_decision = lambda *args, **kwargs: None
        self.module.USSD_SESSION_FENCE_MIN_SECONDS = 0.0
        self.module.USSD_SESSION_FENCE_QUIET_SECONDS = 0.0

        class FakeSerial:
            def __init__(self):
                self.buffer = ['+CUSD: 0,"RESPONS_LAMA"\r\n']
                self.writes = []

            def write(self, data):
                self.writes.append(data.decode("utf-8", errors="ignore"))
                if data.startswith(b"AT+CUSD=1"):
                    self.buffer.append('+CUSD: 0,"RESPONS_BARU"\r\n')

            def read(self, size):
                chunks = self.buffer[:size]
                self.buffer = self.buffer[size:]
                return "".join(chunks).encode("utf-8")

            @property
            def in_waiting(self):
                return len(self.buffer)

        response = worker.send_ussd(FakeSerial(), "*123#")

        self.assertEqual(response, "RESPONS_BARU")


if __name__ == "__main__":
    unittest.main()
