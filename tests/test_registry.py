import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.registry import CapabilityError, active_capabilities, load_capabilities  # noqa: E402


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config" / "schemas").mkdir(parents=True)
        (self.root / "skills" / "sample").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_sample.py").write_text("", encoding="utf-8")
        schema = json.loads(
            (ROOT / "config" / "schemas" / "capability.schema.json").read_text(
                encoding="utf-8"
            )
        )
        (self.root / "config" / "schemas" / "capability.schema.json").write_text(
            json.dumps(schema), encoding="utf-8"
        )
        self.capability = {
            "id": "sample",
            "type": "skill",
            "version": "1.0.0",
            "status": "active",
            "path": "skills/sample",
            "description": "A valid sample capability.",
            "risk_level": "low",
            "owner": "test-owner",
            "requires": [],
            "evaluation_suite": "tests/test_sample.py",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_registry(self, capabilities: list[dict[str, object]]) -> None:
        payload = {"version": "1.0", "capabilities": capabilities}
        (self.root / "config" / "capabilities.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )

    def test_valid_registry_loads(self) -> None:
        self.write_registry([self.capability])
        self.assertEqual(load_capabilities(self.root)[0]["id"], "sample")
        self.assertEqual(active_capabilities(self.root)[0]["status"], "active")

    def test_schema_rejects_unknown_fields(self) -> None:
        invalid = copy.deepcopy(self.capability)
        invalid["unexpected"] = True
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "Additional properties"):
            load_capabilities(self.root)

    def test_duplicate_ids_are_rejected(self) -> None:
        self.write_registry([self.capability, copy.deepcopy(self.capability)])
        with self.assertRaisesRegex(CapabilityError, "Duplicate capability ID"):
            load_capabilities(self.root)

    def test_active_capability_requires_evaluation_suite(self) -> None:
        invalid = copy.deepcopy(self.capability)
        invalid["evaluation_suite"] = None
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "requires an evaluation suite"):
            load_capabilities(self.root)

    def test_unknown_dependency_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.capability)
        invalid["requires"] = ["missing-capability"]
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "Unknown dependency"):
            load_capabilities(self.root)

    def test_parent_traversal_is_rejected_by_schema(self) -> None:
        invalid = copy.deepcopy(self.capability)
        invalid["path"] = "../outside"
        self.write_registry([invalid])
        with self.assertRaisesRegex(CapabilityError, "Invalid capability registry"):
            load_capabilities(self.root)


if __name__ == "__main__":
    unittest.main()
