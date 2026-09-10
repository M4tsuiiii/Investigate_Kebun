"""Tests for Sprint 15O — Shared Serial Ownership Fix.

Verifies:
1. CpinRuntime stops BEFORE serial.close()
2. Serial.close() not called while CPIN thread alive
3. CpinRuntime restarts AFTER serial.open()
4. Reset sequence order is correct
5. No concurrent poll during reset
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class TestCpinRuntimeStopJoinsThread(unittest.TestCase):
    """R2: CpinRuntime.stop() must join thread."""

    def test_stop_joins_thread(self):
        """stop() waits for thread to exit."""
        from worker.cpin_runtime import CpinRuntime
        from worker.ui.event_bus import EventBus

        event_bus = EventBus()
        at_client = MagicMock()
        at_client._serial = MagicMock()
        at_client._serial.is_open = True
        at_client.send_command.return_value = MagicMock(raw="+CPIN: READY\r\nOK")

        cpin = CpinRuntime("COM99", at_client, event_bus)
        cpin.start()
        self.assertTrue(cpin._thread.is_alive())

        cpin.stop(timeout=3.0)

        self.assertIsNone(cpin._thread)
        self.assertFalse(cpin._running.is_set())

    def test_stop_without_thread(self):
        """stop() when no thread running is safe."""
        from worker.cpin_runtime import CpinRuntime
        from worker.ui.event_bus import EventBus

        event_bus = EventBus()
        at_client = MagicMock()

        cpin = CpinRuntime("COM99", at_client, event_bus)
        cpin.stop()

        self.assertIsNone(cpin._thread)

    def test_stop_logs_thread_exited(self):
        """stop() logs THREAD_EXITED=YES."""
        from worker.cpin_runtime import CpinRuntime
        from worker.ui.event_bus import EventBus

        event_bus = EventBus()
        at_client = MagicMock()
        at_client._serial = MagicMock()
        at_client._serial.is_open = True
        at_client.send_command.return_value = MagicMock(raw="OK")

        cpin = CpinRuntime("COM99", at_client, event_bus)
        cpin.start()
        time.sleep(0.2)

        with self.assertLogs("saiki.cpin", level="INFO") as cm:
            cpin.stop(timeout=3.0)

        stopped_logs = [l for l in cm.output if "[CPIN STOPPED]" in l and "THREAD_EXITED=YES" in l]
        self.assertTrue(len(stopped_logs) >= 1)


class TestResetHardwarePausesCpin(unittest.TestCase):
    """O1: ResetHardwareSkill pauses CpinRuntime before close."""

    def test_cpin_stopped_before_serial_close(self):
        """CpinRuntime.stop() called before serial.close()."""
        from worker.skills.reset_hardware import ResetHardwareSkill

        serial = MagicMock()
        serial.port_name = "COM99"
        serial.is_open = True
        serial.open.return_value = True

        at_client = MagicMock()
        at_client.check_modem.return_value = True
        at_client.send_command.return_value = MagicMock(raw="+CPIN: READY\r\nOK")

        cpin_runtime = MagicMock()
        cpin_runtime.stop.return_value = None
        cpin_runtime.start.return_value = None

        skill = ResetHardwareSkill(serial, at_client, cpin_runtime)

        call_order = []
        cpin_runtime.stop.side_effect = lambda **kw: call_order.append("cpin_stop")
        serial.close.side_effect = lambda: call_order.append("serial_close")
        serial.open.side_effect = lambda: (call_order.append("serial_open"), True)[1]
        cpin_runtime.start.side_effect = lambda: call_order.append("cpin_start")

        skill.execute("COM99", wait_seconds=0.01)

        self.assertEqual(call_order[0], "cpin_stop")
        self.assertEqual(call_order[1], "serial_close")
        self.assertEqual(call_order[2], "serial_open")
        self.assertEqual(call_order[3], "cpin_start")

    def test_reset_sequence_traces(self):
        """Reset sequence produces correct trace logs."""
        from worker.skills.reset_hardware import ResetHardwareSkill

        serial = MagicMock()
        serial.port_name = "COM99"
        serial.is_open = True
        serial.open.return_value = True

        at_client = MagicMock()
        at_client.check_modem.return_value = True
        at_client.send_command.return_value = MagicMock(raw="+CPIN: READY\r\nOK")

        cpin_runtime = MagicMock()

        skill = ResetHardwareSkill(serial, at_client, cpin_runtime)

        with self.assertLogs("saiki.skills", level="INFO") as cm:
            skill.execute("COM99", wait_seconds=0.01)

        sequence_logs = [l for l in cm.output if "[RESET SEQUENCE]" in l]
        steps = [l.split("STEP=")[1].split()[0] for l in sequence_logs if "STEP=" in l]

        self.assertIn("CPIN_STOP", steps)
        self.assertIn("SERIAL_CLOSE", steps)
        self.assertIn("MODEM_RESET", steps)
        self.assertIn("SERIAL_REOPEN", steps)
        self.assertIn("CPIN_START", steps)

    def test_cpin_stopped_logs_pause(self):
        """CpinRuntime.stop() produces [CPIN PAUSE] log."""
        from worker.cpin_runtime import CpinRuntime
        from worker.ui.event_bus import EventBus

        event_bus = EventBus()
        at_client = MagicMock()
        at_client._serial = MagicMock()
        at_client._serial.is_open = True
        at_client.send_command.return_value = MagicMock(raw="OK")

        cpin = CpinRuntime("COM99", at_client, event_bus)
        cpin.start()
        time.sleep(0.2)

        with self.assertLogs("saiki.cpin", level="INFO") as cm:
            cpin.stop(timeout=3.0)

        pause_logs = [l for l in cm.output if "[CPIN PAUSE]" in l]
        self.assertTrue(len(pause_logs) >= 1)


class TestNoConcurrentPollDuringReset(unittest.TestCase):
    """Test 5: No concurrent poll during reset sequence."""

    def test_no_poll_during_close_window(self):
        """CpinRuntime thread must be dead before serial.close() executes."""
        from worker.cpin_runtime import CpinRuntime
        from worker.skills.reset_hardware import ResetHardwareSkill
        from worker.ui.event_bus import EventBus

        event_bus = EventBus()
        at_client = MagicMock()
        at_client._serial = MagicMock()
        at_client._serial.is_open = True
        at_client.send_command.return_value = MagicMock(raw="OK")

        cpin = CpinRuntime("COM99", at_client, event_bus)
        cpin.start()
        time.sleep(0.3)

        self.assertTrue(cpin._thread.is_alive(), "CPIN thread should be alive before reset")

        serial = MagicMock()
        serial.port_name = "COM99"
        serial.is_open = True
        serial.open.return_value = True

        at_client2 = MagicMock()
        at_client2.check_modem.return_value = True
        at_client2.send_command.return_value = MagicMock(raw="+CPIN: READY\r\nOK")

        thread_was_alive_at_close = []
        original_close = serial.close

        def tracking_close():
            thread_was_alive_at_close.append(cpin._thread.is_alive() if cpin._thread else False)
            original_close()

        serial.close = tracking_close

        skill = ResetHardwareSkill(serial, at_client2, cpin)

        with self.assertLogs("saiki.skills", level="INFO"):
            skill.execute("COM99", wait_seconds=0.01)

        for was_alive in thread_was_alive_at_close:
            self.assertFalse(was_alive, "CPIN thread was alive when serial.close() was called!")


class TestCpinRuntimeRestartAfterReopen(unittest.TestCase):
    """Test 3: CpinRuntime restarts after reopen."""

    def test_cpin_restarted_after_reopen(self):
        """CpinRuntime.start() called after serial.open()."""
        from worker.skills.reset_hardware import ResetHardwareSkill

        serial = MagicMock()
        serial.port_name = "COM99"
        serial.is_open = True
        serial.open.return_value = True

        at_client = MagicMock()
        at_client.check_modem.return_value = True
        at_client.send_command.return_value = MagicMock(raw="+CPIN: READY\r\nOK")

        cpin_runtime = MagicMock()

        skill = ResetHardwareSkill(serial, at_client, cpin_runtime)

        with self.assertLogs("saiki.skills", level="INFO"):
            skill.execute("COM99", wait_seconds=0.01)

        cpin_runtime.reset_stabilization.assert_called_once()
        cpin_runtime.start.assert_called_once()

    def test_cpin_started_logs(self):
        """CPIN STARTED log appears after restart."""
        from worker.cpin_runtime import CpinRuntime
        from worker.ui.event_bus import EventBus

        event_bus = EventBus()
        at_client = MagicMock()
        at_client._serial = MagicMock()
        at_client._serial.is_open = True
        at_client.send_command.return_value = MagicMock(raw="OK")

        cpin = CpinRuntime("COM99", at_client, event_bus)

        with self.assertLogs("saiki.cpin", level="INFO") as cm:
            cpin.start()

        started_logs = [l for l in cm.output if "[CPIN STARTED]" in l]
        self.assertEqual(len(started_logs), 1)


class TestResetWithoutCpinRuntime(unittest.TestCase):
    """Edge case: ResetHardwareSkill without cpin_runtime."""

    def test_reset_works_without_cpin(self):
        """Reset works even if cpin_runtime is None."""
        from worker.skills.reset_hardware import ResetHardwareSkill

        serial = MagicMock()
        serial.port_name = "COM99"
        serial.is_open = True
        serial.open.return_value = True

        at_client = MagicMock()
        at_client.check_modem.return_value = True
        at_client.send_command.return_value = MagicMock(raw="+CPIN: READY\r\nOK")

        skill = ResetHardwareSkill(serial, at_client, cpin_runtime=None)

        with self.assertLogs("saiki.skills", level="INFO") as cm:
            result = skill.execute("COM99", wait_seconds=0.01)

        self.assertTrue(result.success)
        skipped_logs = [l for l in cm.output if "SKIPPED=no_runtime" in l]
        self.assertTrue(len(skipped_logs) >= 2)


if __name__ == "__main__":
    unittest.main()
