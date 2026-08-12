import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from harness.registry import (
    CapabilityError,
    active_capabilities,
    load_capabilities,
    proposed_capability,
)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        source = Path(__file__).resolve().parent.parent
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "config" / "schemas").mkdir(parents=True)
        (self.root / "skills" / "sample").mkdir(parents=True)
        (self.root / "skills" / "sample" / "SKILL.md").write_text("sample\n")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_sample.py").write_text("")
        schema = json.loads((source / "config" / "schemas" / "capability.schema.json").read_text())
        (self.root / "config" / "schemas" / "capability.schema.json").write_text(json.dumps(schema))
        self.capability = proposed_capability(
            capability_id="sample",
            capability_type="skill",
            version="1.0.0",
            path="skills/sample",
            description="A valid sample capability.",
            risk_level="low",
            evaluation="tests/test_sample.py",
        )

    def write_registry(self, capabilities: list[dict[str, object]]) -> None:
        (self.root / "config" / "capabilities.yaml").write_text(
            yaml.safe_dump({"version": "3.0", "capabilities": capabilities}, sort_keys=False)
        )

    def test_valid_registry_and_active_filter(self) -> None:
        self.write_registry([self.capability])
        self.assertEqual(load_capabilities(self.root)[0]["id"], "sample")
        self.assertEqual(active_capabilities(self.root), [])
        self.capability["status"] = "active"
        self.write_registry([self.capability])
        self.assertEqual(active_capabilities(self.root)[0]["id"], "sample")

    def test_schema_rejects_unknown_fields_and_parent_traversal(self) -> None:
        invalid = copy.deepcopy(self.capability)
        invalid["unexpected"] = True
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "Additional properties"):
            load_capabilities(self.root)
        invalid.pop("unexpected")
        invalid["path"] = "../outside"
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "Invalid capability registry"):
            load_capabilities(self.root)

    def test_active_capability_requires_evaluation(self) -> None:
        self.capability["status"] = "active"
        self.capability["evaluation"] = None
        self.write_registry([self.capability])
        with self.assertRaisesRegex(CapabilityError, "requires an evaluation"):
            load_capabilities(self.root)

    def test_dependencies_enforce_identity_version_status_and_cycles(self) -> None:
        dependent = copy.deepcopy(self.capability)
        dependent["id"] = "dependent"
        dependent["requires"] = [{"id": "missing", "minimum_version": "1.0.0"}]
        self.write_registry([dependent])
        with self.assertRaisesRegex(CapabilityError, "Unknown dependency"):
            load_capabilities(self.root)

        other = copy.deepcopy(self.capability)
        other["id"] = "other"
        dependent["requires"] = [{"id": "other", "minimum_version": "2.0.0"}]
        self.write_registry([dependent, other])
        with self.assertRaisesRegex(CapabilityError, "version is too old"):
            load_capabilities(self.root)

        dependent["requires"] = [{"id": "other", "minimum_version": "1.0.0"}]
        other["requires"] = [{"id": "dependent", "minimum_version": "1.0.0"}]
        self.write_registry([dependent, other])
        with self.assertRaisesRegex(CapabilityError, "dependency cycle"):
            load_capabilities(self.root)


if __name__ == "__main__":
    unittest.main()
