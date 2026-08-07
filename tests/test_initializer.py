import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
