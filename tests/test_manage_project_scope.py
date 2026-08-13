import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ManageProjectScopeTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def script(self) -> Path:
        return self.root / "skills" / "manage-project-scope" / "scripts" / "update_scope.py"

    def harness(self, parent: Path) -> Path:
        harness = parent / "harness"
        config = harness / "config"
        config.mkdir(parents=True)
        (config / "policies.yaml").write_text(
            (self.root / "config" / "policies.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return harness

    def invoke(self, harness: Path, project: Path, access: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--root",
                str(harness),
                "--path",
                str(project),
                "--access",
                access,
            ],
            capture_output=True,
            text=True,
        )

    def test_adds_canonical_read_write_scope_and_preserves_denials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            project = parent / "project"
            project.mkdir()

            result = self.invoke(harness, project, "read-write")
            policy = json.loads((harness / "config" / "policies.yaml").read_text())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(project.resolve()), policy["scope"]["allowed_read_paths"])
        self.assertIn(str(project.resolve()), policy["scope"]["allowed_write_paths"])
        self.assertIn(".env", policy["scope"]["denied_paths"])

    def test_read_only_scope_does_not_grant_write_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            project = parent / "project"
            project.mkdir()

            result = self.invoke(harness, project, "read")
            policy = json.loads((harness / "config" / "policies.yaml").read_text())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(project.resolve()), policy["scope"]["allowed_read_paths"])
        self.assertNotIn(str(project.resolve()), policy["scope"]["allowed_write_paths"])

    def test_rejects_broad_or_denied_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            secrets = parent / "secrets" / "project"
            secrets.mkdir(parents=True)

            broad = self.invoke(harness, Path(Path.home().anchor), "read")
            ancestor = self.invoke(harness, parent, "read")
            denied = self.invoke(harness, secrets, "read")

        self.assertNotEqual(broad.returncode, 0)
        self.assertIn("dangerously broad", broad.stderr)
        self.assertNotEqual(ancestor.returncode, 0)
        self.assertIn("dangerously broad", ancestor.stderr)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("denied path", denied.stderr)


if __name__ == "__main__":
    unittest.main()
