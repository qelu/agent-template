import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from harness.registry import (
    CapabilityError,
    CapabilityLifecycle,
    active_capabilities,
    attested_active_capability,
    capability_definition_digest,
    load_capabilities,
    proposed_capability,
)


class Sequence:
    def __init__(self, *values: str) -> None:
        self.values = iter(values)

    def __call__(self) -> str:
        return next(self.values)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        source = Path(__file__).resolve().parent.parent
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "config" / "schemas").mkdir(parents=True)
        (self.root / "skills" / "sample").mkdir(parents=True)
        (self.root / "skills" / "sample" / "SKILL.md").write_text("sample\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_sample.py").write_text("", encoding="utf-8")
        schema = json.loads(
            (source / "config" / "schemas" / "capability.schema.json").read_text(encoding="utf-8")
        )
        (self.root / "config" / "schemas" / "capability.schema.json").write_text(
            json.dumps(schema), encoding="utf-8"
        )
        self.capability = proposed_capability(
            self.root,
            capability_id="sample",
            capability_type="skill",
            version="1.0.0",
            path="skills/sample",
            description="A valid sample capability.",
            risk_level="low",
            owner="test-owner",
            actor="human:test",
        )

    def write_registry(self, capabilities: list[dict[str, object]]) -> None:
        payload = {"version": "2.0", "capabilities": capabilities}
        (self.root / "config" / "capabilities.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )

    def active(self, capability_id: str = "sample") -> dict[str, object]:
        return attested_active_capability(
            self.root,
            capability_id=capability_id,
            capability_type="skill",
            version="1.0.0",
            path="skills/sample",
            description="A valid sample capability.",
            risk_level="low",
            owner="test-owner",
            evaluation_suite="tests/test_sample.py",
            approved_by="human:test",
            approval_id=f"approval-{capability_id}",
        )

    def manager(self) -> CapabilityLifecycle:
        return CapabilityLifecycle(
            self.root,
            clock=Sequence(
                "2026-08-08T10:00:00Z",
                "2026-08-08T10:01:00Z",
                "2026-08-08T10:02:00Z",
                "2026-08-08T10:03:00Z",
                "2026-08-08T10:04:00Z",
                "2026-08-08T10:05:00Z",
                "2026-08-08T10:06:00Z",
                "2026-08-08T10:07:00Z",
            ),
            id_factory=Sequence("approval-1"),
        )

    @staticmethod
    def refresh_definition(capability: dict[str, Any]) -> None:
        capability["definition_digest"] = capability_definition_digest(capability)
        if capability["activation"] is not None:
            capability["activation"]["definition_digest"] = capability["definition_digest"]

    def test_valid_registry_and_active_filter(self) -> None:
        self.write_registry([self.capability])
        self.assertEqual(load_capabilities(self.root)[0]["id"], "sample")
        self.assertEqual(active_capabilities(self.root), [])
        self.write_registry([self.active()])
        self.assertEqual(active_capabilities(self.root)[0]["status"], "active")

    def test_runbook_is_a_governed_capability_type(self) -> None:
        runbook = copy.deepcopy(self.capability)
        runbook["type"] = "runbook"
        self.refresh_definition(runbook)
        self.write_registry([runbook])
        self.assertEqual(load_capabilities(self.root)[0]["type"], "runbook")

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

    def test_artifact_and_evaluation_drift_fail_closed(self) -> None:
        active = self.active()
        self.write_registry([active])
        (self.root / "skills" / "sample" / "SKILL.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(CapabilityError, "changed without a version"):
            load_capabilities(self.root)

        (self.root / "skills" / "sample" / "SKILL.md").write_text("sample\n", encoding="utf-8")
        (self.root / "tests" / "test_sample.py").write_text("# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(CapabilityError, "evaluation suite changed"):
            load_capabilities(self.root)

    def test_contract_drift_fails_closed(self) -> None:
        active = self.active()
        self.write_registry([active])
        active["compatibility"]["hosts"] = ["codex"]
        self.write_registry([active])
        with self.assertRaisesRegex(CapabilityError, "contract changed without a version"):
            load_capabilities(self.root)

    def test_dependencies_enforce_identity_version_status_and_cycles(self) -> None:
        dependent = copy.deepcopy(self.capability)
        dependent["id"] = "dependent"
        dependent["requires"] = [{"id": "missing", "minimum_version": "1.0.0"}]
        self.refresh_definition(dependent)
        self.write_registry([dependent])
        with self.assertRaisesRegex(CapabilityError, "Unknown dependency"):
            load_capabilities(self.root)

        other = copy.deepcopy(self.capability)
        other["id"] = "other"
        dependent["requires"] = [{"id": "other", "minimum_version": "2.0.0"}]
        self.refresh_definition(dependent)
        self.refresh_definition(other)
        self.write_registry([dependent, other])
        with self.assertRaisesRegex(CapabilityError, "version is too old"):
            load_capabilities(self.root)

        dependent["requires"] = [{"id": "other", "minimum_version": "1.0.0"}]
        other["requires"] = [{"id": "dependent", "minimum_version": "1.0.0"}]
        self.refresh_definition(dependent)
        self.refresh_definition(other)
        self.write_registry([dependent, other])
        with self.assertRaisesRegex(CapabilityError, "dependency cycle"):
            load_capabilities(self.root)

    def test_promotion_disable_restore_and_version_reset(self) -> None:
        self.capability["evaluation_suite"] = "tests/test_sample.py"
        self.refresh_definition(self.capability)
        self.write_registry([self.capability])
        manager = self.manager()
        manager.record_passing_evaluation("sample", "evaluator")
        manager.activate("sample", "human:reviewer")
        self.assertEqual(active_capabilities(self.root)[0]["status"], "active")
        manager.disable("sample", "human:reviewer", "Emergency stop")
        self.assertEqual(load_capabilities(self.root)[0]["disabled_from"], "active")
        manager.restore("sample", "human:reviewer")
        self.assertEqual(active_capabilities(self.root)[0]["status"], "active")

        (self.root / "skills" / "sample" / "SKILL.md").write_text("version two\n", encoding="utf-8")
        manager.bump_version("sample", "2.0.0", "human:reviewer")
        reset = load_capabilities(self.root)[0]
        self.assertEqual(reset["status"], "proposed")
        self.assertIsNone(reset["evaluation"])
        self.assertIsNone(reset["activation"])

    def test_activation_preserves_host_compatibility_and_deprecation_has_dependency_guard(
        self,
    ) -> None:
        active = self.active()
        dependent = copy.deepcopy(active)
        dependent["id"] = "dependent"
        dependent["activation"]["approval_id"] = "approval-dependent"
        dependent["requires"] = [{"id": "sample", "minimum_version": "1.0.0"}]
        self.refresh_definition(dependent)
        self.write_registry([active, dependent])
        with self.assertRaisesRegex(CapabilityError, "dependents block deprecation"):
            self.manager().deprecate("sample", "human:test")

        proposed = copy.deepcopy(self.capability)
        proposed["evaluation_suite"] = "tests/test_sample.py"
        proposed["compatibility"]["hosts"] = ["codex"]
        self.refresh_definition(proposed)
        self.write_registry([proposed])
        manager = self.manager()
        manager.record_passing_evaluation("sample", "evaluator")
        manager.activate("sample", "human:test")
        activated = load_capabilities(self.root)[0]
        self.assertEqual(activated["compatibility"]["hosts"], ["codex"])

    def test_emergency_disable_cascades_to_active_dependents(self) -> None:
        active = self.active()
        dependent = copy.deepcopy(active)
        dependent["id"] = "dependent"
        dependent["activation"]["approval_id"] = "approval-dependent"
        dependent["requires"] = [{"id": "sample", "minimum_version": "1.0.0"}]
        self.refresh_definition(dependent)
        self.write_registry([active, dependent])
        self.manager().disable("sample", "human:test", "Emergency stop")
        states = {item["id"]: item["status"] for item in load_capabilities(self.root)}
        self.assertEqual(states, {"sample": "disabled", "dependent": "disabled"})

    def test_removal_requires_deprecation_and_no_dependents(self) -> None:
        self.write_registry([self.active()])
        manager = self.manager()
        with self.assertRaisesRegex(CapabilityError, "requires deprecated"):
            manager.remove("sample")
        manager.deprecate("sample", "human:test")
        manager.remove("sample")
        self.assertEqual(load_capabilities(self.root), [])
        self.assertTrue((self.root / "skills" / "sample").exists())


if __name__ == "__main__":
    unittest.main()
