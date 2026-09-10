"""Tests for automation.policy — AutomationPolicy and AutomationMode."""

import unittest

from automation.policy import AutomationPolicy, AutomationMode


class TestAutomationMode(unittest.TestCase):
    """Test AutomationMode enum — automation mode options."""

    def test_mode_values(self) -> None:
        """Verify correct enum values."""
        self.assertEqual(AutomationMode.CHECK_DATA.value, "CHECK_DATA")
        self.assertEqual(AutomationMode.REACTIVATE_FAST.value, "REACTIVATE_FAST")
        self.assertEqual(AutomationMode.REACTIVATE_FULL.value, "REACTIVATE_FULL")

    def test_mode_member_count(self) -> None:
        """Verify expected member count."""
        self.assertEqual(len(AutomationMode), 3)


class TestAutomationPolicy(unittest.TestCase):
    """Test AutomationPolicy — workflow selection based on mode."""

    def test_default_mode_is_reactivate_full(self) -> None:
        """Verify default mode is REACTIVATE_FULL."""
        policy = AutomationPolicy()
        self.assertEqual(policy.mode, AutomationMode.REACTIVATE_FULL)

    def test_set_mode(self) -> None:
        """Verify set_mode updates mode."""
        policy = AutomationPolicy()
        policy.set_mode(AutomationMode.CHECK_DATA)
        self.assertEqual(policy.mode, AutomationMode.CHECK_DATA)

    def test_workflow_name_property(self) -> None:
        """Verify workflow_name returns correct workflow for current mode."""
        policy = AutomationPolicy(default_mode=AutomationMode.REACTIVATE_FULL)
        self.assertEqual(policy.workflow_name, "reactivate_full")
        policy.set_mode(AutomationMode.CHECK_DATA)
        self.assertEqual(policy.workflow_name, "check_data")
        policy.set_mode(AutomationMode.REACTIVATE_FAST)
        self.assertEqual(policy.workflow_name, "reactivate_fast")

    def test_select_workflow_check_data_trigger(self) -> None:
        """Verify USER_MASS_CHECK_NUMBER trigger always returns check_data."""
        policy = AutomationPolicy(default_mode=AutomationMode.REACTIVATE_FULL)
        result = policy.select_workflow(trigger="USER_MASS_CHECK_NUMBER")
        self.assertEqual(result, "check_data")

    def test_select_workflow_reactivate_trigger(self) -> None:
        """Verify USER_MASS_REACTIVATION uses current mode."""
        policy = AutomationPolicy(default_mode=AutomationMode.REACTIVATE_FAST)
        result = policy.select_workflow(trigger="USER_MASS_REACTIVATION")
        self.assertEqual(result, "reactivate_fast")

    def test_select_workflow_modem_online(self) -> None:
        """Verify MODEM_ONLINE trigger uses current mode."""
        policy = AutomationPolicy(default_mode=AutomationMode.REACTIVATE_FULL)
        result = policy.select_workflow(trigger="MODEM_ONLINE")
        self.assertEqual(result, "reactivate_full")

    def test_select_workflow_sim_inserted(self) -> None:
        """Verify SIM_INSERTED trigger uses current mode."""
        policy = AutomationPolicy(default_mode=AutomationMode.CHECK_DATA)
        result = policy.select_workflow(trigger="SIM_INSERTED")
        self.assertEqual(result, "check_data")

    def test_select_workflow_cpin_ready(self) -> None:
        """Verify CPIN_READY trigger uses current mode."""
        policy = AutomationPolicy(default_mode=AutomationMode.REACTIVATE_FULL)
        result = policy.select_workflow(trigger="CPIN_READY")
        self.assertEqual(result, "reactivate_full")

    def test_select_workflow_no_trigger(self) -> None:
        """Verify no trigger uses current mode as fallback."""
        policy = AutomationPolicy(default_mode=AutomationMode.REACTIVATE_FAST)
        result = policy.select_workflow(trigger="")
        self.assertEqual(result, "reactivate_fast")

    def test_mode_to_workflow_mapping(self) -> None:
        """Verify all modes map to expected workflow names."""
        expected = {
            AutomationMode.CHECK_DATA: "check_data",
            AutomationMode.REACTIVATE_FAST: "reactivate_fast",
            AutomationMode.REACTIVATE_FULL: "reactivate_full",
        }
        for mode, workflow in expected.items():
            policy = AutomationPolicy(default_mode=mode)
            self.assertEqual(policy.workflow_name, workflow)

    def test_custom_default_mode(self) -> None:
        """Verify constructor accepts non-default mode."""
        policy = AutomationPolicy(default_mode=AutomationMode.CHECK_DATA)
        self.assertEqual(policy.mode, AutomationMode.CHECK_DATA)


if __name__ == "__main__":
    unittest.main()
