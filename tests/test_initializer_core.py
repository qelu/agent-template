import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema
import yaml

from harness.initializer import (
    GOOGLE_WORKSPACE_DEFAULT_SERVICES,
    InitializationSpec,
    InitializerError,
    capability_choices,
    destination_error,
    execute_plan,
    integration_choices,
    provision_and_validate,
    resolve_plan,
    select_capabilities,
    unresolved_placeholders,
)
from scripts.initialize_agent import host_cli_unavailable_message, wizard_spec


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

    def google_client(self, root: Path, *, client_id: str = "test-client") -> Path:
        path = root / f"{client_id}.json"
        path.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": "test-secret",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

    def test_resolver_adds_required_capabilities_and_host_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = resolve_plan(self.root, self.spec(Path(temporary) / "agent"))
        self.assertEqual(plan.documentation_provider, "anthropic")
        self.assertEqual(
            plan.capabilities,
            (
                "documentation-maintenance",
                "import-external-skill",
                "import-template-skills",
                "manage-project-scope",
                "map-skill-command",
                "safe-tool-use",
                "skill-auditor",
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

    def test_python_314_is_valid_installation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            plan = resolve_plan(
                self.root,
                self.spec(destination, python_version="3.14"),
            )
            execute_plan(self.root, plan)
            receipt = yaml.safe_load(
                (destination / ".agent-harness" / "installation.yaml").read_text()
            )
            schema = json.loads(
                (self.root / "config" / "schemas" / "installation.schema.json").read_text()
            )
            generated_readme = (destination / "README.md").read_text(encoding="utf-8")

        jsonschema.Draft202012Validator(schema).validate(receipt)
        self.assertEqual(receipt["environment"]["python"], "3.14")
        self.assertIn("uv sync --python 3.14", generated_readme)

    def test_wizard_all_bundles_never_builds_an_all_disabled_checkbox(self) -> None:
        initializer = yaml.safe_load((self.root / "config" / "initializer.yaml").read_text())

        def prompt(kind: str, message: str, **kwargs: object) -> dict[str, object]:
            if kind == "checkbox":
                choices = kwargs["choices"]
                assert isinstance(choices, list)
                self.assertTrue(choices)
                self.assertTrue(all(not getattr(choice, "disabled", False) for choice in choices))
            return {"kind": kind, "message": message, "kwargs": kwargs}

        def answer(question: dict[str, object]) -> object:
            message = str(question["message"])
            if question["kind"] == "path":
                return destination
            if message.startswith("Bundles"):
                kwargs = question["kwargs"]
                assert isinstance(kwargs, dict)
                choices = kwargs["choices"]
                assert isinstance(choices, list)
                return [choice.value for choice in choices]
            if message.startswith("Google Workspace services"):
                return list(GOOGLE_WORKSPACE_DEFAULT_SERVICES)
            if question["kind"] == "checkbox":
                return []
            if message.startswith("Host"):
                return "antigravity"
            if message.startswith("Official documentation"):
                return "gemini"
            if message.startswith("Python version"):
                return "3.13"
            if question["kind"] == "confirm":
                return False
            text_answers = {
                "Display name": "Bundle Test",
                "Agent ID": "bundle-test",
                "Primary goal": "Exercise bundle selection.",
                "Persona role": "test assistant",
                "Communication tone": "concise",
                "Language/locale": "en-US",
            }
            return next(
                value for prefix, value in text_answers.items() if message.startswith(prefix)
            )

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "questionary.path",
                side_effect=lambda message, **kwargs: prompt("path", message, **kwargs),
            ),
            patch(
                "questionary.text",
                side_effect=lambda message, **kwargs: prompt("text", message, **kwargs),
            ),
            patch(
                "questionary.select",
                side_effect=lambda message, **kwargs: prompt("select", message, **kwargs),
            ),
            patch(
                "questionary.checkbox",
                side_effect=lambda message, **kwargs: prompt("checkbox", message, **kwargs),
            ),
            patch(
                "questionary.confirm",
                side_effect=lambda message, **kwargs: prompt("confirm", message, **kwargs),
            ),
            patch("scripts.initialize_agent._ask", side_effect=answer),
            patch("scripts.initialize_agent.shutil.which", return_value=None),
        ):
            destination = str(Path(temporary) / "agent")
            spec = wizard_spec(self.root, no_color=True)

        supported_integration_ids = {
            choice.integration_id for choice in integration_choices(self.root, "antigravity")
        }
        selected_bundles = tuple(
            bundle_id
            for bundle_id, bundle in initializer["bundles"].items()
            if set(bundle["integrations"]).issubset(supported_integration_ids)
        )
        self.assertEqual(spec.bundles, selected_bundles)
        self.assertNotIn("github-work", spec.bundles)
        expected_capabilities = {
            capability
            for bundle_id, bundle in initializer["bundles"].items()
            if bundle_id in selected_bundles
            for capability in bundle["capabilities"]
        }
        expected_integrations = {
            integration
            for bundle_id, bundle in initializer["bundles"].items()
            if bundle_id in selected_bundles
            for integration in bundle["integrations"]
        }
        self.assertTrue(expected_capabilities.issubset(set(spec.capabilities or ())))
        self.assertEqual(set(spec.integrations), expected_integrations)

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
                "version: '1.0'\nrequired_capabilities: []\n"
                "default_capabilities: []\nbundles: {}\ndefaults:\n"
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

    def test_omitted_capabilities_preserve_configured_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = resolve_plan(
                self.root,
                self.spec(Path(temporary) / "agent", capabilities=None),
            )

        self.assertTrue(
            {"documentation-maintenance", "evidence-gathering", "devoteam-branding"}
            <= set(plan.capabilities)
        )
        self.assertNotIn("incident-triage", plan.capabilities)
        self.assertNotIn("pre-commit-secret-scan", plan.capabilities)

    def test_bundle_expands_to_visible_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = resolve_plan(
                self.root,
                self.spec(
                    Path(temporary) / "agent",
                    capabilities=(),
                    bundles=("governance",),
                ),
            )

        self.assertEqual(plan.bundles, ("governance",))
        self.assertTrue(
            {
                "evidence-gathering",
                "dependency-change-review",
                "documentation-maintenance",
                "post-work-review",
            }
            <= set(plan.capabilities)
        )

    def test_remote_integration_is_merged_and_recorded_for_each_host(self) -> None:
        integration = {
            "id": "example-cloud",
            "status": "active",
            "kind": "remote-mcp",
            "provider": "Example",
            "description": "Read example cloud records.",
            "official_source": "https://example.com/mcp",
            "auth": "oauth",
            "hosts": ["codex", "claude-code", "antigravity"],
            "default_approval": "writes",
            "required": False,
            "data_classes": ["records"],
            "write_capable": True,
            "endpoint": "https://example.com/mcp",
            "token_env": None,
            "command": None,
            "install_command": None,
            "setup_commands": [],
        }
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("harness.initializer._load_source_integrations", return_value=[integration]),
        ):
            root = Path(temporary)
            destinations: dict[str, Path] = {}
            for host in ("codex", "claude-code", "antigravity"):
                destination = root / host
                plan = resolve_plan(
                    self.root,
                    self.spec(
                        destination,
                        host=host,
                        documentation_provider="none",
                        integrations=("example-cloud",),
                    ),
                )
                execute_plan(self.root, plan)
                destinations[host] = destination

            codex_config = (destinations["codex"] / ".codex/config.toml").read_text()
            claude_config = json.loads((destinations["claude-code"] / ".mcp.json").read_text())
            antigravity_config = json.loads(
                (destinations["antigravity"] / ".agents/mcp_config.json").read_text()
            )
            receipt = yaml.safe_load(
                (destinations["codex"] / ".agent-harness/installation.yaml").read_text()
            )
            self.assertIn("[mcp_servers.example-cloud]", codex_config)
            self.assertIn("example-cloud", claude_config["mcpServers"])
            self.assertIn("example-cloud", antigravity_config["mcpServers"])
            self.assertEqual(
                antigravity_config["mcpServers"]["example-cloud"],
                {"serverUrl": "https://example.com/mcp"},
            )
            self.assertEqual(receipt["integrations"][0]["authentication"], "pending")
            self.assertTrue((destinations["codex"] / "docs/integrations.md").is_file())

    def test_provider_integrations_are_filtered_by_host(self) -> None:
        codex = {choice.integration_id for choice in integration_choices(self.root, "codex")}
        antigravity = {
            choice.integration_id for choice in integration_choices(self.root, "antigravity")
        }

        self.assertEqual(codex, {"atlassian-rovo", "github", "google-workspace"})
        self.assertEqual(antigravity, {"atlassian-rovo", "google-workspace"})

    def test_github_mcp_uses_environment_token_without_storing_a_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destinations: dict[str, Path] = {}
            for host in ("codex", "claude-code"):
                destination = root / host
                plan = resolve_plan(
                    self.root,
                    self.spec(
                        destination,
                        host=host,
                        documentation_provider="none",
                        capabilities=(),
                        integrations=("github",),
                    ),
                )
                execute_plan(self.root, plan)
                destinations[host] = destination

            codex = (destinations["codex"] / ".codex/config.toml").read_text()
            claude = json.loads((destinations["claude-code"] / ".mcp.json").read_text())
            docs = (destinations["codex"] / "docs/integrations.md").read_text()
            validation = subprocess.run(
                [sys.executable, "scripts/validate_harness.py"],
                cwd=destinations["codex"],
                capture_output=True,
                text=True,
            )

        self.assertIn('bearer_token_env_var = "GITHUB_PERSONAL_ACCESS_TOKEN"', codex)
        self.assertEqual(
            claude["mcpServers"]["github"]["headers"]["Authorization"],
            "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN:-}",
        )
        self.assertIn("Credential environment: GITHUB_PERSONAL_ACCESS_TOKEN", docs)
        self.assertNotIn("ghp_", codex + json.dumps(claude) + docs)
        self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_atlassian_bundle_uses_current_authv2_endpoint(self) -> None:
        expected_guidance = {
            "codex": "codex mcp login atlassian-rovo",
            "claude-code": "run `/mcp`",
            "antigravity": "Installed MCP Servers",
        }
        with tempfile.TemporaryDirectory() as temporary:
            for host, guidance in expected_guidance.items():
                destination = Path(temporary) / host
                plan = resolve_plan(
                    self.root,
                    self.spec(
                        destination,
                        host=host,
                        documentation_provider="none",
                        capabilities=(),
                        bundles=("atlassian-work",),
                    ),
                )
                execute_plan(self.root, plan)
                docs = (destination / "docs/integrations.md").read_text()
                receipt = yaml.safe_load(
                    (destination / ".agent-harness/installation.yaml").read_text()
                )
                self.assertIn(guidance, docs)
                self.assertEqual(receipt["integrations"][0]["authentication"], "pending")
                if host == "antigravity":
                    antigravity_config = json.loads(
                        (destination / ".agents/mcp_config.json").read_text()
                    )
                    self.assertEqual(
                        antigravity_config["mcpServers"]["atlassian-rovo"],
                        {
                            "command": "npx",
                            "args": [
                                "-y",
                                "mcp-remote@latest",
                                "https://mcp.atlassian.com/v1/mcp/authv2",
                            ],
                        },
                    )
                    self.assertIn("trusted localhost callback", docs)

            codex_config = (Path(temporary) / "codex/.codex/config.toml").read_text()

        self.assertIn("https://mcp.atlassian.com/v1/mcp/authv2", codex_config)
        self.assertIn('default_tools_approval_mode = "writes"', codex_config)
        self.assertIn('auth = "oauth"', codex_config)
        self.assertIn("required = false", codex_config)

    def test_google_workspace_plans_pinned_cli_install_when_missing(self) -> None:
        def find(command: str) -> str | None:
            return None if command in {"gws", "codex"} else f"/tools/{command}"

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("harness.initializer.shutil.which", side_effect=find),
            patch.dict(
                os.environ,
                {"GOOGLE_WORKSPACE_CLI_CONFIG_DIR": str(Path(temporary) / "gws")},
            ),
        ):
            client = self.google_client(Path(temporary))
            plan = resolve_plan(
                self.root,
                self.spec(
                    Path(temporary) / "agent",
                    host="codex",
                    capabilities=(),
                    bundles=("google-workspace",),
                    google_workspace_client=client,
                ),
            )

        self.assertIn(
            (
                "npm",
                "install",
                "--global",
                "@googleworkspace/cli@0.22.5",
            ),
            plan.external_commands,
        )
        self.assertIn("google-workspace-cli", plan.capabilities)
        self.assertEqual(plan.integrations, ("google-workspace",))

    def test_google_workspace_bundle_packages_cli_skill_and_setup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "harness.initializer.shutil.which", side_effect=lambda command: f"/tools/{command}"
            ),
            patch.dict(
                os.environ,
                {"GOOGLE_WORKSPACE_CLI_CONFIG_DIR": str(Path(temporary) / "gws")},
            ),
        ):
            client = self.google_client(Path(temporary))
            destination = Path(temporary) / "agent"
            plan = resolve_plan(
                self.root,
                self.spec(
                    destination,
                    host="codex",
                    capabilities=(),
                    bundles=("google-workspace",),
                    google_workspace_client=client,
                ),
            )
            execute_plan(self.root, plan)
            skill = destination / ".agents/skills/google-workspace-cli"
            docs = (destination / "docs/integrations.md").read_text()
            installed_client = Path(temporary) / "gws/client_secret.json"
            receipt = yaml.safe_load((destination / ".agent-harness/installation.yaml").read_text())

            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / "references/setup.md").is_file())
            self.assertIn("gws auth login --readonly -s gmail,drive,calendar", docs)
            self.assertIn("Google Workspace is CLI-backed; no MCP entry is generated", docs)
            self.assertEqual(stat.S_IMODE(installed_client.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(installed_client.parent.stat().st_mode), 0o700)
            self.assertFalse(any(destination.rglob("client_secret.json")))
            self.assertTrue(receipt["integration_setup"]["google_workspace"]["client_configured"])

    def test_google_workspace_rejects_a_token_as_the_oauth_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            token = root / "token.json"
            token.write_text(
                json.dumps({"refresh_token": "secret", "client_id": "client"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(InitializerError, "Desktop client"):
                resolve_plan(
                    self.root,
                    self.spec(
                        root / "agent",
                        host="codex",
                        capabilities=(),
                        bundles=("google-workspace",),
                        google_workspace_client=token,
                    ),
                )

    def test_google_workspace_rejects_a_broadly_readable_oauth_client(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX file modes are required")
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(
                os.environ,
                {"GOOGLE_WORKSPACE_CLI_CONFIG_DIR": str(Path(temporary) / "gws")},
            ),
        ):
            root = Path(temporary)
            client = self.google_client(root)
            client.chmod(0o644)
            with self.assertRaisesRegex(InitializerError, "chmod 600"):
                resolve_plan(
                    self.root,
                    self.spec(
                        root / "agent",
                        host="codex",
                        capabilities=(),
                        bundles=("google-workspace",),
                        google_workspace_client=client,
                    ),
                )

    def test_google_workspace_refuses_to_overwrite_a_different_client(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(
                os.environ,
                {"GOOGLE_WORKSPACE_CLI_CONFIG_DIR": str(Path(temporary) / "gws")},
            ),
        ):
            root = Path(temporary)
            config = root / "gws"
            config.mkdir()
            self.google_client(config, client_id="existing").replace(config / "client_secret.json")
            replacement = self.google_client(root, client_id="replacement")
            with self.assertRaisesRegex(InitializerError, "refusing to overwrite"):
                resolve_plan(
                    self.root,
                    self.spec(
                        root / "agent",
                        host="codex",
                        capabilities=(),
                        bundles=("google-workspace",),
                        google_workspace_client=replacement,
                    ),
                )

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
            self.assertTrue((destination / ".claude" / "skills" / "skill-auditor").is_dir())
            self.assertTrue((destination / ".claude" / "skills" / "import-external-skill").is_dir())
            self.assertTrue(
                (destination / ".claude" / "skills" / "import-template-skills").is_dir()
            )
            self.assertFalse((destination / ".claude" / "skills" / "evidence-gathering").exists())
            self.assertFalse((destination / ".githooks").exists())
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
                    "skill-auditor",
                    "import-external-skill",
                    "import-template-skills",
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
            self.assertEqual(
                receipt["template"]["repository"],
                "https://github.com/qelu/agent-template.git",
            )
            self.assertEqual(receipt["skill_imports"], [])

    def test_optional_devoteam_branding_skill_is_packaged_when_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            plan = resolve_plan(
                self.root,
                self.spec(destination, host="codex", capabilities=("devoteam-branding",)),
            )
            execute_plan(self.root, plan)

            skill = destination / ".agents" / "skills" / "devoteam-branding"
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / "references" / "official-sources.md").is_file())
            registry = yaml.safe_load(
                (destination / "config" / "capabilities.yaml").read_text(encoding="utf-8")
            )
            self.assertIn(
                "devoteam-branding",
                {item["id"] for item in registry["capabilities"]},
            )

    def test_optional_post_work_review_is_packaged_with_its_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "agent"
            plan = resolve_plan(
                self.root,
                self.spec(destination, host="codex", capabilities=("post-work-review",)),
            )
            execute_plan(self.root, plan)

            skill = destination / ".agents" / "skills" / "post-work-review"
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / "references" / "review-matrix.md").is_file())

    def test_operations_bundle_packages_runbooks_and_enables_secret_hook(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "harness.initializer.shutil.which", side_effect=lambda command: f"/tools/{command}"
            ),
        ):
            destination = Path(temporary) / "agent"
            plan = resolve_plan(
                self.root,
                self.spec(
                    destination,
                    host="codex",
                    capabilities=(),
                    bundles=("operations",),
                ),
            )
            execute_plan(self.root, plan)

            hook = destination / ".githooks" / "pre-commit"
            hooks_path = subprocess.run(
                ["git", "config", "--get", "core.hooksPath"],
                cwd=destination,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertTrue(hook.is_file())
            self.assertTrue(hook.stat().st_mode & 0o100)
            self.assertEqual(hooks_path, ".githooks")
            self.assertTrue((destination / "knowledge/runbooks/incident-response.md").is_file())
            self.assertTrue((destination / "knowledge/runbooks/integration-lifecycle.md").is_file())

    def test_secret_hook_plans_gitleaks_install_when_missing_on_macos(self) -> None:
        def find(command: str) -> str | None:
            return None if command in {"gitleaks", "codex"} else f"/tools/{command}"

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("harness.initializer.platform.system", return_value="Darwin"),
            patch("harness.initializer.shutil.which", side_effect=find),
        ):
            plan = resolve_plan(
                self.root,
                self.spec(
                    Path(temporary) / "agent",
                    host="codex",
                    capabilities=("pre-commit-secret-scan",),
                ),
            )

        self.assertIn(("brew", "install", "gitleaks"), plan.external_commands)

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
            self.assertIn("These illustrate a few of many capabilities", result.stdout)
            self.assertIn("Add /path/to/project", result.stdout)
            self.assertIn("Map /scope", result.stdout)
            self.assertNotIn("scripts/validate_repository.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
