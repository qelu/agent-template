"""Load and validate the canonical capability registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from harness.configuration import load_yaml


class CapabilityError(ValueError):
    """Raised when the capability registry violates its contract."""


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def _contained_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise CapabilityError(f"Capability path escapes repository root: {relative}") from exc
    return target


def load_capabilities(root: Path) -> list[dict[str, Any]]:
    """Load, schema-validate, and cross-check all declared capabilities."""
    registry_path = root / "config" / "capabilities.yaml"
    schema_path = root / "config" / "schemas" / "capability.schema.json"
    payload = load_yaml(registry_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(_format_schema_error(error) for error in errors)
        raise CapabilityError(f"Invalid capability registry: {details}")

    capabilities = payload["capabilities"]
    by_id: dict[str, dict[str, Any]] = {}
    for capability in capabilities:
        capability_id = capability["id"]
        if capability_id in by_id:
            raise CapabilityError(f"Duplicate capability ID: {capability_id}")
        by_id[capability_id] = capability

        target = _contained_path(root, capability["path"])
        if not target.exists():
            raise CapabilityError(
                f"Capability path does not exist for {capability_id}: {capability['path']}"
            )

        suite = capability["evaluation_suite"]
        if capability["status"] in {"tested", "active"} and suite is None:
            raise CapabilityError(f"{capability_id} requires an evaluation suite before activation")
        if suite is not None and not _contained_path(root, suite).is_file():
            raise CapabilityError(f"Evaluation suite does not exist for {capability_id}: {suite}")

    for capability in capabilities:
        for dependency_id in capability["requires"]:
            dependency = by_id.get(dependency_id)
            if dependency is None:
                raise CapabilityError(
                    f"Unknown dependency for {capability['id']}: {dependency_id}"
                )
            if capability["status"] == "active" and dependency["status"] != "active":
                raise CapabilityError(
                    f"Active capability {capability['id']} requires inactive {dependency_id}"
                )

    return capabilities


def active_capabilities(root: Path) -> list[dict[str, Any]]:
    """Return active capabilities from the canonical registry."""
    return [item for item in load_capabilities(root) if item["status"] == "active"]
