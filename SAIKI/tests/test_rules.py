"""Tests for worker/rules.py — AutoRunConfig and gating functions."""

import unittest
import threading

from app.domain.enums import CpinState
from app.domain.constants import CPIN_UNKNOWN_THRESHOLD
from worker.rules import AutoRunConfig, should_block_auto_run


class TestAutoRunConfig(unittest.TestCase):
    """Tests for AutoRunConfig class."""

    def test_set_enabled_true(self):
        """set_enabled(True) should enable auto-run."""
        config = AutoRunConfig()
        config.set_enabled(True)
        self.assertTrue(config.auto_run_enabled)

    def test_set_enabled_false(self):
        """set_enabled(False) should disable auto-run."""
        config = AutoRunConfig()
        config.set_enabled(True)
        config.set_enabled(False)
        self.assertFalse(config.auto_run_enabled)

    def test_toggle(self):
        """toggle() should flip enabled state and return new value."""
        config = AutoRunConfig()
        result = config.toggle()
        self.assertTrue(result)
        self.assertTrue(config.auto_run_enabled)

    def test_toggle_twice(self):
        """Two toggles should return to original state."""
        config = AutoRunConfig()
        config.toggle()
        result = config.toggle()
        self.assertFalse(result)
        self.assertFalse(config.auto_run_enabled)

    def test_auto_run_enabled_default_false(self):
        """auto_run_enabled should default to False."""
        config = AutoRunConfig()
        self.assertFalse(config.auto_run_enabled)

    def test_toggle_returns_new_value(self):
        """toggle() should return the new value after flipping."""
        config = AutoRunConfig()
        config.set_enabled(True)
        result = config.toggle()
        self.assertFalse(result)

    def test_thread_safety(self):
        """Multiple threads toggling should not corrupt state."""
        config = AutoRunConfig()
        errors = []

        def toggle_many():
            try:
                for _ in range(100):
                    config.toggle()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=toggle_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        # 10 threads * 100 toggles = 1000 toggles (even), so should be False
        self.assertFalse(config.auto_run_enabled)


class TestShouldBlockAutoRun(unittest.TestCase):
    """Tests for should_block_auto_run function."""

    def setUp(self):
        self.config = AutoRunConfig()

    def _snapshot(self, **kwargs):
        """Helper to build a state snapshot with defaults."""
        base = {
            "cpin_state": CpinState.UNKNOWN,
            "awaiting_card_cycle": False,
            "unknown_failure_count": 0,
        }
        base.update(kwargs)
        return base

    def test_global_toggle_off_blocks(self):
        """Auto-run disabled globally should block."""
        self.config.set_enabled(False)
        snap = self._snapshot(cpin_state=CpinState.READY)
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=True)
        self.assertTrue(blocked)
        self.assertEqual(reason, "Auto-run disabled")

    def test_modem_offline_blocks(self):
        """Modem offline should block auto-run."""
        self.config.set_enabled(True)
        snap = self._snapshot()
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=False)
        self.assertTrue(blocked)
        self.assertEqual(reason, "Modem offline")

    def test_sim_not_inserted_blocks(self):
        """SIM NOT_INSERTED should block auto-run."""
        self.config.set_enabled(True)
        snap = self._snapshot(cpin_state=CpinState.NOT_INSERTED)
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=True)
        self.assertTrue(blocked)
        self.assertEqual(reason, "SIM not inserted")

    def test_sim_pin_required_blocks(self):
        """SIM PIN_REQUIRED should block auto-run."""
        self.config.set_enabled(True)
        snap = self._snapshot(cpin_state=CpinState.PIN_REQUIRED)
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=True)
        self.assertTrue(blocked)
        self.assertEqual(reason, "SIM requires PIN")

    def test_awaiting_card_cycle_blocks(self):
        """Awaiting card cycle (HR-004) should block auto-run."""
        self.config.set_enabled(True)
        snap = self._snapshot(
            cpin_state=CpinState.READY,
            awaiting_card_cycle=True,
        )
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=True)
        self.assertTrue(blocked)
        self.assertEqual(reason, "Awaiting card cycle")

    def test_unknown_threshold_reached_blocks(self):
        """CPIN unknown threshold reached (HR-019) should block auto-run."""
        self.config.set_enabled(True)
        snap = self._snapshot(
            cpin_state=CpinState.READY,
            unknown_failure_count=CPIN_UNKNOWN_THRESHOLD,
        )
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=True)
        self.assertTrue(blocked)
        self.assertEqual(reason, "CPIN unknown threshold reached")

    def test_unknown_threshold_exceeded_blocks(self):
        """CPIN unknown count exceeding threshold should also block."""
        self.config.set_enabled(True)
        snap = self._snapshot(
            cpin_state=CpinState.READY,
            unknown_failure_count=CPIN_UNKNOWN_THRESHOLD + 5,
        )
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=True)
        self.assertTrue(blocked)
        self.assertEqual(reason, "CPIN unknown threshold reached")

    def test_all_clear_not_blocked(self):
        """All conditions clear should not block."""
        self.config.set_enabled(True)
        snap = self._snapshot(cpin_state=CpinState.READY)
        blocked, reason = should_block_auto_run(snap, self.config, modem_online=True)
        self.assertFalse(blocked)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
