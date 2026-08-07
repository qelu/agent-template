"""Load and validate the canonical trusted tool-policy registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from harness.configuration import load_yaml


class ToolPolicyError(ValueError):
    """Raised when trusted tool policy is missing, ambiguous, or invalid."""


def load_tool_policies(root: Path) -> dict[str, dict[str, Any]]:
    """Return trusted tool policies keyed by exact adapter tool ID."""
    try:
        payload = load_yaml(root / "config" / "tools.yaml")
        schema = json.loads(
            (root / "config" / "schemas" / "tool-policy.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, TypeError, SchemaError) as exc:
        raise ToolPolicyError(f"Invalid trusted tool-policy schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise ToolPolicyError(f"Invalid trusted tool-policy registry: {details}")

    policies: dict[str, dict[str, Any]] = {}
    for policy in payload["tools"]:
        tool_id = policy["id"]
        if tool_id in policies:
            raise ToolPolicyError(f"Duplicate trusted tool ID: {tool_id}")
        _validate_semantics(policy)
        policies[tool_id] = policy
    return policies


def _validate_semantics(policy: dict[str, Any]) -> None:
    tool_id = policy["id"]
    filesystem = policy["filesystem"]
    paths = filesystem["path_arguments"]
    if filesystem["access"] == "none" and paths:
        raise ToolPolicyError(f"{tool_id}: filesystem path arguments require filesystem access")
    if filesystem["access"] != "none" and not paths:
        raise ToolPolicyError(f"{tool_id}: filesystem access requires path arguments")
    if filesystem["access"] == "destructive" and not filesystem["require_exact_targets"]:
        raise ToolPolicyError(f"{tool_id}: destructive access requires exact targets")

    shell = policy["shell"]
    command_fields = shell["command_arguments"]
    if shell["access"] == "none" and command_fields:
        raise ToolPolicyError(f"{tool_id}: shell fields require execute access")
    if shell["access"] == "execute" and not command_fields:
        raise ToolPolicyError(f"{tool_id}: shell access requires command fields")

    network = policy["network"]
    host_fields = network["host_arguments"]
    allowed_hosts = network["allowed_hosts"]
    if network["access"] == "none" and (host_fields or allowed_hosts):
        raise ToolPolicyError(f"{tool_id}: network fields require outbound access")
    if network["access"] == "outbound" and (not host_fields or not allowed_hosts):
        raise ToolPolicyError(f"{tool_id}: outbound access requires host fields and allowed hosts")
    if network["access"] == "none" and policy["private_data_egress"] != "deny":
        raise ToolPolicyError(f"{tool_id}: private-data egress requires outbound access")
