"""Load and validate the provider-neutral deployment profile."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from harness.configuration import load_yaml


class DeploymentError(ValueError):
    """Raised when the deployment profile violates its schema."""


def load_deployment(root: Path) -> dict[str, Any]:
    """Load and schema-validate the deployment profile."""
    payload = load_yaml(root / "config" / "deployment.yaml")
    schema = json.loads(
        (root / "config" / "schemas" / "deployment.schema.json").read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise DeploymentError(f"Invalid deployment profile: {details}")
    adapter = payload["runtime"]["adapter"]
    if adapter not in {"none", "reference"}:
        raise DeploymentError(f"Runtime adapter is not implemented: {adapter}")
    return payload


def validate_runtime_activation(
    profile: dict[str, Any], capabilities: list[dict[str, Any]]
) -> None:
    """Require an executable adapter before any runtime hook can activate."""
    active_hooks = [
        item["id"]
        for item in capabilities
        if item.get("type") == "hook" and item.get("status") == "active"
    ]
    if active_hooks and profile["runtime"]["adapter"] == "none":
        joined = ", ".join(sorted(active_hooks))
        raise DeploymentError(f"Active runtime hooks require an adapter: {joined}")
