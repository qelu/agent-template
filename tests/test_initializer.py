import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml


class InitializerTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def test_generated_harness_is_lean_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "sample-agent"
            result = self._initialize(destination, "codex")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((destination / "AGENTS.md").is_file())
            self.assertTrue((destination / ".codex" / "config.toml").is_file())
            self.assertTrue((destination / ".codex" / "hooks.json").is_file())
            self.assertTrue((destination / ".agents" / "skills" / "task-planning").is_dir())
            self.assertFalse((destination / "harness").exists())
            self.assertFalse((destination / "tests").exists())
            self.assertFalse((destination / "config" / "deployment.yaml").exists())
            self.assertFalse((destination / "config" / "lifecycle.yaml").exists())
            self.assertFalse((destination / "config" / "tools.yaml").exists())
            self.assertFalse((destination / "agent" / "config.yaml").exists())

            config = tomllib.loads((destination / ".codex" / "config.toml").read_text())
            self.assertEqual(config["approval_policy"], "on-request")
            self.assertEqual(config["sandbox_mode"], "workspace-write")
            self.assertFalse(config["sandbox_workspace_write"]["network_access"])
            self.assertIn("openaiDeveloperDocs", config["mcp_servers"])

            receipt = yaml.safe_load(
                (destination / ".agent-harness" / "installation.yaml").read_text()
            )
            self.assertEqual(receipt["schema_version"], "2.0")
            self.assertEqual(receipt["execution"], "host-native")
            self.assertEqual(receipt["run_identity"], "host-session")
            validation = subprocess.run(
                [sys.executable, str(destination / "scripts" / "validate_harness.py")],
                cwd=destination,
                capture_output=True,
                text=True,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_host_profiles_use_native_locations(self) -> None:
        cases = (
            ("codex", "codex", "AGENTS.md", ".agents/skills", ".codex/config.toml"),
            ("claude-code", "claude-code", "CLAUDE.md", ".claude/skills", ".claude/settings.json"),
            (
                "antigravity",
                "antigravity",
                "GEMINI.md",
                ".agents/skills",
                ".agents/mcp_config.json",
            ),
            ("gemini-cli", "antigravity", "GEMINI.md", ".agents/skills", ".agents/mcp_config.json"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for requested, canonical, entrypoint, skill_root, integration in cases:
                with self.subTest(host=requested):
                    destination = Path(temporary) / requested
                    result = self._initialize(destination, requested)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    receipt = yaml.safe_load(
                        (destination / ".agent-harness" / "installation.yaml").read_text()
                    )
                    self.assertEqual(receipt["host"], canonical)
                    self.assertTrue((destination / entrypoint).is_file())
                    self.assertTrue(
                        (destination / skill_root / "task-planning" / "SKILL.md").is_file()
                    )
                    self.assertTrue((destination / integration).is_file())
                    validation = subprocess.run(
                        [sys.executable, str(destination / "scripts" / "validate_harness.py")],
                        cwd=destination,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_antigravity_profile_uses_current_cli_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "antigravity"
            result = self._initialize(destination, "antigravity")
            self.assertEqual(result.returncode, 0, result.stderr)
            hooks = json.loads((destination / ".agents" / "hooks.json").read_text())
            self.assertIn("agent-harness-guardrails", hooks)
            mcp = json.loads((destination / ".agents" / "mcp_config.json").read_text())
            self.assertEqual(
                mcp["mcpServers"]["geminiDocs"],
                {"serverUrl": "https://gemini-api-docs-mcp.dev"},
            )

    def test_runtime_option_was_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._initialize(
                Path(temporary) / "runtime", "codex", extra=("--runtime", "reference")
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unrecognized arguments", result.stderr)

    def _initialize(
        self,
        destination: Path,
        host: str,
        *,
        extra: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(self.root / "scripts" / "initialize_agent.py"),
            "--destination",
            str(destination),
            "--name",
            "Profile Test",
            "--id",
            "profile-test",
            "--goal",
            "Validate generated host profiles.",
            "--role",
            "test assistant",
            "--tone",
            "concise",
            "--host",
            host,
            *extra,
        ]
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )


if __name__ == "__main__":
    unittest.main()
