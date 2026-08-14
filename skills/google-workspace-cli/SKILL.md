---
name: google-workspace-cli
description: Operate Gmail, Drive, Calendar, Docs, Sheets, Chat, and other Google Workspace APIs through the structured gws CLI with narrow scopes, schema inspection, dry runs, and explicit write approval. Use when a selected harness must read or change Google Workspace data through gws.
---

# Google Workspace CLI

1. Confirm `gws` is installed. For setup, authentication, version, and support
   boundaries, read [references/setup.md](references/setup.md).
2. Identify the exact service, resource, tenant or account, data class, and whether the
   request is read-only or write-capable.
3. Inspect unfamiliar operations with `gws <service> --help` and
   `gws schema <service>.<resource>.<method>` before constructing parameters.
4. Authenticate with only the services and scopes needed for the task. Keep credentials
   in the OS keyring or provider-designated user configuration, never this project.
5. Prefer list or get operations first. Bound page sizes and page counts; avoid broad
   mailbox, drive, or directory exports unless explicitly requested.
6. For writes, show the exact target and payload, use `--dry-run` when the command
   supports it, and obtain the applicable approval before execution.
7. Parse structured JSON output. Check the CLI exit code and verify the resulting
   Workspace state with an independent read.
8. Redact message bodies, file contents, attendee details, identifiers, and tokens from
   logs and durable reports unless the task specifically requires them.

Quote JSON and Sheets ranges safely for the active shell. Never use the removed
`gws mcp` command or invent a current Google Workspace MCP transport.
