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
            self.assertTrue((destination / "scripts" / "guardrails" / "codex.py").is_file())
            self.assertTrue((destination / "scripts" / "update_scope.py").is_file())
            self.assertTrue((destination / "scripts" / "update_mcp_access.py").is_file())
            self.assertFalse((destination / "scripts" / "guardrails" / "__pycache__").exists())
            self.assertTrue((destination / ".git").is_dir())
            self.assertTrue((destination / ".agents" / "skills" / "task-planning").is_dir())
            self.assertFalse((destination / "harness").exists())
            self.assertFalse((destination / "tests").exists())
            self.assertFalse((destination / "config" / "deployment.yaml").exists())
            self.assertFalse((destination / "config" / "lifecycle.yaml").exists())
            self.assertFalse((destination / "config" / "tools.yaml").exists())
            self.assertFalse((destination / "agent" / "config.yaml").exists())

            config = tomllib.loads((destination / ".codex" / "config.toml").read_text())
            self.assertEqual(config["approval_policy"], "on-request")
            self.assertEqual(config["sandbox_mode"], "read-only")
            self.assertIn("openaiDeveloperDocs", config["mcp_servers"])
            policy = json.loads((destination / "config" / "policies.yaml").read_text())
            self.assertEqual(policy["mcp"]["allowed_servers"], ["openaiDeveloperDocs"])

            hooks = json.loads((destination / ".codex" / "hooks.json").read_text())
            command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            subdirectory = destination / "nested"
            subdirectory.mkdir()
            hook_result = subprocess.run(
                command,
                cwd=subdirectory,
                shell=True,
                input=json.dumps(
                    {
                        "session_id": "generated-root",
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": "sudo rm -rf /"},
                    }
                ),
                capture_output=True,
                text=True,
            )
            self.assertEqual(hook_result.returncode, 0, hook_result.stderr)
            self.assertEqual(
                json.loads(hook_result.stdout)["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

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
            guardrails = hooks["agent-harness-guardrails"]
            self.assertIn("--event PreInvocation", guardrails["PreInvocation"][0]["command"])
            self.assertIn("--event PreToolUse", guardrails["PreToolUse"][0]["hooks"][0]["command"])
            mcp = json.loads((destination / ".agents" / "mcp_config.json").read_text())
            self.assertEqual(
                mcp["mcpServers"]["geminiDocs"],
                {"serverUrl": "https://gemini-api-docs-mcp.dev"},
            )
            policy = json.loads((destination / "config/policies.yaml").read_text())
            self.assertEqual(policy["mcp"]["allowed_servers"], ["geminiDocs"])

    def test_runtime_option_was_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._initialize(
                Path(temporary) / "runtime", "codex", extra=("--runtime", "reference")
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unrecognized arguments", result.stderr)

    def test_rovo_and_google_workspace_are_primed_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "primed-agent"
            client = root / "web-client.json"
            client.write_text(
                json.dumps(
                    {
                        "web": {
                            "client_id": "test-client",
                            "client_secret": "test-secret",
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "redirect_uris": ["http://localhost:8000/oauth2callback"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            client.chmod(0o600)
            workspace_config = root / "workspace-config"
            result = self._initialize(
                destination,
                "antigravity",
                extra=(
                    "--docs-provider",
                    "none",
                    "--bundle",
                    "atlassian-work",
                    "--bundle",
                    "google-workspace",
                    "--google-workspace-client",
                    str(client),
                    "--google-workspace-service",
                    "gmail",
                    "--yes",
                ),
                env={"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(workspace_config)},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((workspace_config / "client_secret.json").is_file())
            self.assertFalse(any(destination.rglob("client_secret.json")))
            project_mcp = json.loads((destination / ".agents/mcp_config.json").read_text())
            docs = (destination / "docs/integrations.md").read_text()
            self.assertIn("atlassian-rovo", project_mcp["mcpServers"])
            self.assertIn("google-workspace", project_mcp["mcpServers"])
            self.assertIn("workspace-mcp==1.25.0", docs)

    def _initialize(
        self,
        destination: Path,
        host: str,
        *,
        extra: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
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
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(env or {})},
        )


if __name__ == "__main__":
    unittest.main()
