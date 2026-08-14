import re
import unittest
from pathlib import Path

import yaml


class PostWorkReviewSkillTests(unittest.TestCase):
    @property
    def skill(self) -> Path:
        return Path(__file__).resolve().parent.parent / "skills" / "post-work-review"

    def test_trigger_covers_major_work_and_first_service_use(self) -> None:
        text = (self.skill / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match)
        assert match is not None
        description = yaml.safe_load(match.group(1))["description"]

        self.assertIn("major piece of work", description)
        self.assertIn("unfamiliar service", description)

    def test_review_separates_required_maintenance_from_new_scope(self) -> None:
        text = (self.skill / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Required now", text)
        self.assertIn("Propose next", text)
        self.assertIn("No change", text)
        self.assertIn("Do not install tools", text)

    def test_matrix_covers_each_durable_surface_and_jira_example(self) -> None:
        text = (self.skill / "references" / "review-matrix.md").read_text(encoding="utf-8")

        for surface in (
            "ADR",
            "Technical debt",
            "Skill",
            "Hook or policy",
            "Runbook",
            "Integration",
            "Configuration or schema",
            "Test or eval",
            "User documentation",
        ):
            with self.subTest(surface=surface):
                self.assertIn(f"| {surface} |", text)
        self.assertIn("Atlassian Rovo MCP", text)
        self.assertIn("confirmation before comments, assignments, or transitions", text)


if __name__ == "__main__":
    unittest.main()
