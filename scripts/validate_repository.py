#!/usr/bin/env python3
"""Validate the host-native template, capability registry, and initializer."""

import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.configuration import ConfigurationError, load_yaml  # noqa: E402
from harness.initializer import (  # noqa: E402
    HOSTS,
    InitializerError,
    capability_choices,
    load_initializer_config,
)
from harness.policy import PolicyError, load_policy  # noqa: E402
from harness.registry import CapabilityError, load_capabilities  # noqa: E402

PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".toml", ".py"}
IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    "runtime",
}
REQUIRED = (
    "agent/AGENT.md",
    "config/capabilities.yaml",
    "config/initializer.yaml",
    "config/persona.yaml",
    "config/policies.yaml",
    "config/schemas/installation.schema.json",
    "harness/configuration.py",
    "harness/initializer.py",
    "harness/policy.py",
    "harness/registry.py",
    "scripts/guardrails/core.py",
    "scripts/guardrails/codex.py",
    "scripts/guardrails/claude_code.py",
    "scripts/guardrails/antigravity.py",
    "scripts/initialize_agent.py",
    "scripts/update_scope.py",
    "scripts/validate_harness.py",
    "scripts/validate_repository.py",
    "templates/generated-pyproject.toml",
)


def repository_text_files(root: Path) -> Iterator[Path]:
    for current, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in IGNORED_DIRECTORIES]
        current_path = Path(current)
        for filename in filenames:
            path = current_path / filename
            if path.suffix in TEXT_SUFFIXES:
                yield path


def validate_skill(path: Path) -> list[str]:
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        return [f"Missing {skill_file.relative_to(ROOT)}"]
    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return [f"Invalid frontmatter in {skill_file.relative_to(ROOT)}"]
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return [f"{skill_file.relative_to(ROOT)}: {exc}"]
    errors: list[str] = []
    if not isinstance(metadata, dict) or set(metadata) != {"name", "description"}:
        errors.append(
            f"{skill_file.relative_to(ROOT)} frontmatter must contain name and description"
        )
    elif metadata.get("name") != path.name:
        errors.append(f"Skill name must match folder: {path.name}")
    return errors


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            errors.append(f"Missing required path: {relative}")

    for relative in ("config/initializer.yaml", "config/persona.yaml", "config/policies.yaml"):
        try:
            load_yaml(ROOT / relative)
        except ConfigurationError as exc:
            errors.append(str(exc))

    try:
        json.loads((ROOT / "config" / "policies.yaml").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"config/policies.yaml must remain JSON-compatible YAML: {exc}")

    try:
        initializer = load_initializer_config(ROOT)
        if initializer["defaults"]["host"] not in HOSTS:
            errors.append("Initializer default host is unsupported")
        capability_choices(ROOT)
    except (InitializerError, OSError, ValueError) as exc:
        errors.append(str(exc))

    receipt = ROOT / ".agent-harness" / "installation.yaml"
    if receipt.exists():
        try:
            schema = json.loads((ROOT / "config/schemas/installation.schema.json").read_text())
            payload = yaml.safe_load(receipt.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(payload)
        except (jsonschema.ValidationError, OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"Invalid installation receipt: {exc}")

    try:
        capabilities = load_capabilities(ROOT)
    except (CapabilityError, ConfigurationError, OSError, ValueError) as exc:
        errors.append(str(exc))
        capabilities = []

    try:
        load_policy(ROOT)
    except (PolicyError, ConfigurationError, OSError, ValueError) as exc:
        errors.append(str(exc))

    registered_skill_paths = {
        ROOT / item["path"] for item in capabilities if item.get("type") == "skill"
    }
    filesystem_skill_paths = {path for path in (ROOT / "skills").glob("*") if path.is_dir()}
    for unregistered in sorted(filesystem_skill_paths - registered_skill_paths):
        errors.append(f"Unregistered skill directory: {unregistered.relative_to(ROOT)}")
    for skill_path in sorted(registered_skill_paths):
        errors.extend(validate_skill(skill_path))

    if not (ROOT / ".agent-template").exists():
        for path in repository_text_files(ROOT):
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if PLACEHOLDER.search(content):
                errors.append(f"Unresolved placeholder in {path.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
