"""Validate the optional external-integration catalog."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from harness.configuration import load_yaml


INTEGRATION_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INTEGRATION_FIELDS = {
    "id",
    "status",
    "kind",
    "provider",
    "description",
    "official_source",
    "auth",
    "hosts",
    "default_approval",
    "required",
    "data_classes",
    "write_capable",
    "endpoint",
}
INTEGRATION_STATUSES = {"active", "experimental", "disabled"}
INTEGRATION_KINDS = {"remote-mcp", "official-cli", "plugin"}
INTEGRATION_AUTH = {"none", "oauth", "provider-cli"}
INTEGRATION_APPROVALS = {"prompt", "writes"}
INTEGRATION_HOSTS = {"codex", "claude-code", "antigravity"}


class IntegrationError(ValueError):
    """Raised when the integration catalog violates its contract."""


def load_integrations(root: Path) -> list[dict[str, Any]]:
    payload = load_yaml(root / "config" / "integrations.yaml")
    if set(payload) != {"version", "integrations"} or payload.get("version") != "1.0":
        raise IntegrationError("Integration catalog must contain version 1.0 and integrations")
    integrations = payload.get("integrations")
    if not isinstance(integrations, list):
        raise IntegrationError("Integration catalog integrations must be a list")

    seen: set[str] = set()
    for index, integration in enumerate(integrations):
        label = f"Integration entry {index}"
        if not isinstance(integration, dict):
            raise IntegrationError(f"{label} must be a mapping")
        if set(integration) != INTEGRATION_FIELDS:
            missing = sorted(INTEGRATION_FIELDS - set(integration))
            unknown = sorted(set(integration) - INTEGRATION_FIELDS)
            raise IntegrationError(
                f"{label} has missing fields {missing} and unknown fields {unknown}"
            )
        integration_id = integration["id"]
        if not isinstance(integration_id, str) or not INTEGRATION_ID.fullmatch(integration_id):
            raise IntegrationError(f"Invalid integration ID: {integration_id}")
        if integration_id in seen:
            raise IntegrationError(f"Duplicate integration ID: {integration_id}")
        seen.add(integration_id)
        if integration["status"] not in INTEGRATION_STATUSES:
            raise IntegrationError(f"Invalid integration status: {integration['status']}")
        if integration["kind"] not in INTEGRATION_KINDS:
            raise IntegrationError(f"Invalid integration kind: {integration['kind']}")
        if integration["auth"] not in INTEGRATION_AUTH:
            raise IntegrationError(f"Invalid integration auth: {integration['auth']}")
        if integration["default_approval"] not in INTEGRATION_APPROVALS:
            raise IntegrationError(
                f"Invalid integration approval: {integration['default_approval']}"
            )
        for field in ("provider", "description", "official_source"):
            if not isinstance(integration[field], str) or not integration[field].strip():
                raise IntegrationError(f"Integration {integration_id} requires a non-empty {field}")
        if not str(integration["official_source"]).startswith("https://"):
            raise IntegrationError(f"Integration {integration_id} official_source must use HTTPS")
        hosts = integration["hosts"]
        if (
            not isinstance(hosts, list)
            or not hosts
            or not all(isinstance(host, str) and host in INTEGRATION_HOSTS for host in hosts)
            or len(set(hosts)) != len(hosts)
        ):
            raise IntegrationError(f"Integration {integration_id} has invalid hosts")
        data_classes = integration["data_classes"]
        if not isinstance(data_classes, list) or not all(
            isinstance(item, str) and item.strip() for item in data_classes
        ):
            raise IntegrationError(f"Integration {integration_id} has invalid data_classes")
        if not isinstance(integration["required"], bool) or not isinstance(
            integration["write_capable"], bool
        ):
            raise IntegrationError(f"Integration {integration_id} has invalid boolean fields")
        if integration["required"]:
            raise IntegrationError(
                f"Optional integration {integration_id} cannot be required at host startup"
            )
        endpoint = integration["endpoint"]
        if integration["kind"] == "remote-mcp":
            if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
                raise IntegrationError(
                    f"Remote MCP integration {integration_id} requires an HTTPS endpoint"
                )
        elif endpoint is not None:
            raise IntegrationError(
                f"Non-MCP integration {integration_id} must set endpoint to null"
            )
    return integrations


def active_integrations(root: Path) -> list[dict[str, Any]]:
    return [item for item in load_integrations(root) if item["status"] == "active"]
