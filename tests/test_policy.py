import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.policy import evaluate_tool_call  # noqa: E402


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent.parent

    def test_read_only_is_allowed(self) -> None:
        decision = evaluate_tool_call(self.root, {"action_class": "read_only"})
        self.assertTrue(decision.allowed)

    def test_destructive_requires_approval(self) -> None:
        decision = evaluate_tool_call(self.root, {"action_class": "destructive_change"})
        self.assertFalse(decision.allowed)

    def test_denied_pattern_wins_even_with_approval(self) -> None:
        decision = evaluate_tool_call(
            self.root,
            {"command": "rm -rf /", "action_class": "destructive_change", "explicit_approval": True},
        )
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
