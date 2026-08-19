import json
import tempfile
import unittest
from pathlib import Path

from harness.policy import PolicyError, load_policy


class PolicyTests(unittest.TestCase):
    def test_repository_policy_uses_clear_path_names_and_strict_actions(self) -> None:
        root = Path(__file__).resolve().parent.parent
        policy = load_policy(root)
        self.assertEqual(policy["actions"]["read"], "allow")
        self.assertEqual(policy["actions"]["write"], "ask")
        self.assertEqual(policy["actions"]["delete"], "deny")
        self.assertEqual(
            set(policy["scope"]),
            {"allowed_read_paths", "allowed_write_paths", "denied_paths"},
        )
        self.assertNotIn("network", policy)
        self.assertEqual(policy["mcp"], {"mode": "allowlist", "allowed_servers": []})

    def test_runtime_parser_rejects_unknown_or_missing_fields(self) -> None:
        source = Path(__file__).resolve().parent.parent
        policy = json.loads((source / "config" / "policies.yaml").read_text())
        for mutation in ("unknown", "missing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "config").mkdir()
                candidate = json.loads(json.dumps(policy))
                if mutation == "unknown":
                    candidate["scope"]["read_roots"] = ["."]
                else:
                    del candidate["actions"]["unknown"]
                (root / "config" / "policies.yaml").write_text(json.dumps(candidate))
                with self.assertRaisesRegex(PolicyError, "invalid fields"):
                    load_policy(root)

    def test_delete_policy_cannot_be_weakened(self) -> None:
        source = Path(__file__).resolve().parent.parent
        policy = json.loads((source / "config" / "policies.yaml").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            policy["actions"]["delete"] = "ask"
            (root / "config" / "policies.yaml").write_text(json.dumps(policy))
            with self.assertRaisesRegex(PolicyError, "delete must be deny"):
                load_policy(root)


if __name__ == "__main__":
    unittest.main()
