---
name: manage-mcp-access
description: Inspect or change a generated agent harness's MCP execution allowlist. Use when the user asks to enable, allow, disable, block, list, or troubleshoot access to a specific MCP server in this harness without changing other projects or global MCP configuration.
---

# Manage MCP access

1. Locate the harness root containing `config/policies.yaml`. List the current execution
   allowlist before proposing a change:

   ```bash
   python3 scripts/update_mcp_access.py --root "/path/to/harness" --list
   ```

2. Resolve the exact MCP server ID from the selected host's MCP manager or project configuration.
   Prefer a read-only host listing over opening a global configuration that may contain secrets.
   Do not infer an ID from a provider's display name.
3. Before enabling a server, confirm that it is already installed or configured and explain its
   relevant data access and write capability. This skill permits execution; it does not install,
   authenticate, start, or repair an MCP server.
4. Present the exact server ID and requested allowlist change. Enabling an MCP expands the
   harness's external-data/tool scope and requires the host's normal write approval.
5. Apply only the approved change through the stable project launcher:

   ```bash
   python3 scripts/update_mcp_access.py \
     --root "/path/to/harness" --enable "server-id"
   ```

   Use `--disable "server-id"` to revoke execution. If an older harness lacks the launcher, read
   the `manage-mcp-access` entry in `config/capabilities.yaml`, resolve its registered `path`, and
   run `<registered-skill-path>/scripts/update_mcp_access.py` by absolute path.
6. Run `python3 scripts/validate_harness.py` and list the resulting allowed servers. If project
   dependencies are available only through uv, use `uv run python scripts/validate_harness.py`.

The allowlist is project-contained and does not edit the host's global MCP configuration. A server
may remain visible to the model while its execution is denied. Never weaken the allowlist to a
wildcard, copy credentials into the project, or treat permission to use one server as permission to
enable another.
