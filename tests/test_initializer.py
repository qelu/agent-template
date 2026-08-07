import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


class InitializerTests(unittest.TestCase):
    def test_minimal_initialization_extension_and_validation(self) -> None:
        root = Path(__file__).resolve().parent.parent
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "sample-agent"
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "initialize_agent.py"),
                    "--destination",
                    str(destination),
                    "--name",
                    "Sample",
                    "--id",
                    "sample",
                    "--goal",
                    "Complete bounded sample tasks.",
                    "--role",
                    "sample assistant",
                    "--tone",
                    "clear and concise",
                ],
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            persona = (destination / "config" / "persona.yaml").read_text(encoding="utf-8")
            self.assertIn('name: "Sample"', persona)
            self.assertNotIn("__AGENT_NAME__", persona)
            project = (destination / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn('name = "sample"', project)
            self.assertNotIn("agent-template-placeholder", project)

            expected = {
                "agent",
                "config",
                "harness",
                "knowledge",
                "scripts",
                "skills",
                "templates",
                "tests",
            }
            directories = {path.name for path in destination.iterdir() if path.is_dir()}
            self.assertEqual(directories, expected)
            for excluded in ("examples", "hooks", "mcps", "runtime", "workflows"):
                self.assertFalse((destination / excluded).exists())
            self.assertFalse((destination / "config" / "registry").exists())
            self.assertFalse((destination / "tests" / "test_initializer.py").exists())
            deployment = yaml.safe_load(
                (destination / "config" / "deployment.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(deployment["host"], "portable")
            self.assertEqual(deployment["documentation"]["provider"], "none")
            self.assertEqual(deployment["runtime"]["adapter"], "none")
            for filename in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
                self.assertFalse((destination / filename).exists())
            self.assertEqual(list(destination.glob("skills/*/agents")), [])

            extension = subprocess.run(
                [
                    sys.executable,
                    str(destination / "scripts" / "create_extension.py"),
                    "--type",
                    "skill",
                    "--id",
                    "sample-analysis",
                    "--name",
                    "Sample Analysis",
                ],
                cwd=destination,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(extension.returncode, 0, extension.stderr)

            validation = subprocess.run(
                [sys.executable, str(destination / "scripts" / "validate_repository.py")],
                cwd=destination,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_host_and_documentation_profiles(self) -> None:
        cases = (
            ("codex", None, "openai", "AGENTS.md", ".codex/config.toml"),
            ("claude-code", None, "anthropic", "CLAUDE.md", None),
            ("gemini-cli", None, "gemini", "GEMINI.md", ".gemini/settings.json"),
            ("claude-code", "gemini", "gemini", "CLAUDE.md", ".mcp.json"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for host, override, provider, entrypoint, mcp_path in cases:
                with self.subTest(host=host, provider=provider):
                    destination = Path(temporary) / f"{host}-{provider}"
                    result = self._initialize(destination, host, override)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    deployment = yaml.safe_load(
                        (destination / "config" / "deployment.yaml").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(deployment["host"], host)
                    self.assertEqual(deployment["documentation"]["provider"], provider)
                    self.assertTrue((destination / entrypoint).is_file())
                    if mcp_path:
                        self.assertTrue((destination / mcp_path).is_file())
                    if provider == "anthropic":
                        self.assertTrue(
                            (destination / "skills" / "anthropic-documentation" / "SKILL.md").is_file()
                        )
                    validation = subprocess.run(
                        [
                            sys.executable,
                            str(destination / "scripts" / "validate_repository.py"),
                        ],
                        cwd=destination,
                        capture_output=True,
                        text=True,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    )
                    self.assertEqual(validation.returncode, 0, validation.stderr)
                    generated_tests = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "unittest",
                            "discover",
                            "-s",
                            "tests",
                            "-v",
                        ],
                        cwd=destination,
                        capture_output=True,
                        text=True,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    )
                    self.assertEqual(
                        generated_tests.returncode, 0, generated_tests.stderr
                    )

    def test_reference_runtime_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "reference-runtime"
            result = self._initialize(destination, "portable", None, "reference")
            self.assertEqual(result.returncode, 0, result.stderr)
            deployment = yaml.safe_load(
                (destination / "config" / "deployment.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(deployment["runtime"]["adapter"], "reference")
            generated_tests = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=destination,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(generated_tests.returncode, 0, generated_tests.stderr)

    def test_rejects_mcp_for_portable_host_and_unimplemented_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            portable = self._initialize(
                Path(temporary) / "portable-openai", "portable", "openai"
            )
            self.assertNotEqual(portable.returncode, 0)
            self.assertIn("requires a concrete --host", portable.stderr)

            runtime = self._initialize(
                Path(temporary) / "runtime", "codex", None, "openai-agents"
            )
            self.assertNotEqual(runtime.returncode, 0)
            self.assertIn("not implemented", runtime.stderr)

    @staticmethod
    def _initialize(
        destination: Path,
        host: str,
        documentation_provider: str | None,
        runtime: str = "none",
    ) -> subprocess.CompletedProcess[str]:
        root = Path(__file__).resolve().parent.parent
        command = [
            sys.executable,
            str(root / "scripts" / "initialize_agent.py"),
            "--destination",
            str(destination),
            "--name",
            "Profile Test",
            "--id",
            "profile-test",
            "--goal",
            "Validate generated deployment profiles.",
            "--role",
            "test assistant",
            "--tone",
            "concise",
            "--host",
            host,
            "--runtime",
            runtime,
        ]
        if documentation_provider is not None:
            command.extend(("--docs-provider", documentation_provider))
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )


if __name__ == "__main__":
    unittest.main()
