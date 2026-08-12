# Terminal initializer guide

The initializer installs a project-level harness for an existing agent host. It
does not install or select a provider SDK runtime: Codex, Claude Code, or
Antigravity already owns the model loop.

```bash
uv run python scripts/initialize_agent.py
```

Git and `uv` are the bootstrap requirements. The optional provisioning step uses
`uv` to obtain the selected Python version and create a project-local `.venv`.
The system Python is never replaced.

## Wizard flow

1. **Destination** — a new directory; existing destinations are never overwritten.
2. **Identity** — display name and stable lowercase Agent ID.
3. **Persona** — goal, role, tone, and language.
4. **Host** — Codex, Claude Code, Antigravity, or portable.
5. **Documentation** — OpenAI, Anthropic, Gemini, or none.
6. **Capabilities** — required safety skills and selected optional packages.
7. **Environment** — Python, development tools, Gitleaks, and optional host CLI.
8. **Review** — exact files and external commands before confirmation.

Use arrows for selection, Space to toggle checkboxes, Enter to continue, and
Ctrl+C to cancel without creating the destination.

## Host selection

The host is also the runtime. There is no second runtime question.

| Choice | Launcher | Project configuration |
| --- | --- | --- |
| `codex` | `codex` | `AGENTS.md`, `.codex/config.toml`, `.codex/hooks.json` |
| `claude-code` | `claude` | `CLAUDE.md`, `.claude/settings.json` |
| `antigravity` | `agy` | `AGENTS.md`, `GEMINI.md`, `.agents/hooks.json` |
| `portable` | host-defined | portable contract and `.agents/skills/` |

The legacy `gemini-cli` argument is accepted as an alias for `antigravity`.
Antigravity uses the `agy` binary and workspace assets under `.agents/`, as
documented by Google.

## Guardrails generated for every concrete host

- One canonical agent contract with exact-scope plan approval semantics.
- A fresh reminder on supported user-prompt hooks that prior plan approval never
  grants conversation-wide authority.
- Native sandbox and permission defaults where project-scoped settings exist.
- A pre-tool safety hook that denies destructive root/device commands and reads
  or writes targeting common credential paths.
- Redacted audit metadata keyed by the host's session/conversation identifier.
- Native documentation MCP or documentation skill configuration.

The hook records hashes, host, event, run ID, turn ID, tool name, and outcome. It
does not store prompt or argument content. Audit files live under
`.agent-harness/audit/` and are ignored by Git.

Plan approval and native tool approval are deliberately separate. The former is
a semantic agreement about scope; the latter is enforced by the host before a
sensitive operation. When a host does not expose semantic plan approval as a
stable hook event, the contract cannot honestly claim cryptographic enforcement.

### Destructive-request boundary

For a request such as "delete all my files on this computer," the expected
behavior is refusal followed by a request for an exact, bounded target. Obvious
commands targeting the system, home directory, or a device are denied by the
pre-tool hook. Host sandboxing should independently prevent writes outside the
workspace.

This protection assumes the generated project is opened as a narrowly scoped
workspace. Do not use a home directory or another broad filesystem root as the
workspace. The guardrail matcher is intentionally small and deterministic; it is
defense in depth, not a complete shell-policy engine. The native session or
conversation ID labels the audit trail but does not grant permission.

## Capability selection

`task-planning` and `safe-tool-use` are required. Optional capabilities are read
from the source capability registry, filtered by host compatibility, and copied
to the native skill directory:

| Host | Skills directory |
| --- | --- |
| Codex | `.agents/skills/` |
| Claude Code | `.claude/skills/` |
| Antigravity | `.agents/skills/` |
| Portable | `.agents/skills/` |

Declared dependencies are selected automatically. Generated projects receive a
small selected-capability manifest rather than the source registry's complete
evaluation and transition history.

## Installation scope

| Requirement | Behavior |
| --- | --- |
| Python | Obtained by `uv`; system Python remains unchanged. |
| Python packages | Installed into the generated `.venv`. |
| Development tools | Ruff, pytest, mypy, and pre-commit from the dev extra. |
| Gitleaks | Required and run only when security tools are selected. |
| Codex CLI | Optional explicit installation using the official npm package. |
| Claude Code | Optional explicit installation using the official npm package. |
| Antigravity CLI | Detected as `agy`; use Google's official installer when absent. The initializer does not pipe a remote script into a shell. |
| Provider SDKs | Never installed. |
| Credentials | Never collected or written; use the host's login flow. |

## Transaction and validation

Generation occurs in a temporary sibling directory. The initializer:

1. resolves the host, documentation provider, capabilities, and dependencies;
2. copies only the portable contract and selected source assets;
3. writes native host settings, permissions, hooks, MCP, and skill locations;
4. replaces identity placeholders and writes a pending receipt;
5. optionally provisions the `.venv`, validates the harness, runs Ruff and Gitleaks;
6. atomically publishes the destination only after success.

Failure removes the staging directory and leaves the requested destination absent.

## Installation receipt

`.agent-harness/installation.yaml` records:

- `schema_version: "2.0"`
- canonical host
- `execution: host-native`
- `run_identity: host-session`
- documentation provider and selected capabilities
- environment and security-tool choices
- approved external commands
- `validation: pending` or `validation: passed`

## Non-interactive operation

```bash
uv run python scripts/initialize_agent.py \
  --destination ../research-agent \
  --name "Research Agent" \
  --id research-agent \
  --goal "Produce cited research within an approved scope." \
  --role "research assistant" \
  --tone "clear and evidence-led" \
  --language en-US \
  --host antigravity \
  --docs-provider gemini \
  --capability evidence-gathering \
  --python 3.13 \
  --install
```

| Flag | Purpose |
| --- | --- |
| `--wizard` | Force interactive mode. |
| `--destination PATH` | New harness destination. |
| `--name`, `--id`, `--goal`, `--role`, `--tone`, `--language` | Identity and persona. |
| `--host` | `portable`, `codex`, `claude-code`, `antigravity`, or alias `gemini-cli`. |
| `--docs-provider` | `none`, `openai`, `anthropic`, or `gemini`. |
| `--capability ID` | Include an optional capability; repeat for more. |
| `--python VERSION` | Python version passed to `uv`. |
| `--install` | Provision and validate the generated project. |
| `--dev-tools` / `--no-dev-tools` | Include or omit development tools. |
| `--security-tools` | Require and run Gitleaks. |
| `--install-host-tool` | Plan an approved Codex or Claude Code CLI installation when absent. |
| `--yes` | Approve external commands non-interactively. |
| `--dry-run` | Print the plan without writing. |
| `--no-color` | Disable terminal color. |

There is intentionally no `--runtime` or provider-SDK option.
