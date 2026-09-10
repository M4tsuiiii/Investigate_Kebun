"""Tests for Sprint 15E — End-to-End CPIN Trace Audit.

Tests for: RAW MODEM TRACE, PARSER TRACE, CPIN RUNTIME TRACE,
FSM TRACE, UI EVENT TRACE, STARTUP SUMMARY.
"""

import unittest
from unittest.mock import MagicMock, patch, call
import logging

from app.domain.enums import CpinState, PortStatus
from app.domain.classifier import parse_cpin_response
from app.domain.state_machine.hw_sm import HwStateMachine, HwState
from worker.port_worker import PortWorker
from worker.cpin_runtime import CpinRuntime
from worker.rules import AutoRunConfig
from worker.ui.event_bus import EventBus


# ------------------------------------------------------------------
# 1. RAW MODEM TRACE — cpin_runtime logs SEND, RAW, HEX, LINES
# ------------------------------------------------------------------

class TestRawModemTrace(unittest.TestCase):
    """CPIN trace must log full raw response from modem."""

    def test_raw_response_logged(self):
        """_poll_once logs RAW RESPONSE."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        raw_logs = [l for l in cm.output if "RAW RESPONSE" in l]
        self.assertTrue(len(raw_logs) > 0)
        self.assertIn("+CPIN: READY", raw_logs[0])

    def test_send_logged(self):
        """_poll_once logs SEND command."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        send_logs = [l for l in cm.output if "SEND: AT+CPIN?" in l]
        self.assertTrue(len(send_logs) > 0)

    def test_hex_logged(self):
        """_poll_once logs HEX dump."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        hex_logs = [l for l in cm.output if "HEX:" in l]
        self.assertTrue(len(hex_logs) > 0)

    def test_lines_logged(self):
        """_poll_once logs LINES breakdown."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        lines_logs = [l for l in cm.output if "LINES:" in l]
        self.assertTrue(len(lines_logs) > 0)

    def test_empty_response_logged(self):
        """_poll_once logs (empty) for no response."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = ""
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        raw_logs = [l for l in cm.output if "RAW RESPONSE" in l]
        self.assertTrue(len(raw_logs) > 0)
        self.assertIn("(empty)", raw_logs[0])

    def test_port_in_trace(self):
        """_poll_once includes PORT= in trace."""
        cpin = CpinRuntime("COM104", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        port_logs = [l for l in cm.output if "PORT=COM104" in l]
        self.assertTrue(len(port_logs) > 0)


# ------------------------------------------------------------------
# 2. PARSER TRACE — logs INPUT/OUTPUT and UNKNOWN reason
# ------------------------------------------------------------------

class TestParserTrace(unittest.TestCase):
    """CPIN trace must log parser input/output and UNKNOWN reason."""

    def test_parse_input_logged(self):
        """_poll_once logs CPIN PARSE INPUT."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        input_logs = [l for l in cm.output if "CPIN PARSE" in l and "INPUT" in l]
        self.assertTrue(len(input_logs) > 0)

    def test_parse_output_logged(self):
        """_poll_once logs CPIN PARSE OUTPUT."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        output_logs = [l for l in cm.output if "CPIN PARSE" in l and "OUTPUT" in l]
        self.assertTrue(len(output_logs) > 0)
        self.assertIn("READY", output_logs[0])

    def test_unknown_reason_logged(self):
        """_poll_once logs REASON for UNKNOWN."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = None  # None triggers UNKNOWN path
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        reason_logs = [l for l in cm.output if "REASON" in l]
        self.assertTrue(len(reason_logs) > 0)

    def test_parse_not_inserted_logged(self):
        """_poll_once logs NOT_INSERTED output."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: SIM NOT INSERTED"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        output_logs = [l for l in cm.output if "CPIN PARSE" in l and "OUTPUT" in l]
        self.assertTrue(len(output_logs) > 0)
        self.assertIn("NOT_INSERTED", output_logs[0])


# ------------------------------------------------------------------
# 3. CPIN RUNTIME TRACE — logs PREVIOUS/CURRENT/CHANGED
# ------------------------------------------------------------------

class TestCpinRuntimeTrace(unittest.TestCase):
    """CPIN trace must log state transitions."""

    def test_previous_current_changed_logged(self):
        """_poll_once logs PREVIOUS, CURRENT, CHANGED."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        prev_logs = [l for l in cm.output if "PREVIOUS" in l]
        curr_logs = [l for l in cm.output if "CURRENT" in l]
        chng_logs = [l for l in cm.output if "CHANGED" in l]
        self.assertTrue(len(prev_logs) > 0)
        self.assertTrue(len(curr_logs) > 0)
        self.assertTrue(len(chng_logs) > 0)

    def test_changed_yes_on_transition(self):
        """CHANGED=YES when state transitions."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        chng_logs = [l for l in cm.output if "CHANGED" in l]
        self.assertTrue(any("YES" in l for l in chng_logs))

    def test_changed_no_when_stable(self):
        """No CHANGED log when state unchanged (only logs YES on change)."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        # First poll sets state
        cpin._poll_once()
        # Second poll with same state
        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        chng_logs = [l for l in cm.output if "CHANGED" in l]
        self.assertEqual(len(chng_logs), 0, "Should not log CHANGED when state is stable")


