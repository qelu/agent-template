import unittest
from pathlib import Path

from harness.policy import PolicyError, authorization_requirement, load_policy


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = {
            "authorization": {
                "read_only": "autonomous",
                "destructive_change": "explicit_approval",
            }
        }

    def test_reads_only_trusted_authorization_configuration(self) -> None:
        self.assertEqual(authorization_requirement(self.policy, "read_only"), "autonomous")
        self.assertEqual(
            authorization_requirement(self.policy, "destructive_change"),
            "explicit_approval",
        )

    def test_repository_policy_has_separate_read_and_write_roots(self) -> None:
        root = Path(__file__).resolve().parent.parent
        policy = load_policy(root)
        self.assertIn("read_roots", policy["scope"])
        self.assertIn("write_roots", policy["scope"])

    def test_unknown_classification_fails_closed(self) -> None:
        with self.assertRaisesRegex(PolicyError, "Unknown authorization"):
            authorization_requirement(self.policy, "model_supplied_classification")

    def test_caller_approval_fields_are_not_part_of_the_policy_api(self) -> None:
        with self.assertRaises(TypeError):
            authorization_requirement(  # type: ignore[call-arg]
                self.policy,
                "read_only",
                explicit_approval=True,
            )


if __name__ == "__main__":
    unittest.main()
