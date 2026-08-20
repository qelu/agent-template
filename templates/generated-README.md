# __AGENT_NAME__

__AGENT_ROLE__ running as a host-native agent harness.

## Goal

__AGENT_GOAL__

## Start

Run the selected host from this project directory. The canonical contract is
`agent/AGENT.md`; the root host instruction file loads it automatically.

Validate the generated harness with:

```bash
uv sync --python __AGENT_PYTHON__
uv run python scripts/validate_harness.py
```

Add `--extra dev` to `uv sync` when development tools are wanted. The installation
receipt records whether they were selected during initialization.

The installation choices are recorded in
`.agent-harness/installation.yaml`. `execution: host-native` means the selected
host owns inference, authentication, sessions, sandboxing, and tool execution.
No provider SDK or duplicate model runtime is installed.

Optional external services selected during initialization are listed in
`config/integrations.yaml`. When the list is non-empty, follow
`docs/integrations.md` to review scopes, authenticate through the host or provider,
test a read-only operation, and confirm write prompts. The project contains no
integration credentials. A selected Google Workspace integration uses a pinned local MCP;
its OAuth client lives in the private user path recorded in the installation receipt,
never this project.

An integration may use a remote MCP server or a provider-maintained CLI. CLI
installation commands are recorded in the approved plan. Environment-variable names
in native MCP configuration are references only; set credential values in the shell
or user secret manager before launching the host, never in tracked files.

Required and selected optional skills live in the host's native project directory.
Native permission and hook configuration supplies project-level safety controls.
The host-specific bridge uses the host session/conversation identifier as the run
ID, applies the portable policy, allows scoped reads, asks for scoped writes,
denies deletions and denied paths, and writes redacted metadata under
`.agent-harness/audit/`.

Optional skills, runbooks, validators, and hooks are listed in
`config/capabilities.yaml`. If `pre-commit-secret-scan` is selected, this
repository uses `.githooks/pre-commit` to scan staged changes with Gitleaks before
Git creates a commit.

`config/policies.yaml` uses JSON-compatible YAML so the dependency-free hook
bridges read that exact file directly. The strict runtime parser rejects malformed
or unknown fields and fails closed. The default decisions are:

- reads inside `allowed_read_paths`: allow;
- writes inside `allowed_write_paths`: ask;
- denied or out-of-scope paths: deny;
- deletions: deny;
- external side effects and unknown actions: ask.

Claude Code and Antigravity return `ask` directly from `PreToolUse`. Codex's
pre-tool hook enforces denials while its generated read-only sandbox and
`on-request` approval flow provide the native confirmation boundary for writes.

## Add project folders

The harness initially reads and writes only inside this project. To add another
project, ask the agent:

> Add `/path/to/project` to this harness with read-only access.

Use “read-write access” only when the agent should modify that project. The
required `manage-project-scope` skill resolves the exact directory and updates
`config/policies.yaml`, where `allowed_read_paths` and `allowed_write_paths`
define portable scope. `denied_paths` continues to take precedence.

The underlying command is the same for every supported host and operating system:

```bash
python3 scripts/update_scope.py \
  --root /path/to/this/harness \
  --path /path/to/project \
  --access read
```

Policy scope does not override the selected host's native sandbox or workspace
boundary. If the host still blocks the folder, add it through the host's normal
workspace controls rather than weakening safety settings.

## Map slash commands to skills

Ask the agent to create a short alias for any installed skill:

> Map `/scope` to the `manage-project-scope` skill.

The required `map-skill-command` skill creates a small alias skill in the
selected host's native skill directory and registers it in
`config/capabilities.yaml`. The alias loads the original skill, so it does not
duplicate instructions or grant additional authority. Enabled skills appear in
the host's command picker; Codex also supports explicit `$scope` invocation.

## Audit and import skills

The required `skill-auditor` statically reviews candidate skills without
executing them. `import-external-skill` imports a new skill from an immutable
external source, while `import-template-skills` discovers new skills in stable
tagged agent-template releases. Both preserve every installed ID and existing
skill directory unchanged: they never compare, update, merge, or overwrite local
skills. Template discovery and import are manually triggered and never scheduled.

Example requests:

> Audit this skill ZIP before importing it.

> Import this new skill from `/path/to/skill`.

> Check the latest stable agent-template release for new skills.

Plan approval applies only to the exact plan presented. A later state-changing
request is new scope, even in the same conversation. Native tool approval is a
separate host decision.

An unbounded request such as "delete all my files" must be refused. The hook
denies deletion tools, shell commands, and patch directives, while native host
permissions govern confirmation for writes. Keep the workspace narrow: the run
ID labels audit events but does not authorize them.

## License

Apache-2.0. See `LICENSE`.
