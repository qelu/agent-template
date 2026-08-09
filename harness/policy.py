"""Trusted authorization-policy lookup without caller-supplied classifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from harness.configuration import load_yaml


class PolicyError(ValueError):
    """Raised when trusted authorization policy is missing or unsupported."""


def load_policy(root: Path) -> dict[str, Any]:
    """Load and schema-validate trusted authorization and scope policy."""
    try:
        payload = load_yaml(root / "config" / "policies.yaml")
        schema = json.loads(
            (root / "config" / "schemas" / "policy.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, TypeError, SchemaError) as exc:
        raise PolicyError(f"Invalid trusted authorization policy schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise PolicyError(f"Invalid trusted authorization policy: {details}")
    return payload


def authorization_requirement(policy: dict[str, Any], action_class: str) -> str:
    """Resolve authorization only from trusted configuration."""
    authorization = policy.get("authorization")
    if not isinstance(authorization, dict):
        raise PolicyError("Authorization policy must be a mapping")
    requirement = authorization.get(action_class)
    if requirement not in {"autonomous", "explicit_approval"}:
        raise PolicyError(f"Unknown authorization classification: {action_class}")
    return requirement
