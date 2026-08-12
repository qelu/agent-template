"""Validate the lightweight source capability registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from harness.configuration import load_yaml


class CapabilityError(ValueError):
    """Raised when the capability registry violates its contract."""


def load_capabilities(root: Path) -> list[dict[str, Any]]:
    payload = load_yaml(root / "config" / "capabilities.yaml")
    schema = json.loads(
        (root / "config" / "schemas" / "capability.schema.json").read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise CapabilityError(
            "Invalid capability registry: " + "; ".join(error.message for error in errors)
        )

    capabilities = payload["capabilities"]
    by_id: dict[str, dict[str, Any]] = {}
    for capability in capabilities:
        capability_id = capability["id"]
        if capability_id in by_id:
            raise CapabilityError(f"Duplicate capability ID: {capability_id}")
        by_id[capability_id] = capability
        _contained_path(root, capability["path"], "artifact")
        evaluation = capability["evaluation"]
        if evaluation is not None:
            path = _contained_path(root, evaluation, "evaluation")
            if not path.is_file():
                raise CapabilityError(f"Evaluation suite does not exist: {evaluation}")
        if capability["status"] == "active" and evaluation is None:
            raise CapabilityError(f"Active capability requires an evaluation: {capability_id}")

    _validate_dependencies(by_id)
    _validate_cycles(by_id)
    return capabilities


def active_capabilities(root: Path) -> list[dict[str, Any]]:
    return [item for item in load_capabilities(root) if item["status"] == "active"]


def proposed_capability(
    *,
    capability_id: str,
    capability_type: str,
    version: str,
    path: str,
    description: str,
    risk_level: str,
    evaluation: str | None,
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "type": capability_type,
        "version": version,
        "status": "proposed",
        "path": path,
        "description": description,
        "risk_level": risk_level,
        "hosts": ["portable", "codex", "claude-code", "antigravity"],
        "requires": [],
        "evaluation": evaluation,
    }


def _contained_path(root: Path, relative: str, label: str) -> Path:
    target = (root / relative).resolve()
    resolved_root = root.resolve()
    if target == resolved_root or resolved_root not in target.parents:
        raise CapabilityError(f"Capability {label} path escapes repository: {relative}")
    if not target.exists():
        raise CapabilityError(f"Capability {label} does not exist: {relative}")
    return target


def _semver(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _validate_dependencies(by_id: dict[str, dict[str, Any]]) -> None:
    for capability in by_id.values():
        for requirement in capability["requires"]:
            dependency = by_id.get(requirement["id"])
            if dependency is None:
                raise CapabilityError(f"Unknown dependency: {requirement['id']}")
            if _semver(dependency["version"]) < _semver(requirement["minimum_version"]):
                raise CapabilityError(f"Dependency version is too old: {requirement['id']}")
            if capability["status"] == "active" and dependency["status"] != "active":
                raise CapabilityError(f"Active dependency required: {requirement['id']}")


def _validate_cycles(by_id: dict[str, dict[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(capability_id: str) -> None:
        if capability_id in visiting:
            raise CapabilityError(f"Capability dependency cycle contains: {capability_id}")
        if capability_id in visited:
            return
        visiting.add(capability_id)
        for requirement in by_id[capability_id]["requires"]:
            visit(requirement["id"])
        visiting.remove(capability_id)
        visited.add(capability_id)

    for capability_id in by_id:
        visit(capability_id)
