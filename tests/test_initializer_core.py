import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from harness.initializer import (
    InitializationSpec,
    InitializerError,
    execute_plan,
    provision_and_validate,
    resolve_plan,
    select_capabilities,
)


class InitializerCoreTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def spec(self, destination: Path, **overrides: object) -> InitializationSpec:
        values: dict[str, object] = {
            "destination": destination,
            "name": "Terminal Agent",
            "agent_id": "terminal-agent",
            "goal": "Exercise the initializer.",
            "role": "test assistant",
            "tone": "concise",
            "host": "claude-code",
            "capabilities": ("documentation-maintenance",),
        }
        values.update(overrides)
        return InitializationSpec(**values)  # type: ignore[arg-type]

    def test_resolver_adds_required_capabilities_and_host_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = resolve_plan(self.root, self.spec(Path(temporary) / "agent"))
        self.assertEqual(plan.documentation_provider, "anthropic")
        self.assertEqual(
            plan.capabilities,
            ("documentation-maintenance", "safe-tool-use", "task-planning"),
        )
        self.assertEqual(plan.launch_command, "claude")

    def test_resolver_rejects_unknown_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(InitializerError, "Unknown capabilities"):
                resolve_plan(
                    self.root,
                    self.spec(Path(temporary) / "agent", capabilities=("imaginary",)),
                )

    def test_missing_host_install_is_explicit_and_uses_official_package(self) -> None:
        def find(command: str) -> str | None:
            return None if command == "claude" else f"/tools/{command}"

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("harness.initializer.shutil.which", side_effect=find),
        ):
            plan = resolve_plan(
                self.root,
                self.spec(Path(temporary) / "agent", install_host_tool=True),
            )
        self.assertEqual(
            plan.external_commands,
            (("npm", "install", "-g", "@anthropic-ai/claude-code"),),
        )

    def test_execution_selects_capabilities_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            plan = resolve_plan(self.root, self.spec(destination))
            execute_plan(self.root, plan)

            self.assertTrue((destination / "CLAUDE.md").is_file())
            self.assertTrue((destination / "skills" / "task-planning").is_dir())
            self.assertTrue((destination / "skills" / "safe-tool-use").is_dir())
            self.assertTrue((destination / "skills" / "documentation-maintenance").is_dir())
            self.assertFalse((destination / "skills" / "evidence-gathering").exists())
            self.assertTrue((destination / "skills" / "anthropic-documentation").is_dir())
            registry = yaml.safe_load(
                (destination / "config" / "capabilities.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                {item["id"] for item in registry["capabilities"]},
                {
                    "task-planning",
                    "safe-tool-use",
                    "documentation-maintenance",
                    "anthropic-documentation",
                },
            )
            receipt = yaml.safe_load(
                (destination / ".agent-harness" / "installation.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["validation"], "pending")
            self.assertEqual(receipt["host"], "claude-code")
            self.assertIn("anthropic-documentation", receipt["capabilities"])

    def test_capability_removal_cannot_escape_or_delete_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            config = destination / "config"
            config.mkdir()
            (config / "capabilities.yaml").write_text(
                "version: '2.0'\ncapabilities:\n  - id: unsafe\n    path: .\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(InitializerError, "escapes"):
                select_capabilities(destination, set())
            self.assertTrue(destination.is_dir())

    def test_failed_provisioning_never_publishes_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            destination = parent / "agent"
            plan = resolve_plan(
                self.root,
                self.spec(destination, install_dependencies=True),
            )
            with patch(
                "harness.initializer.provision_and_validate",
                side_effect=InitializerError("validation failed"),
            ):
                with self.assertRaisesRegex(InitializerError, "validation failed"):
                    execute_plan(self.root, plan)
            self.assertFalse(destination.exists())
            self.assertEqual(list(parent.glob(".agent.initializer-*")), [])

    def test_successful_provisioning_publishes_passed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            plan = resolve_plan(
                self.root,
                self.spec(destination, install_dependencies=True),
            )
            with patch("harness.initializer.provision_and_validate"):
                execute_plan(self.root, plan)
            receipt = yaml.safe_load(
                (destination / ".agent-harness" / "installation.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["validation"], "passed")

    def test_provisioning_uses_uv_and_selected_validation_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            with (
                patch("harness.initializer.shutil.which", return_value="/tools/uv"),
                patch("harness.initializer._run") as run,
            ):
                plan = resolve_plan(
                    self.root,
                    self.spec(
                        destination / "agent",
                        install_dependencies=True,
                        security_tools=True,
                    ),
                )
                provision_and_validate(destination, plan)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["/tools/uv", "sync", "--python", "3.13", "--extra", "dev"])
        self.assertIn(("/tools/uv", "run", "ruff", "check", "."), commands)
        self.assertIn(
            ("gitleaks", "dir", ".", "--no-banner", "--redact", "--exit-code", "1"),
            commands,
        )

    def test_cli_dry_run_does_not_create_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.root / "scripts" / "initialize_agent.py"),
                    "--destination",
                    str(destination),
                    "--name",
                    "Dry Run",
                    "--goal",
                    "Inspect the plan.",
                    "--role",
                    "assistant",
                    "--tone",
                    "concise",
                    "--host",
                    "claude-code",
                    "--capability",
                    "evidence-gathering",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("destination:", result.stdout)
            self.assertIn("Dry run complete", result.stdout)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
