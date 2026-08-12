import re
import unittest
from pathlib import Path

import yaml


class SkillContractTests(unittest.TestCase):
    def test_registered_skills_have_minimal_valid_contracts(self) -> None:
        root = Path(__file__).resolve().parent.parent
        registry = yaml.safe_load(
            (root / "config" / "capabilities.yaml").read_text(encoding="utf-8")
        )
        skills = [item for item in registry["capabilities"] if item["type"] == "skill"]
        self.assertGreater(len(skills), 0)
        for skill in skills:
            with self.subTest(skill=skill["id"]):
                path = root / skill["path"] / "SKILL.md"
                text = path.read_text(encoding="utf-8")
                match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
                self.assertIsNotNone(match)
                assert match is not None
                metadata = yaml.safe_load(match.group(1))
                self.assertEqual(set(metadata), {"name", "description"})
                self.assertEqual(metadata["name"], skill["id"])
                self.assertTrue(metadata["description"].strip())


if __name__ == "__main__":
    unittest.main()
