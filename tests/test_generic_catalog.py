import os
import subprocess
import unittest
from pathlib import Path


class GenericCatalogTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def test_generic_skills_have_distinct_operational_triggers(self) -> None:
        dependency = (self.root / "skills/dependency-change-review/SKILL.md").read_text()
        incident = (self.root / "skills/incident-triage/SKILL.md").read_text()

        self.assertIn("lockfile changes", dependency)
        self.assertIn("supply-chain risk", dependency)
        self.assertIn("preserving evidence", incident)
        self.assertIn("unexplained production symptoms", incident)

    def test_runbooks_include_required_operational_sections(self) -> None:
        for relative in (
            "knowledge/runbooks/incident-response.md",
            "knowledge/runbooks/integration-lifecycle.md",
        ):
            text = (self.root / relative).read_text(encoding="utf-8")
            with self.subTest(runbook=relative):
                for heading in (
                    "## Purpose",
                    "## Scope and risk",
                    "## Prerequisites and approvals",
                    "## Procedure",
                    "## Validation",
                    "## Rollback",
                    "## Troubleshooting",
                    "## References",
                ):
                    self.assertIn(heading, text)

    def test_secret_hook_uses_official_staged_scan_and_fails_without_tool(self) -> None:
        hook = self.root / ".githooks/pre-commit"
        text = hook.read_text(encoding="utf-8")

        if os.name == "posix":
            self.assertTrue(hook.stat().st_mode & 0o100)
        self.assertIn("command -v gitleaks", text)
        self.assertIn(
            "gitleaks git --pre-commit --redact --staged --verbose",
            text,
        )
        if os.name != "posix":
            return
        environment = {**os.environ, "PATH": "/usr/bin:/bin"}
        result = subprocess.run(
            [str(hook)],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("gitleaks is required", result.stderr)


if __name__ == "__main__":
    unittest.main()
