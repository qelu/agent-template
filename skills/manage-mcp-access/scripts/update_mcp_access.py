#!/usr/bin/env python3
"""Safely inspect or update a generated harness MCP execution allowlist."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SERVER_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")


class McpAccessError(ValueError):
    """Raised when an MCP allowlist update is invalid."""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd(), help="generated harness root")
    action = result.add_mutually_exclusive_group(required=True)
    action.add_argument("--enable", metavar="SERVER_ID", help="allow one MCP server")
    action.add_argument("--disable", metavar="SERVER_ID", help="deny one MCP server")
    action.add_argument("--list", action="store_true", help="show allowed MCP servers")
    return result


def load_policy(root: Path) -> tuple[Path, dict[str, Any], list[str]]:
    policy_path = root / "config" / "policies.yaml"
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise McpAccessError(f"Cannot load {policy_path}: {exc}") from exc
    mcp = payload.get("mcp") if isinstance(payload, dict) else None
    if not isinstance(mcp, dict) or set(mcp) != {"mode", "allowed_servers"}:
        raise McpAccessError("Policy must contain only mode and allowed_servers in its mcp object")
    if mcp["mode"] != "allowlist":
        raise McpAccessError("Policy mcp.mode must be allowlist")
    allowed = mcp["allowed_servers"]
    if not isinstance(allowed, list) or not all(
        isinstance(server, str) and SERVER_ID.fullmatch(server) for server in allowed
    ):
        raise McpAccessError("Policy mcp.allowed_servers contains an invalid server ID")
    if len(set(allowed)) != len(allowed):
        raise McpAccessError("Policy mcp.allowed_servers contains duplicates")
    return policy_path, payload, allowed


def server_id(value: str) -> str:
    candidate = value.strip()
    if not SERVER_ID.fullmatch(candidate):
        raise McpAccessError(
            "Server ID must use 1-128 letters, digits, dots, underscores, or hyphens"
        )
    return candidate


def update_access(root: Path, *, enable: str | None, disable: str | None) -> tuple[list[str], bool]:
    policy_path, payload, allowed = load_policy(root)
    changed = False
    if enable is not None:
        candidate = server_id(enable)
        if candidate not in allowed:
            allowed.append(candidate)
            changed = True
    elif disable is not None:
        candidate = server_id(disable)
        if candidate in allowed:
            allowed.remove(candidate)
            changed = True
    allowed.sort()
    if changed:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".policies-", suffix=".json", dir=policy_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.write("\n")
            temporary.chmod(policy_path.stat().st_mode)
            os.replace(temporary, policy_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return allowed, changed


def main() -> int:
    args = parser().parse_args()
    root = args.root.expanduser().resolve()
    try:
        if args.list:
            _, _, allowed = load_policy(root)
            changed = False
        else:
            allowed, changed = update_access(root, enable=args.enable, disable=args.disable)
    except McpAccessError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print("Updated MCP execution allowlist." if changed else "MCP execution allowlist unchanged.")
    print("Allowed MCP servers:", ", ".join(sorted(allowed)) if allowed else "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
