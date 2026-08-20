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
    "token_env",
    "command",
    "install_command",
    "setup_commands",
}
INTEGRATION_STATUSES = {"active", "experimental", "disabled"}
INTEGRATION_KINDS = {"remote-mcp", "remote-mcp-suite", "local-mcp", "official-cli", "plugin"}
INTEGRATION_AUTH = {"none", "oauth", "provider-cli", "token-env"}
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
        token_env = integration["token_env"]
        command = integration["command"]
        install_command = integration["install_command"]
        setup_commands = integration["setup_commands"]
        if token_env is not None and (
            not isinstance(token_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", token_env)
        ):
            raise IntegrationError(f"Integration {integration_id} has invalid token_env")
        if integration["auth"] == "token-env" and token_env is None:
            raise IntegrationError(f"Token integration {integration_id} requires token_env")
        if integration["auth"] != "token-env" and token_env is not None:
            raise IntegrationError(
                f"Integration {integration_id} may not declare token_env for {integration['auth']}"
            )
        if not isinstance(setup_commands, list) or not all(
            isinstance(item, str) and item.strip() for item in setup_commands
        ):
            raise IntegrationError(f"Integration {integration_id} has invalid setup_commands")
        if integration["kind"] == "remote-mcp":
            if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
                raise IntegrationError(
                    f"Remote MCP integration {integration_id} requires an HTTPS endpoint"
                )
            if command is not None or install_command is not None:
                raise IntegrationError(
                    f"Remote MCP integration {integration_id} may not declare CLI installation"
                )
        elif integration["kind"] == "remote-mcp-suite":
            if endpoint is not None or command is not None or install_command is not None:
                raise IntegrationError(
                    f"Remote MCP suite {integration_id} may not declare a single transport"
                )
            if integration["auth"] != "oauth":
                raise IntegrationError(f"Remote MCP suite {integration_id} requires OAuth")
        elif integration["kind"] == "local-mcp":
            if endpoint is not None or install_command is not None:
                raise IntegrationError(
                    f"Local MCP integration {integration_id} may not declare endpoint or installation"
                )
            if not isinstance(command, str) or not command.strip():
                raise IntegrationError(f"Local MCP integration {integration_id} requires command")
        elif integration["kind"] == "official-cli":
            if endpoint is not None or token_env is not None:
                raise IntegrationError(
                    f"CLI integration {integration_id} may not declare endpoint or token_env"
                )
            if not isinstance(command, str) or not command.strip():
                raise IntegrationError(f"CLI integration {integration_id} requires command")
            if (
                not isinstance(install_command, list)
                or not install_command
                or not all(isinstance(item, str) and item.strip() for item in install_command)
            ):
                raise IntegrationError(f"CLI integration {integration_id} requires install_command")
        elif endpoint is not None or command is not None or install_command is not None:
            raise IntegrationError(
                f"Plugin integration {integration_id} has invalid transport fields"
            )
    return integrations


def active_integrations(root: Path) -> list[dict[str, Any]]:
    return [item for item in load_integrations(root) if item["status"] == "active"]
