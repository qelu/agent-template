#!/usr/bin/env python3
"""Scaffold a proposed skill, workflow, or unregistered runbook."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.registry import proposed_capability  # noqa: E402

TEMPLATES = ROOT / "templates"

CAPABILITY_TARGETS = {
    "skill": ("skills", "skill", "low"),
    "workflow": ("workflows", "workflow", "medium"),
}


def normalize(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise SystemExit("ID must contain a letter or digit")
    return result


def replace_tree(path: Path, replacements: dict[str, str]) -> None:
    for file in path.rglob("*"):
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        file.write_text(text, encoding="utf-8")


def scaffold_runbook(extension_id: str, name: str) -> Path:
    destination = ROOT / "knowledge" / "runbooks" / f"{extension_id}.md"
    if destination.exists():
        raise SystemExit(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = (TEMPLATES / "runbook-template.md").read_text(encoding="utf-8")
    destination.write_text(content.replace("Procedure title", name), encoding="utf-8")
    return destination


def scaffold_capability(capability_type: str, extension_id: str, name: str) -> Path:
    folder, template_name, risk_level = CAPABILITY_TARGETS[capability_type]
    source = TEMPLATES / template_name
    destination = ROOT / folder / extension_id
    if destination.exists():
        raise SystemExit(f"Destination already exists: {destination}")
    registry_path = ROOT / "config" / "capabilities.yaml"
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    capabilities = data.setdefault("capabilities", [])
    if any(item.get("id") == extension_id for item in capabilities):
        raise SystemExit(f"Capability ID already exists: {extension_id}")

    shutil.copytree(source, destination)
    replace_tree(
        destination,
        {
            "example-skill": extension_id,
            "Example Skill": name,
            "example-workflow": extension_id,
        },
    )
    suite = ROOT / "tests" / f"test_capability_{extension_id.replace('-', '_')}.py"
    if suite.exists():
        raise SystemExit(f"Evaluation suite already exists: {suite}")
    suite.write_text(
        "import unittest\n\n\n"
        f"class {''.join(part.title() for part in extension_id.split('-'))}CapabilityTests"
        "(unittest.TestCase):\n"
        "    def test_behavioral_contract(self) -> None:\n"
        '        self.fail("Replace with a behavioral evaluation before promotion")\n\n\n'
        'if __name__ == "__main__":\n'
        "    unittest.main()\n",
        encoding="utf-8",
    )
    capabilities.append(
        proposed_capability(
            capability_id=extension_id,
            capability_type=capability_type,
            version="0.1.0",
            path=str(destination.relative_to(ROOT)),
            description=f"Proposed capability for {name}.",
            risk_level=risk_level,
            evaluation=str(suite.relative_to(ROOT)),
        )
    )
    registry_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, choices=["runbook", *sorted(CAPABILITY_TARGETS)])
    parser.add_argument("--id", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    extension_id = normalize(args.id)
    if args.type == "runbook":
        destination = scaffold_runbook(extension_id, args.name)
        print(f"Created runbook at {destination.relative_to(ROOT)}")
        return

    destination = scaffold_capability(args.type, extension_id, args.name)
    print(f"Created proposed {args.type} at {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
