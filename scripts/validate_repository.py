#!/usr/bin/env python3
"""Validate the minimal template, configuration, capabilities, and skills."""

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.configuration import ConfigurationError, load_yaml  # noqa: E402
from harness.approvals import ApprovalError, ApprovalStore  # noqa: E402
from harness.deployment import (  # noqa: E402
    DeploymentError,
    load_deployment,
    validate_runtime_activation,
)
from harness.registry import CapabilityError, load_capabilities  # noqa: E402
from harness.policy import PolicyError, load_policy  # noqa: E402
from harness.runtime import RuntimeBoundaryError, validate_runtime_schemas  # noqa: E402
from harness.tool_policy import ToolPolicyError, load_tool_policies  # noqa: E402

PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".toml", ".py"}
IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
}
REQUIRED = (
    "agent/AGENT.md",
    "agent/config.yaml",
    "config/capabilities.yaml",
    "config/context-routes.yaml",
    "config/deployment.yaml",
    "config/persona.yaml",
    "config/policies.yaml",
    "config/schemas/capability.schema.json",
    "config/schemas/deployment.schema.json",
    "config/schemas/approval.schema.json",
    "config/schemas/post-tool-event.schema.json",
    "config/schemas/policy.schema.json",
    "config/schemas/pre-tool-event.schema.json",
    "config/schemas/tool-policy.schema.json",
    "config/tools.yaml",
    "harness/approvals.py",
    "harness/guarded_runtime.py",
    "harness/guardrails.py",
    "harness/reference_adapter.py",
    "harness/runtime.py",
    "harness/runtime_factory.py",
    "harness/tool_policy.py",
    "scripts/initialize_agent.py",
    "scripts/create_extension.py",
)


def repository_text_files(root: Path) -> Iterator[Path]:
    for current, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in IGNORED_DIRECTORIES]
        current_path = Path(current)
        for filename in filenames:
            path = current_path / filename
            if path.suffix in TEXT_SUFFIXES:
                yield path


def load_yaml_fragment(text: str) -> dict[str, object]:
    import yaml

    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("frontmatter must be a mapping")
    return payload


def validate_skill(path: Path) -> list[str]:
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        return [f"Missing {skill_file.relative_to(ROOT)}"]
    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return [f"Invalid frontmatter in {skill_file.relative_to(ROOT)}"]
    try:
        metadata = load_yaml_fragment(match.group(1))
    except ValueError as exc:
        return [f"{skill_file.relative_to(ROOT)}: {exc}"]
    errors: list[str] = []
    if set(metadata) != {"name", "description"}:
        errors.append(f"{skill_file.relative_to(ROOT)} frontmatter must contain only name and description")
    if metadata.get("name") != path.name:
        errors.append(f"Skill name must match folder: {path.name}")
    if not str(metadata.get("description", "")).strip():
        errors.append(f"Skill description must not be empty: {path.name}")
    return errors


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            errors.append(f"Missing required path: {relative}")

    for relative in (
        "agent/config.yaml",
        "config/context-routes.yaml",
        "config/persona.yaml",
        "config/policies.yaml",
    ):
        try:
            load_yaml(ROOT / relative)
        except ConfigurationError as exc:
            errors.append(str(exc))

    try:
        capabilities = load_capabilities(ROOT)
    except (CapabilityError, ConfigurationError, OSError, ValueError) as exc:
        errors.append(str(exc))
        capabilities = []

    try:
        deployment = load_deployment(ROOT)
        validate_runtime_activation(deployment, capabilities)
    except (DeploymentError, ConfigurationError, OSError, ValueError) as exc:
        errors.append(str(exc))

    try:
        validate_runtime_schemas(ROOT)
    except (RuntimeBoundaryError, OSError, ValueError) as exc:
        errors.append(str(exc))

    try:
        load_tool_policies(ROOT)
    except (ToolPolicyError, ConfigurationError, OSError, ValueError) as exc:
        errors.append(str(exc))

    try:
        load_policy(ROOT)
    except (PolicyError, ConfigurationError, OSError, ValueError) as exc:
        errors.append(str(exc))

    try:
        ApprovalStore(ROOT)
    except (ApprovalError, OSError, ValueError) as exc:
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
