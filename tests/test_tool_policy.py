import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from harness.tool_policy import ToolPolicyError, load_tool_policies


def tool_policy(tool_id: str = "files.read") -> dict[str, object]:
    return {
        "id": tool_id,
        "action_class": "read_only",
        "risk_level": "low",
        "approval": "inherit",
        "argument_rules": [],
        "filesystem": {
            "access": "read",
            "path_arguments": ["path"],
            "require_exact_targets": False,
        },
        "shell": {"access": "none", "command_arguments": []},
        "network": {"access": "none", "host_arguments": [], "allowed_hosts": []},
        "private_data_egress": "deny",
        "untrusted_output": False,
    }


class ToolPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent.parent

    def test_source_registry_is_valid_and_empty_by_default(self) -> None:
        self.assertEqual(load_tool_policies(self.root), {})

    def test_duplicate_tool_ids_are_rejected(self) -> None:
        policy = tool_policy()
        candidate = self._repository({"version": "1.0", "tools": [policy, policy]})
        with self.assertRaisesRegex(ToolPolicyError, "Duplicate trusted tool ID"):
            load_tool_policies(candidate)

    def test_destructive_tools_require_exact_targets(self) -> None:
        policy = tool_policy("files.delete")
        policy["filesystem"] = {
            "access": "destructive",
            "path_arguments": ["path"],
            "require_exact_targets": False,
        }
        candidate = self._repository({"version": "1.0", "tools": [policy]})
        with self.assertRaisesRegex(ToolPolicyError, "requires exact targets"):
            load_tool_policies(candidate)

    def test_outbound_tools_require_explicit_hosts(self) -> None:
        policy = tool_policy("http.fetch")
        policy["filesystem"] = {
            "access": "none",
            "path_arguments": [],
            "require_exact_targets": False,
        }
        policy["network"] = {
            "access": "outbound",
            "host_arguments": ["host"],
            "allowed_hosts": [],
        }
        candidate = self._repository({"version": "1.0", "tools": [policy]})
        with self.assertRaisesRegex(ToolPolicyError, "requires host fields and allowed hosts"):
            load_tool_policies(candidate)

    def _repository(self, payload: dict[str, object]) -> Path:
        temporary = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temporary)
        root = Path(temporary)
        schemas = root / "config" / "schemas"
        schemas.mkdir(parents=True)
        shutil.copy2(
            self.root / "config" / "schemas" / "tool-policy.schema.json",
            schemas / "tool-policy.schema.json",
        )
        (root / "config" / "tools.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )
        return root


if __name__ == "__main__":
    unittest.main()
