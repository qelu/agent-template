import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from harness.initializer import InitializationSpec, execute_plan, resolve_plan


class MapSkillCommandTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def script(self) -> Path:
        return self.root / "skills" / "map-skill-command" / "scripts" / "map_command.py"

    def harness(self, parent: Path, host: str) -> Path:
        destination = parent / host
        spec = InitializationSpec(
            destination=destination,
            name="Command Test",
            agent_id="command-test",
            goal="Test command aliases.",
            role="test assistant",
            tone="concise",
            host=host,
            documentation_provider="none",
            capabilities=("evidence-gathering",),
        )
        execute_plan(self.root, resolve_plan(self.root, spec))
        return destination

    def invoke(
        self, harness: Path, command: str, skill: str = "evidence-gathering"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--root",
                str(harness),
                "--command",
                command,
                "--skill",
                skill,
                "--description",
                "Gather evidence for this request.",
            ],
            capture_output=True,
            text=True,
        )

    def test_skill_resolves_its_registered_helper_instead_of_a_root_script(self) -> None:
        instructions = (self.script.parent.parent / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("<registered-skill-path>/scripts/map_command.py", instructions)
        self.assertIn("/path/to/harness/scripts/map_command.py", instructions)
        self.assertIn("not exist", instructions)

    def test_creates_native_alias_skill_and_registers_it_for_each_host(self) -> None:
        roots = {
            "portable": Path(".agents/skills"),
            "codex": Path(".agents/skills"),
            "claude-code": Path(".claude/skills"),
            "antigravity": Path(".agents/skills"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            for host, skill_root in roots.items():
                with self.subTest(host=host):
                    harness = self.harness(parent, host)
                    result = self.invoke(harness, "/facts")
                    alias = harness / skill_root / "facts"
                    metadata = yaml.safe_load(
                        (harness / "config" / "capabilities.yaml").read_text(encoding="utf-8")
                    )
                    validation = subprocess.run(
                        [sys.executable, str(harness / "scripts" / "validate_harness.py")],
                        cwd=harness,
                        capture_output=True,
                        text=True,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(
                        "../evidence-gathering/SKILL.md", (alias / "SKILL.md").read_text()
                    )
                    self.assertIn("facts", {item["id"] for item in metadata["capabilities"]})
                    self.assertEqual(validation.returncode, 0, validation.stderr)
                    self.assertEqual(
                        (alias / "agents" / "openai.yaml").exists(), host in {"portable", "codex"}
                    )

    def test_rejects_built_ins_duplicates_missing_skills_and_self_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = self.harness(Path(temporary), "portable")
            built_in = self.invoke(harness, "review")
            missing = self.invoke(harness, "facts", "missing-skill")
            self_alias = self.invoke(harness, "evidence-gathering")
            created = self.invoke(harness, "facts")
            duplicate = self.invoke(harness, "facts")

        self.assertIn("built-in", built_in.stderr)
        self.assertIn("not an installed skill", missing.stderr)
        self.assertIn("already exists", self_alias.stderr)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertIn("already exists", duplicate.stderr)


if __name__ == "__main__":
    unittest.main()
