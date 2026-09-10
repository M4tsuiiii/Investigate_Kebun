"""Tests for worker.skills.base — Skill ABC and SkillResult dataclass.

SkillResult is the unified return type for all skills.
Skill is the abstract base class that all concrete skills must extend.
"""

import unittest
from typing import Any, Dict

from worker.skills.base import Skill, SkillResult


class ConcreteSkill(Skill):
    """Minimal concrete skill for testing the ABC contract."""

    @property
    def name(self) -> str:
        return "test_skill"

    @property
    def description(self) -> str:
        return "A test skill"

    def execute(self, port: str, **kwargs: Any) -> SkillResult:
        return self._success(port)


class TestSkillResultDefaults(unittest.TestCase):
    """Test SkillResult default values."""

    def test_skill_result_success_defaults(self) -> None:
        """success=True should be explicitly set."""
        result = SkillResult(success=True)
        self.assertTrue(result.success)

    def test_skill_result_failure_defaults(self) -> None:
        """success=False should be explicitly set."""
        result = SkillResult(success=False)
        self.assertFalse(result.success)

    def test_skill_result_data_defaults_to_empty_dict(self) -> None:
        """data should default to an empty dict, not None."""
        result = SkillResult(success=True)
        self.assertEqual(result.data, {})
        self.assertIsInstance(result.data, dict)

    def test_skill_result_success_with_data(self) -> None:
        """data dict should carry skill-specific payload."""
        data = {"modem_responsive": True, "raw_response": "OK"}
        result = SkillResult(success=True, data=data)
        self.assertEqual(result.data["modem_responsive"], True)
        self.assertEqual(result.data["raw_response"], "OK")

    def test_skill_result_failure_with_error(self) -> None:
        """error string should carry failure reason."""
        result = SkillResult(success=False, error="No AT client available")
        self.assertEqual(result.error, "No AT client available")

    def test_skill_result_repr(self) -> None:
        """repr should include key fields for debugging."""
        result = SkillResult(
            success=True,
            skill_name="cek_nomor",
            port="COM3",
            error="",
        )
        r = repr(result)
        self.assertIn("success=True", r)
        self.assertIn("cek_nomor", r)
        self.assertIn("COM3", r)


class TestSkillABC(unittest.TestCase):
    """Test that Skill is an ABC and cannot be instantiated directly."""

    def test_cannot_instantiate_skill_directly(self) -> None:
        """Skill is abstract — direct instantiation must raise TypeError."""
        with self.assertRaises(TypeError):
            Skill()  # type: ignore[abstract]

    def test_success_helper_creates_success_result(self) -> None:
        """_success() should return a SkillResult with success=True."""
        skill = ConcreteSkill()
        result = skill._success("COM5", data={"key": "value"})
        self.assertTrue(result.success)
        self.assertEqual(result.data, {"key": "value"})
        self.assertEqual(result.skill_name, "test_skill")
        self.assertEqual(result.port, "COM5")

    def test_failure_helper_creates_failure_result(self) -> None:
        """_failure() should return a SkillResult with success=False."""
        skill = ConcreteSkill()
        result = skill._failure("COM5", "Something broke")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Something broke")
        self.assertEqual(result.skill_name, "test_skill")
        self.assertEqual(result.port, "COM5")

    def test_success_helper_with_no_data(self) -> None:
        """_success() with no data should default to empty dict."""
        skill = ConcreteSkill()
        result = skill._success("COM1")
        self.assertEqual(result.data, {})

    def test_concrete_skill_execute_returns_result(self) -> None:
        """A concrete skill's execute should return a SkillResult."""
        skill = ConcreteSkill()
        result = skill.execute("COM1")
        self.assertIsInstance(result, SkillResult)
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
