import json
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
    capability_choices,
    destination_error,
    execute_plan,
    provision_and_validate,
    resolve_plan,
    select_capabilities,
    unresolved_placeholders,
)
from scripts.initialize_agent import host_cli_unavailable_message


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
            (
                "documentation-maintenance",
                "manage-project-scope",
                "map-skill-command",
                "safe-tool-use",
                "task-planning",
            ),
        )
        self.assertEqual(plan.launch_command, "claude")

    def test_resolver_accepts_an_existing_empty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            destination.mkdir()
            plan = resolve_plan(self.root, self.spec(destination))
            execute_plan(self.root, plan)
            self.assertTrue((destination / "config" / "persona.yaml").is_file())

    def test_resolver_rejects_a_non_empty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            destination.mkdir()
            (destination / "keep.txt").write_text("user data", encoding="utf-8")
            with self.assertRaisesRegex(InitializerError, "not empty"):
                resolve_plan(self.root, self.spec(destination))
            self.assertEqual((destination / "keep.txt").read_text(), "user data")

    def test_destination_validation_rejects_template_descendants(self) -> None:
        error = destination_error(self.root, self.root / "generated-agent")
        self.assertIn("outside the template", error or "")

    def test_gemini_cli_alias_resolves_to_antigravity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = resolve_plan(
                self.root,
                self.spec(Path(temporary) / "agent", host="gemini-cli"),
            )
        self.assertEqual(plan.spec.host, "antigravity")
        self.assertEqual(plan.launch_command, "agy")
        self.assertEqual(plan.documentation_provider, "gemini")

    def test_placeholder_scan_ignores_tool_managed_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".venv").mkdir()
            (root / ".venv" / "dependency.py").write_text("__THIRD_PARTY_TOKEN__")
            (root / "README.md").write_text("ready")
            self.assertEqual(unresolved_placeholders(root), [])

            (root / "README.md").write_text("__AGENT_NAME__")
            self.assertEqual(unresolved_placeholders(root), ["README.md"])

    def test_resolver_rejects_unknown_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(InitializerError, "Unknown capabilities"):
                resolve_plan(
                    self.root, self.spec(Path(temporary) / "agent", capabilities=("imaginary",))
                )

    def test_initializer_does_not_offer_inactive_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "config").mkdir()
            (source / "config" / "initializer.yaml").write_text(
                "version: '1.0'\nrequired_capabilities: []\ndefaults:\n"
                "  host: portable\n  python: '3.13'\n"
                "  development_tools: true\n  security_tools: false\n"
            )
            (source / "config" / "capabilities.yaml").write_text(
                "version: '1.0'\ncapabilities:\n"
                "  - id: inactive\n    type: skill\n    status: experimental\n"
                "    path: skills/inactive\n"
                "    description: Experimental test capability.\n"
                "    when: Use for testing.\n"
            )
            (source / "skills" / "inactive").mkdir(parents=True)
            self.assertEqual(capability_choices(source), ())

    def test_missing_host_install_is_explicit_and_uses_official_package(self) -> None:
        def find(command: str) -> str | None:
            return None if command == "claude" else f"/tools/{command}"

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("harness.initializer.shutil.which", side_effect=find),
        ):
            plan = resolve_plan(
                self.root, self.spec(Path(temporary) / "agent", install_host_tool=True)
            )
        self.assertEqual(
            plan.external_commands, (("npm", "install", "-g", "@anthropic-ai/claude-code"),)
        )

    def test_codex_cli_notice_distinguishes_desktop_app_from_path_check(self) -> None:
        message = host_cli_unavailable_message("codex", "codex")

        self.assertIn("CLI command (`codex`)", message)
        self.assertIn("shell's PATH", message)
        self.assertIn("desktop app may still be installed", message)

    def test_missing_gitleaks_plans_homebrew_install_on_macos(self) -> None:
        def find(command: str) -> str | None:
            return None if command == "gitleaks" else f"/tools/{command}"

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("harness.initializer.platform.system", return_value="Darwin"),
            patch("harness.initializer.shutil.which", side_effect=find),
        ):
            plan = resolve_plan(
                self.root,
                self.spec(Path(temporary) / "agent", security_tools=True),
            )
        self.assertIn(("brew", "install", "gitleaks"), plan.external_commands)

    def test_execution_generates_only_host_native_harness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            plan = resolve_plan(self.root, self.spec(destination))
            execute_plan(self.root, plan)

            self.assertTrue((destination / "CLAUDE.md").is_file())
            self.assertTrue((destination / ".claude" / "settings.json").is_file())
            self.assertTrue((destination / ".git").is_dir())
            self.assertTrue((destination / "scripts" / "guardrails" / "claude_code.py").is_file())
            self.assertTrue((destination / ".claude" / "skills" / "task-planning").is_dir())
            self.assertTrue((destination / ".claude" / "skills" / "safe-tool-use").is_dir())
            self.assertTrue((destination / ".claude" / "skills" / "manage-project-scope").is_dir())
            self.assertTrue((destination / ".claude" / "skills" / "map-skill-command").is_dir())
            self.assertFalse((destination / ".claude" / "skills" / "evidence-gathering").exists())
            self.assertTrue(
                (destination / ".claude" / "skills" / "anthropic-documentation").is_dir()
            )
            for removed in (
                "harness",
                "tests",
                "config/lifecycle.yaml",
                "config/tools.yaml",
                "agent/config.yaml",
            ):
                self.assertFalse((destination / removed).exists())

            settings = json.loads((destination / ".claude" / "settings.json").read_text())
            self.assertEqual(settings["permissions"]["defaultMode"], "default")
            self.assertIn("PreToolUse", settings["hooks"])
            registry = yaml.safe_load((destination / "config" / "capabilities.yaml").read_text())
            self.assertEqual(
                {item["id"] for item in registry["capabilities"]},
                {
                    "task-planning",
                    "safe-tool-use",
                    "manage-project-scope",
                    "map-skill-command",
                    "documentation-maintenance",
                    "anthropic-documentation",
                },
            )
            self.assertTrue(
                all(
                    set(item) == {"id", "type", "status", "path", "description", "when"}
                    for item in registry["capabilities"]
                )
            )
            receipt = yaml.safe_load(
                (destination / ".agent-harness" / "installation.yaml").read_text()
            )
            self.assertEqual(receipt["execution"], "host-native")
            self.assertEqual(receipt["run_identity"], "host-session")
            self.assertEqual(receipt["host"], "claude-code")

    def test_capability_removal_cannot_escape_or_delete_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            config = destination / "config"
            config.mkdir()
            (config / "capabilities.yaml").write_text(
                "version: '1.0'\ncapabilities:\n  - id: unsafe\n    path: .\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(InitializerError, "escapes"):
                select_capabilities(destination, set())
            self.assertTrue(destination.is_dir())

    def test_failed_provisioning_never_publishes_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            destination = parent / "agent"
            plan = resolve_plan(self.root, self.spec(destination, install_dependencies=True))
            with patch(
                "harness.initializer.provision_and_validate",
                side_effect=InitializerError("validation failed"),
            ):
                with self.assertRaisesRegex(InitializerError, "validation failed"):
                    execute_plan(self.root, plan)
            self.assertFalse(destination.exists())
            self.assertEqual(list(parent.glob(".agent.initializer-*")), [])

    def test_failed_provisioning_preserves_an_existing_empty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            destination = parent / "agent"
            destination.mkdir()
            plan = resolve_plan(self.root, self.spec(destination, install_dependencies=True))
            with patch(
                "harness.initializer.provision_and_validate",
                side_effect=InitializerError("validation failed"),
            ):
                with self.assertRaisesRegex(InitializerError, "validation failed"):
                    execute_plan(self.root, plan)
            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(list(parent.glob(".agent.initializer-*")), [])

    def test_successful_provisioning_publishes_passed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            plan = resolve_plan(self.root, self.spec(destination, install_dependencies=True))
            with patch("harness.initializer.provision_and_validate"):
                execute_plan(self.root, plan)
            receipt = yaml.safe_load(
                (destination / ".agent-harness" / "installation.yaml").read_text()
            )
            self.assertEqual(receipt["validation"], "passed")

    def test_provisioning_uses_host_validator_and_selected_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            with (
                patch("harness.initializer.shutil.which", return_value="/tools/uv"),
                patch("harness.initializer._run") as run,
            ):
                plan = resolve_plan(
                    self.root,
                    self.spec(
                        destination / "agent", install_dependencies=True, security_tools=True
                    ),
                )
                provision_and_validate(destination, plan)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["/tools/uv", "sync", "--python", "3.13", "--extra", "dev"])
        self.assertIn(["/tools/uv", "run", "python", "scripts/validate_harness.py"], commands)
        self.assertIn(["/tools/uv", "run", "ruff", "check", "."], commands)
        self.assertIn(
            ["gitleaks", "dir", ".", "--no-banner", "--redact", "--exit-code", "1"], commands
        )

    def test_uv_provisioning_ignores_an_unrelated_active_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            with (
                patch("harness.initializer.shutil.which", return_value="/tools/uv"),
                patch.dict("harness.initializer.os.environ", {"VIRTUAL_ENV": "/other/.venv"}),
                patch("harness.initializer.subprocess.run") as run,
            ):
                plan = resolve_plan(
                    self.root, self.spec(destination / "agent", install_dependencies=True)
                )
                provision_and_validate(destination, plan)
        for call in run.call_args_list:
            self.assertNotIn("VIRTUAL_ENV", call.kwargs["env"])

    def test_security_scan_runs_without_python_provisioning(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("harness.initializer.shutil.which", return_value="/tools/gitleaks"),
            patch("harness.initializer._run") as run,
        ):
            destination = Path(temporary) / "agent"
            plan = resolve_plan(self.root, self.spec(destination, security_tools=True))
            execute_plan(self.root, plan)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(
            ["gitleaks", "dir", ".", "--no-banner", "--redact", "--exit-code", "1"], commands
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
            self.assertIn("execution: host-native", result.stdout)
            self.assertFalse(destination.exists())

    def test_cli_success_recommends_generated_harness_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.root / "scripts" / "initialize_agent.py"),
                    "--destination",
                    str(destination),
                    "--name",
                    "Generated Validator",
                    "--goal",
                    "Validate the generated harness.",
                    "--role",
                    "assistant",
                    "--tone",
                    "concise",
                    "--host",
                    "portable",
                    "--no-color",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("scripts/validate_harness.py", result.stdout)
            self.assertIn(
                "Examples of what this harness can do (not a complete list)", result.stdout
            )
            self.assertIn("Here are some things you can try", result.stdout)
            self.assertIn("they are not required next steps", result.stdout)
            self.assertIn("Add /path/to/project", result.stdout)
            self.assertIn("Map /scope", result.stdout)
            self.assertNotIn("scripts/validate_repository.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