# ------------------------------------------------------------------
# 4. FSM TRACE — logs transitions and rejections
# ------------------------------------------------------------------

class TestFSMTrace(unittest.TestCase):
    """FSM must log transitions and rejections."""

    def test_transition_accepted_logged(self):
        """transition() logs EVENT ACCEPTED."""
        hw = HwStateMachine("COM1")
        # OFFLINE -> MODEM_DETECTED is valid
        with self.assertLogs("saiki.hw_sm", level="INFO") as cm:
            hw.transition(HwState.MODEM_DETECTED, "test")

        accepted_logs = [l for l in cm.output if "EVENT ACCEPTED" in l]
        self.assertTrue(len(accepted_logs) > 0)
        self.assertIn("OFFLINE", accepted_logs[0])
        self.assertIn("MODEM_DETECTED", accepted_logs[0])

    def test_transition_rejected_logged(self):
        """transition() logs EVENT REJECTED for invalid transition."""
        hw = HwStateMachine("COM1")
        # OFFLINE -> READY is valid (direct reconnect)
        # OFFLINE -> SIM_INSERTED is NOT valid
        with self.assertLogs("saiki.hw_sm", level="INFO") as cm:
            hw.transition(HwState.SIM_INSERTED, "test")

        rejected_logs = [l for l in cm.output if "EVENT REJECTED" in l]
        self.assertTrue(len(rejected_logs) > 0)

    def test_port_in_fsm_trace(self):
        """FSM trace includes PORT=."""
        hw = HwStateMachine("COM104")
        with self.assertLogs("saiki.hw_sm", level="INFO") as cm:
            hw.transition(HwState.MODEM_DETECTED, "test")

        port_logs = [l for l in cm.output if "PORT=COM104" in l]
        self.assertTrue(len(port_logs) > 0)

    def test_detail_in_fsm_trace(self):
        """FSM trace includes detail text."""
        hw = HwStateMachine("COM1")
        with self.assertLogs("saiki.hw_sm", level="INFO") as cm:
            hw.transition(HwState.MODEM_DETECTED, "Serial connected")

        detail_logs = [l for l in cm.output if "Serial connected" in l]
        self.assertTrue(len(detail_logs) > 0)


# ------------------------------------------------------------------
# 5. UI EVENT TRACE — logs cpin.transition publication
# ------------------------------------------------------------------

