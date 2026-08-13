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

1. **Destination** — a new directory or an existing empty directory; existing
   files are never overwritten.
2. **Identity** — display name and stable lowercase Agent ID.
3. **Persona** — goal, role, tone, and language.
4. **Host** — Codex, Claude Code, Antigravity, or portable.
5. **Documentation** — OpenAI, Anthropic, Gemini, or none.
6. **Capabilities** — required safety skills and selected optional packages.
7. **Environment** — Python, development tools, Gitleaks, and optional host CLI.
8. **Review** — exact files and external commands before confirmation.

Use arrows for selection, Space to toggle checkboxes, Enter to continue, and
Ctrl+C to cancel without creating the destination.

The primary goal should describe a concrete result the agent is expected to
produce, not a personality trait. For example: “Review pull requests and
identify security or correctness issues before merge.” The role can then
describe the working identity, such as “security-focused code reviewer.”

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
- A fresh reminder through `UserPromptSubmit` on Codex and Claude Code or
  `PreInvocation` on Antigravity that prior plan approval never grants
  conversation-wide authority.
- Native sandbox and permission defaults where project-scoped settings exist.
- One portable decision policy: reads inside allowed paths are allowed, writes
  inside allowed paths ask, and deletions are denied.
- A pre-tool hook that enforces denied paths, path scope, deletion rules, shell
  denials, and conservative handling of unknown actions.
- Redacted audit metadata keyed by the host's session/conversation identifier.
- Native documentation MCP or documentation skill configuration.

The portable configuration copied into every generated project is:

- `config/persona.yaml` for identity, goal, language, and tone;
- `config/policies.yaml` for action decisions, allowed paths, denied paths, shell
  denials, and audit enablement;
- `config/capabilities.yaml` for the selected discovery manifest.

`agent/AGENT.md` remains the separate, stable contract. The generated root host
file only directs the selected host to that contract, while native settings and
`scripts/guardrails/*.py` form the enforcement layer.

The hook records hashes, host, event, run ID, turn ID, tool name, and outcome. It
does not store prompt or argument content. Audit files live under
`.agent-harness/audit/` and are ignored by Git.

The native translation is host-specific:

| Portable decision | Claude Code | Antigravity | Codex |
| --- | --- | --- | --- |
| `allow` | `PreToolUse` returns `allow` | `PreToolUse` returns `allow` | Hook exits without tightening native controls. |
| `ask` | `PreToolUse` returns `ask` | `PreToolUse` returns `ask` | The generated read-only sandbox and `on-request` approval flow prompt natively. |
| `deny` | `PreToolUse` returns `deny` | `PreToolUse` returns `deny` | `PreToolUse` returns `deny`. |

The policy file is JSON-compatible YAML so all three dependency-free hook
bridges can read it with Python's standard library. Its strict parser rejects
missing fields, unknown fields, invalid decisions, duplicate entries, and any
attempt to weaken deletion from `deny`. Repository validation and generated
harness validation call that same parser; there is no separate policy schema
with potentially different behavior.

Plan approval and native tool approval are deliberately separate. The former is
a semantic agreement about scope; the latter is enforced by the host before a
sensitive operation. When a host does not expose semantic plan approval as a
stable hook event, the contract cannot honestly claim cryptographic enforcement.

### Destructive-request boundary

For a request such as "delete all my files on this computer," the expected
behavior is refusal. Deletion tools, deletion shell commands, and patch deletion
directives are denied by the pre-tool hook. Host sandboxing independently limits
other writes.

This protection assumes the generated project is opened as a narrowly scoped
workspace. Do not use a home directory or another broad filesystem root as the
workspace. Shell classification is intentionally conservative: commands that
cannot be shown to be read-only ask through the native permission flow. The
native session or conversation ID labels the audit trail but does not grant
permission.

## Capability selection

`task-planning`, `safe-tool-use`, `manage-project-scope`, and
`map-skill-command` are required. The scope-management skill lets a user ask the
generated agent to add an existing project directory with read-only or
read-write access. It updates the portable scope in `config/policies.yaml` while
preserving denied paths and treating the host's native workspace boundary
separately.

The command-mapping skill creates project-level slash aliases that load an
installed target skill without copying its instructions or expanding authority.
On the completion screen, “Here are some things you can try” introduces adding
a project folder and mapping a slash command. These demonstrate two of the
harness's capabilities; they are not required next steps or a complete list of
what the harness can do.

Active optional capabilities
are read from the lightweight source registry and copied to the native skill
directory:

| Host | Skills directory |
| --- | --- |
| Codex | `.agents/skills/` |
| Claude Code | `.claude/skills/` |
| Antigravity | `.agents/skills/` |
| Portable | `.agents/skills/` |

Generated projects receive only the selected discovery entries: ID, type,
status, path, description, and the `when` trigger.

The permitted states are `active`, `experimental`, and `disabled`. Only active
capabilities are offered by the initializer. Tests remain ordinary repository
tests instead of fields in the capability manifest.

## Installation scope

| Requirement | Behavior |
| --- | --- |
| Python | Obtained by `uv`; system Python remains unchanged. |
| Python packages | Installed into the generated `.venv`. |
| Development tools | Ruff, pytest, mypy, and pre-commit from the dev extra. |
| Gitleaks | Run only when selected. The wizard detects it before offering the scan and can plan an official Homebrew install on macOS. |
| Codex CLI | Optional explicit installation using the official npm package. |
| Claude Code | Optional explicit installation using the official npm package. |
| Antigravity CLI | Detected as `agy`; use Google's official installer when absent. The initializer does not pipe a remote script into a shell. |
| Provider SDKs | Never installed. |
| Credentials | Never collected or written; use the host's login flow. |

## Transaction and validation

Generation occurs in a temporary sibling directory. The initializer:

1. resolves the host, documentation provider, and capabilities;
2. copies only the portable contract and selected source assets;
3. writes native host settings, permissions, hooks, MCP, and skill locations;
4. replaces identity placeholders and writes a pending receipt;
5. optionally provisions the `.venv` and runs the harness validator and Ruff;
6. runs Gitleaks when selected, whether or not Python provisioning was selected;
7. atomically publishes the destination only after success.

Failure removes the staging directory and leaves a new destination absent or a
supplied empty destination unchanged.

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
| `--destination PATH` | New or existing empty harness destination. |
| `--name`, `--id`, `--goal`, `--role`, `--tone`, `--language` | Identity and persona. |
| `--host` | `portable`, `codex`, `claude-code`, `antigravity`, or alias `gemini-cli`. |
| `--docs-provider` | `none`, `openai`, `anthropic`, or `gemini`. |
| `--capability ID` | Include an optional capability; repeat for more. |
| `--python VERSION` | Python version passed to `uv`. |
| `--install` | Provision and validate the generated project. |
| `--dev-tools` / `--no-dev-tools` | Include or omit development tools. |
| `--security-tools` | Run Gitleaks; on macOS, a missing binary can be installed through Homebrew after plan approval. |
| `--install-host-tool` | Plan an approved Codex or Claude Code CLI installation when absent. |
| `--yes` | Approve external commands non-interactively. |
| `--dry-run` | Print the plan without writing. |
| `--no-color` | Disable terminal color. |

There is intentionally no `--runtime` or provider-SDK option.
