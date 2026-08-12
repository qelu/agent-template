"""Validate the lightweight capability discovery registry."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from harness.configuration import load_yaml


CAPABILITY_FIELDS = {"id", "type", "status", "path", "description", "when"}
CAPABILITY_TYPES = {"skill", "workflow", "hook", "runbook", "validator", "mcp-server"}
CAPABILITY_STATUSES = {"active", "experimental", "disabled"}
CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CapabilityError(ValueError):
    """Raised when the capability registry violates its contract."""


def load_capabilities(root: Path) -> list[dict[str, Any]]:
    payload = load_yaml(root / "config" / "capabilities.yaml")
    if set(payload) != {"version", "capabilities"} or payload.get("version") != "1.0":
        raise CapabilityError("Capability registry must contain version 1.0 and capabilities")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        raise CapabilityError("Capability registry capabilities must be a list")

    by_id: dict[str, dict[str, Any]] = {}
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            raise CapabilityError(f"Capability {index} must be a mapping")
        if set(capability) != CAPABILITY_FIELDS:
            missing = sorted(CAPABILITY_FIELDS - set(capability))
            unknown = sorted(set(capability) - CAPABILITY_FIELDS)
            raise CapabilityError(
                f"Capability {index} has invalid fields; missing={missing}, unknown={unknown}"
            )
        capability_id = capability["id"]
        if not isinstance(capability_id, str) or not CAPABILITY_ID.fullmatch(capability_id):
            raise CapabilityError(f"Invalid capability ID: {capability_id}")
        if capability_id in by_id:
            raise CapabilityError(f"Duplicate capability ID: {capability_id}")
        if capability["type"] not in CAPABILITY_TYPES:
            raise CapabilityError(f"Invalid capability type: {capability['type']}")
        if capability["status"] not in CAPABILITY_STATUSES:
            raise CapabilityError(f"Invalid capability status: {capability['status']}")
        for field in ("description", "when"):
            if not isinstance(capability[field], str) or not capability[field].strip():
                raise CapabilityError(f"Capability {capability_id} requires a non-empty {field}")
        path = capability["path"]
        if not isinstance(path, str):
            raise CapabilityError(f"Capability {capability_id} path must be a string")
        _contained_path(root, path)
        by_id[capability_id] = capability
    return capabilities


def active_capabilities(root: Path) -> list[dict[str, Any]]:
    return [item for item in load_capabilities(root) if item["status"] == "active"]


def experimental_capability(
    *,
    capability_id: str,
    capability_type: str,
    path: str,
    description: str,
    when: str,
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "type": capability_type,
        "status": "experimental",
        "path": path,
        "description": description,
        "when": when,
    }


def _contained_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    resolved_root = root.resolve()
    if target == resolved_root or resolved_root not in target.parents:
        raise CapabilityError(f"Capability path escapes repository: {relative}")
    if not target.exists():
        raise CapabilityError(f"Capability artifact does not exist: {relative}")
    return target
