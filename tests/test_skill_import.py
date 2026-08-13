import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from harness.initializer import InitializationSpec, execute_plan, resolve_plan


class SkillImportTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def harness(self, parent: Path) -> Path:
        destination = parent / "harness"
        spec = InitializationSpec(
            destination=destination,
            name="Import Test",
            agent_id="import-test",
            goal="Test safe skill imports.",
            role="test assistant",
            tone="concise",
            host="codex",
            capabilities=(),
        )
        execute_plan(self.root, resolve_plan(self.root, spec))
        return destination

    def candidate(self, parent: Path, skill_id: str = "new-skill") -> Path:
        skill = parent / skill_id
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\n"
            f"name: {skill_id}\n"
            "description: Perform a bounded example task when explicitly requested by the user.\n"
            "---\n\n"
            "# Example\n\nInspect the request and report the result.\n",
            encoding="utf-8",
        )
        return skill

    def importer(self, harness: Path) -> Path:
        return (
            harness / ".agents" / "skills" / "import-external-skill" / "scripts" / "import_skill.py"
        )

    def test_auditor_rejects_dangerous_candidate_without_executing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self.candidate(root)
            scripts = candidate / "scripts"
            scripts.mkdir()
            marker = root / "executed"
            (scripts / "unsafe.py").write_text(
                f'from pathlib import Path\nPath({str(marker)!r}).write_text("ran")\n'
                'eval("1 + 1")\n',
                encoding="utf-8",
            )
            auditor = self.root / "skills" / "skill-auditor" / "scripts" / "audit_skill.py"

            result = subprocess.run(
                [sys.executable, str(auditor), str(candidate), "--json"],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertFalse(marker.exists())
            payload = json.loads(result.stdout)
            self.assertEqual(payload["verdict"], "reject")
            self.assertIn("dynamic-execution", {item["code"] for item in payload["findings"]})

    def test_external_import_adds_new_skill_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            candidate = self.candidate(parent / "source")

            result = subprocess.run(
                [
                    sys.executable,
                    str(self.importer(harness)),
                    "--root",
                    str(harness),
                    "--source",
                    str(candidate),
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((harness / ".agents" / "skills" / "new-skill" / "SKILL.md").is_file())
            receipt = yaml.safe_load(
                (harness / ".agent-harness" / "installation.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["skill_imports"][-1]["skill"], "new-skill")
            self.assertEqual(receipt["skill_imports"][-1]["source"]["kind"], "local-directory")

    def test_existing_skill_is_preserved_without_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            installed = harness / ".agents" / "skills" / "task-planning" / "SKILL.md"
            installed.write_text(installed.read_text(encoding="utf-8") + "\nLOCAL CHANGE\n")
            original = installed.read_text(encoding="utf-8")
            candidate = self.candidate(parent / "source", "task-planning")

            result = subprocess.run(
                [
                    sys.executable,
                    str(self.importer(harness)),
                    "--root",
                    str(harness),
                    "--source",
                    str(candidate),
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "preserved")
            self.assertEqual(installed.read_text(encoding="utf-8"), original)

    def test_unregistered_destination_collision_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            destination = harness / ".agents" / "skills" / "new-skill"
            destination.mkdir()
            marker = destination / "local.txt"
            marker.write_text("keep me", encoding="utf-8")
            candidate = self.candidate(parent / "source")

            result = subprocess.run(
                [
                    sys.executable,
                    str(self.importer(harness)),
                    "--root",
                    str(harness),
                    "--source",
                    str(candidate),
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "preserved")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")

    def test_zip_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            archive = parent / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escape/SKILL.md", "unsafe")

            result = subprocess.run(
                [
                    sys.executable,
                    str(self.importer(harness)),
                    "--root",
                    str(harness),
                    "--source",
                    str(archive),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("escapes destination", result.stderr)
            self.assertFalse((parent / "escape").exists())

    def test_template_import_uses_stable_tag_and_only_adds_new_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            harness = self.harness(parent)
            upstream = parent / "upstream"
            (upstream / "config").mkdir(parents=True)
            skill = self.candidate(upstream / "skills", "release-skill")
            existing_skill = self.candidate(upstream / "skills", "task-planning")
            registry = {
                "version": "1.0",
                "capabilities": [
                    {
                        "id": "release-skill",
                        "type": "skill",
                        "status": "active",
                        "path": skill.relative_to(upstream).as_posix(),
                        "description": "Import a release skill for a bounded test.",
                        "when": "Use when testing tagged template imports.",
                    },
                    {
                        "id": "task-planning",
                        "type": "skill",
                        "status": "active",
                        "path": existing_skill.relative_to(upstream).as_posix(),
                        "description": "An upstream version that must not replace local changes.",
                        "when": "Use for testing preservation.",
                    },
                ],
            }
            (upstream / "config" / "capabilities.yaml").write_text(
                yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
            )
            subprocess.run(["git", "init", "-q"], cwd=upstream, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=upstream, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"], cwd=upstream, check=True
            )
            subprocess.run(["git", "add", "."], cwd=upstream, check=True)
            subprocess.run(["git", "commit", "-qm", "release"], cwd=upstream, check=True)
            subprocess.run(["git", "tag", "v1.2.0"], cwd=upstream, check=True)
            subprocess.run(["git", "tag", "v9.0.0-beta.1"], cwd=upstream, check=True)
            installed = harness / ".agents" / "skills" / "task-planning" / "SKILL.md"
            installed.write_text(installed.read_text(encoding="utf-8") + "\nLOCAL CHANGE\n")
            original = installed.read_text(encoding="utf-8")
            importer = (
                harness
                / ".agents"
                / "skills"
                / "import-template-skills"
                / "scripts"
                / "import_from_release.py"
            )

            check = subprocess.run(
                [
                    sys.executable,
                    str(importer),
                    "--root",
                    str(harness),
                    "--repository",
                    str(upstream),
                    "--release",
                    "latest",
                    "--check",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertEqual(json.loads(check.stdout)["new"], ["release-skill"])
            self.assertFalse((harness / ".agents" / "skills" / "release-skill").exists())

            result = subprocess.run(
                [
                    sys.executable,
                    str(importer),
                    "--root",
                    str(harness),
                    "--repository",
                    str(upstream),
                    "--release",
                    "latest",
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["release"], "v1.2.0")
            self.assertEqual(payload["imported"], ["release-skill"])
            self.assertIn("task-planning", payload["preserved"])
            self.assertEqual(installed.read_text(encoding="utf-8"), original)
            receipt = yaml.safe_load(
                (harness / ".agent-harness" / "installation.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                receipt["skill_imports"][-1]["source"]["kind"],
                "agent-template-release",
            )


if __name__ == "__main__":
    unittest.main()
