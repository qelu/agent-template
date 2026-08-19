import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ManageMcpAccessTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def script(self) -> Path:
        return self.root / "skills" / "manage-mcp-access" / "scripts" / "update_mcp_access.py"

    @property
    def launcher(self) -> Path:
        return self.root / "scripts" / "update_mcp_access.py"

    def harness(self, parent: Path) -> Path:
        harness = parent / "harness"
        config = harness / "config"
        config.mkdir(parents=True)
        (config / "policies.yaml").write_text(
            (self.root / "config/policies.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        shutil.copytree(
            self.root / "skills/manage-mcp-access",
            harness / ".agents/skills/manage-mcp-access",
        )
        return harness

    def invoke(self, harness: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), "--root", str(harness), *arguments],
            capture_output=True,
            text=True,
        )

    def test_skill_uses_project_launcher_and_preserves_global_configuration(self) -> None:
        instructions = (self.script.parent.parent / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("python3 scripts/update_mcp_access.py", instructions)
        self.assertIn("does not edit the host's global MCP configuration", instructions)

    def test_enable_list_and_disable_are_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = self.harness(Path(temporary))
            enabled = self.invoke(harness, "--enable", "atlassian-rovo")
            repeated = self.invoke(harness, "--enable", "atlassian-rovo")
            listed = self.invoke(harness, "--list")
            disabled = self.invoke(harness, "--disable", "atlassian-rovo")
            policy = json.loads((harness / "config/policies.yaml").read_text())

        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        self.assertIn("Updated", enabled.stdout)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("unchanged", repeated.stdout)
        self.assertIn("atlassian-rovo", listed.stdout)
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertEqual(policy["mcp"]["allowed_servers"], [])

    def test_project_launcher_resolves_host_native_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = self.harness(Path(temporary))
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.launcher),
                    "--root",
                    str(harness),
                    "--enable",
                    "wikijs",
                ],
                cwd=harness,
                capture_output=True,
                text=True,
            )
            policy = json.loads((harness / "config/policies.yaml").read_text())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(policy["mcp"]["allowed_servers"], ["wikijs"])

    def test_rejects_invalid_server_ids_and_malformed_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = self.harness(Path(temporary))
            invalid = self.invoke(harness, "--enable", "wikijs/*")
            policy_path = harness / "config/policies.yaml"
            policy = json.loads(policy_path.read_text())
            del policy["mcp"]
            policy_path.write_text(json.dumps(policy))
            malformed = self.invoke(harness, "--list")

        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("Server ID", invalid.stderr)
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("mcp object", malformed.stderr)


if __name__ == "__main__":
    unittest.main()
