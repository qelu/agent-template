import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from harness.registry import (
    CapabilityError,
    active_capabilities,
    experimental_capability,
    load_capabilities,
)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        (self.root / "skills" / "sample").mkdir(parents=True)
        self.capability = experimental_capability(
            capability_id="sample",
            capability_type="skill",
            path="skills/sample",
            description="A valid sample capability.",
            when="Use when sample behavior is required.",
        )

    def write_registry(self, capabilities: list[dict[str, object]]) -> None:
        (self.root / "config" / "capabilities.yaml").write_text(
            yaml.safe_dump({"version": "1.0", "capabilities": capabilities}, sort_keys=False)
        )

    def test_valid_registry_and_active_filter(self) -> None:
        self.write_registry([self.capability])
        self.assertEqual(load_capabilities(self.root)[0]["id"], "sample")
        self.assertEqual(active_capabilities(self.root), [])
        self.capability["status"] = "active"
        self.write_registry([self.capability])
        self.assertEqual(active_capabilities(self.root)[0]["id"], "sample")

    def test_rejects_unknown_fields_and_parent_traversal(self) -> None:
        invalid = copy.deepcopy(self.capability)
        invalid["risk_level"] = "low"
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "invalid fields"):
            load_capabilities(self.root)
        invalid.pop("risk_level")
        invalid["path"] = "../outside"
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "escapes repository"):
            load_capabilities(self.root)

    def test_statuses_are_intentionally_small(self) -> None:
        for status in ("active", "experimental", "disabled"):
            with self.subTest(status=status):
                candidate = copy.deepcopy(self.capability)
                candidate["status"] = status
                self.write_registry([candidate])
                self.assertEqual(load_capabilities(self.root)[0]["status"], status)
        invalid = copy.deepcopy(self.capability)
        invalid["status"] = "proposed"
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "Invalid capability status"):
            load_capabilities(self.root)


if __name__ == "__main__":
    unittest.main()
