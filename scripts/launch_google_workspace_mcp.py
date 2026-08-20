#!/usr/bin/env python3
"""Launch the pinned Workspace MCP without placing OAuth secrets in a project."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    configured = os.environ.get("GOOGLE_WORKSPACE_OAUTH_CLIENT_FILE", "").strip()
    if not configured:
        print("GOOGLE_WORKSPACE_OAUTH_CLIENT_FILE is not configured", file=sys.stderr)
        return 2
    source = Path(configured).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"Cannot read Google OAuth client configuration: {exc}", file=sys.stderr)
        return 2
    client = payload.get("installed") or payload.get("web")
    if not isinstance(client, dict):
        print("Google OAuth client requires an installed or web object", file=sys.stderr)
        return 2
    client_id = client.get("client_id")
    client_secret = client.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        print("Google OAuth client is missing client_id or client_secret", file=sys.stderr)
        return 2
    uvx = shutil.which("uvx")
    if not uvx:
        print("uvx is required to launch Google Workspace MCP", file=sys.stderr)
        return 127
    environment = os.environ.copy()
    environment["GOOGLE_OAUTH_CLIENT_ID"] = client_id
    environment["GOOGLE_OAUTH_CLIENT_SECRET"] = client_secret
    command = [uvx, "workspace-mcp==1.25.0", *sys.argv[1:]]
    os.execve(uvx, command, environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