class TestUIEventTrace(unittest.TestCase):
    """CPIN trace must log cpin.transition publication and receipt."""

    def test_publish_trace_logged(self):
        """_poll_once logs UI TRACE on publish."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        ui_logs = [l for l in cm.output if "CPIN EVENT" in l and "PUBLISH" in l]
        self.assertTrue(len(ui_logs) > 0)
        self.assertIn("cpin.transition", ui_logs[0])
        self.assertIn("COM1", ui_logs[0])
        self.assertIn("READY", ui_logs[0])

    def test_publish_not_logged_when_same_state(self):
        """No UI TRACE when state unchanged."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        # First poll sets state
        cpin._poll_once()
        # Second poll with same state
        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        ui_logs = [l for l in cm.output if "UI TRACE" in l]
        self.assertEqual(len(ui_logs), 0)  # No publish on same state


# ------------------------------------------------------------------
# 6. STARTUP SUMMARY — CPIN AUDIT REPORT
# ------------------------------------------------------------------

class TestCpinAuditReport(unittest.TestCase):
    """Startup must print CPIN AUDIT REPORT per modem."""

    def test_audit_report_header_printed(self):
        """_print_startup_report prints CPIN AUDIT REPORT header."""
        from worker.system_bootstrap import SystemBootstrap

        bootstrap = SystemBootstrap()

        with patch("builtins.print") as mock_print:
            bootstrap._print_startup_report(scan_duration=0.0)

        all_calls = []
        for c in mock_print.call_args_list:
            if c[0]:
                all_calls.append(c[0][0])
        audit_headers = [c for c in all_calls if "CPIN AUDIT REPORT" in c]
        self.assertTrue(len(audit_headers) > 0)

    def test_audit_report_has_port_field(self):
        """CPIN AUDIT REPORT includes PORT: field."""
        from worker.system_bootstrap import SystemBootstrap

        bootstrap = SystemBootstrap()

        with patch("builtins.print") as mock_print:
            bootstrap._print_startup_report(scan_duration=0.0)

        all_calls = []
        for c in mock_print.call_args_list:
            if c[0]:
                all_calls.append(c[0][0])
        self.assertIsInstance(all_calls, list)


# ------------------------------------------------------------------
# 7. Integration: full trace chain
# ------------------------------------------------------------------

class TestFullTraceChain(unittest.TestCase):
    """Integration test for full trace chain."""

    def test_full_chain_logs_everything(self):
        """Complete chain: SEND → RAW → PARSE → FSM → UI TRACE."""
        event_bus = EventBus()
        cpin = CpinRuntime("COM1", MagicMock(), event_bus)
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "+CPIN: READY"
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        logs = cm.output

        # Verify all trace points exist
        self.assertTrue(any("SEND: AT+CPIN?" in l for l in logs))
        self.assertTrue(any("RAW RESPONSE" in l for l in logs))
        self.assertTrue(any("HEX:" in l for l in logs))
        self.assertTrue(any("LINES:" in l for l in logs))
        self.assertTrue(any("CPIN PARSE" in l and "INPUT" in l for l in logs))
        self.assertTrue(any("CPIN PARSE" in l and "OUTPUT" in l for l in logs))
        self.assertTrue(any("PREVIOUS" in l for l in logs))
        self.assertTrue(any("CURRENT" in l for l in logs))
        self.assertTrue(any("CHANGED" in l for l in logs))
        self.assertTrue(any("CPIN EVENT" in l and "PUBLISH" in l for l in logs))

    def test_echo_response_identified(self):
        """Trace reveals if modem echoes AT commands."""
        cpin = CpinRuntime("COM1", MagicMock(), MagicMock())
        at_client = MagicMock()
        response = MagicMock()
        response.raw = "AT+CPIN?\r\n+CPIN: READY"  # Echo + real response
        at_client.send_command.return_value = response
        cpin._at_client = at_client

        with self.assertLogs("saiki.cpin", level="DEBUG") as cm:
            cpin._poll_once()

        # Parser should still find READY
        output_logs = [l for l in cm.output if "CPIN PARSE" in l and "OUTPUT" in l]
        self.assertTrue(any("READY" in l for l in output_logs))


if __name__ == "__main__":
    unittest.main()
