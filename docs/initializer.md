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
6. **Bundles** — optional, transparent shortcuts for related additions.
7. **Capabilities** — required safety skills and selected optional packages.
8. **Integrations** — active external services supported by the chosen host.
9. **Environment** — Python, development tools, Gitleaks, and optional host CLI.
10. **Review** — exact selections and external commands before confirmation.

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

Host detection checks whether the host's terminal command is available on the
current shell's `PATH`. For Codex, this checks the `codex` CLI command—not
whether the Codex desktop app is installed. When `codex` is unavailable but
`npm` is present, the wizard can add the npm-based CLI installation to the
reviewed installation plan.

## Guardrails generated for every concrete host

- One canonical agent contract with exact-scope plan approval semantics.
- A fresh reminder through `UserPromptSubmit` on Codex and Claude Code or
  `PreInvocation` on Antigravity that prior plan approval never grants
  conversation-wide authority.
- Native sandbox and permission defaults where project-scoped settings exist.
- One portable decision policy: reads inside allowed paths are allowed, writes
  inside allowed paths ask, deletions are denied, and MCP execution is limited
  to the generated project allowlist.
- A pre-tool hook that enforces denied paths, path scope, deletion rules, shell
  denials, MCP server scope, and conservative handling of unknown actions.
- Redacted audit metadata keyed by the host's session/conversation identifier.
- Native documentation MCP or documentation skill configuration.

The portable configuration copied into every generated project is:

- `config/persona.yaml` for identity, goal, language, and tone;
- `config/policies.yaml` for action decisions, allowed paths, denied paths, the
  exact MCP execution allowlist, shell denials, and audit enablement;
- `config/capabilities.yaml` for the selected discovery manifest.
- `config/integrations.yaml` for selected optional external services.

`agent/AGENT.md` remains the separate, stable contract. The generated root host
file only directs the selected host to that contract, while native settings and
`scripts/guardrails/*.py` form the enforcement layer.

The hook records hashes, host, event, run ID, turn ID, tool name, detected MCP server,
and outcome. It does not store prompt or argument content. Audit files live under
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
attempt to weaken deletion from `deny`, use an MCP policy other than `allowlist`,
or declare duplicate or invalid MCP server IDs. Repository validation and generated
harness validation call that same parser; there is no separate policy schema
with potentially different behavior.

The initializer adds only selected remote integrations and the selected documentation
MCP to `mcp.allowed_servers`. Globally configured host MCPs can remain visible, but the
pre-tool bridge hard-denies their execution unless they are explicitly enabled for this
harness. The required `manage-mcp-access` skill applies reviewed changes through
`scripts/update_mcp_access.py` without modifying global host configuration.

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

`task-planning`, `safe-tool-use`, `manage-project-scope`, `map-skill-command`,
`skill-auditor`, `import-external-skill`, and `import-template-skills` are
required. The scope-management skill lets a user ask the
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

The skill auditor performs static inspection without executing candidate code.
The external importer accepts a local folder or ZIP, a checksum-pinned archive
URL, or a Git repository pinned to a commit or tag. The template importer runs
only when explicitly requested and reads stable tagged releases. Both importers
preserve an installed capability ID or existing destination directory without
comparison, update, merge, or overwrite.

From the generated harness root, the scope skill uses one command on every host
and operating system:

```bash
python3 scripts/update_scope.py \
  --root /path/to/harness \
  --path /path/to/project \
  --access read
```

The launcher resolves the helper from the selected host's installed skill
directory. Older harnesses without the launcher must resolve the
`manage-project-scope` path from `config/capabilities.yaml` and invoke its bundled
`scripts/update_scope.py` by absolute path.

Users can trigger the management skills in plain language, for example:

- “Audit this skill ZIP before importing it.”
- “Import this new skill from `/path/to/skill`.”
- “Check the latest stable agent-template release for new skills.”

The last request performs discovery only when the user asks to check. Importing is
a separate explicit intent, and no template import runs automatically.

Active optional capabilities are read from the lightweight source registry and
copied to the native skill directory. Entries listed in
`default_capabilities` are preselected in the wizard and used when
`--capability` is omitted. Repeating the flag selects only those optional IDs.
Bundles in `config/initializer.yaml` expand into visible capability and integration
selections; selecting one never hides what will be installed.

`devoteam-branding` is an optional capability for creating, rebranding, and
auditing Devoteam documents, presentations, spreadsheets, PDFs, CVs, reports,
proposals, and visual assets. It resolves current official templates and logos
through the authenticated Devoteam Branding Zone at task time; the public
template repository does not embed private Drive links or file IDs.

`post-work-review` is an opt-in completion review for material work and first use
of unfamiliar services. It checks whether durable decisions, debt, procedures,
guardrails, configuration, tests, or integration setup need maintenance, and it
does not install tools or expand authority merely because it found an opportunity.

The first generic catalog also provides dependency review and incident-triage
skills, incident-response and external-integration-lifecycle runbooks, and an
optional staged-secret Git hook. Select `governance`, `operations`, or
`team-baseline` to use reviewed shortcuts whose contents remain visible in the
plan and receipt. Selecting `pre-commit-secret-scan` requires Gitleaks; on macOS
the initializer can add an official Homebrew installation to the approval plan.

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

## Optional integrations

External services are described separately in `config/integrations.yaml`. Each
entry declares its provider, kind, official source, authentication model,
supported hosts, data classes, write capability, endpoint where applicable, and
default approval posture. The wizard offers only active entries supported by the
selected host. Non-interactive callers repeat `--integration ID`, or use
`--bundle ID` as a reviewed shortcut.

The initializer never writes credentials into the generated project. It merges selected
MCP servers into native host configuration with optional startup behavior. For Google
Workspace, it validates a Desktop OAuth client or a Web client containing
`http://localhost:8000/oauth2callback`, then copies it to a private user directory and
configures the pinned community server locally over stdio. On POSIX systems, the source
must already be private (`chmod 600`).
Generated `docs/integrations.md` covers one-time
authentication, read-only smoke testing, scope review, and write-confirmation checks.
When Antigravity and `atlassian-rovo` are selected, interactive initialization offers to
launch the standalone `mcp-remote-client` OAuth flow after the harness is safely created.
Skipping or failing that optional login leaves the harness intact with authentication
`pending`; a successful bootstrap records it as `verified` in the installation receipt.

Current provider adapters are deliberately different where provider contracts differ:

| Selection | Adapter | Authentication | Hosts |
| --- | --- | --- | --- |
| `atlassian-rovo` | Atlassian remote MCP at the current `authv2` endpoint; Antigravity uses a persistent `mcp-remote` bridge for its Atlassian-trusted localhost callback | Host-managed OAuth 2.1 | Codex, Claude Code, Antigravity |
| `github` | GitHub official remote MCP | Fine-grained token from `GITHUB_PERSONAL_ACCESS_TOKEN`; never written to project config | Codex, Claude Code |
| `google-workspace` | `workspace-mcp==1.25.0`, locally launched with explicit service permissions | Google Desktop or Web OAuth client | Codex, Claude Code, Antigravity |

The wizard asks which Workspace services to configure and defaults them to read-only.
The generated guidance reminds users to enable the matching Google APIs and complete
browser authentication on the first tool call. The `atlassian-work`,
`github-work`, and `google-workspace` bundles add the relevant lifecycle guidance.

## Installation scope

| Requirement | Behavior |
| --- | --- |
| Python | Python 3.11–3.14 obtained by `uv` when provisioning; system Python remains unchanged. |
| Python packages | Installed into the generated `.venv` only when `--install` is selected. |
| Development tools | Ruff, pytest, mypy, and pre-commit from the dev extra when provisioning with development tools enabled. |
| Gitleaks | Run only when selected. The wizard detects it before offering the scan and can plan an official Homebrew install on macOS. |
| Staged secret hook | Optional; enables the generated repository's local `.githooks/pre-commit` and requires Gitleaks. |
| Codex CLI | Optional explicit installation using the official npm package. |
| Claude Code | Optional explicit installation using the official npm package. |
| Antigravity CLI | Detected as `agy`; use Google's official installer when absent. The initializer does not pipe a remote script into a shell. |
| Provider SDKs | Never installed. |
| Provider integrations | Codex and Claude use project-local MCP configuration. Antigravity 2.0 receives both a project manifest and a safe merge of selected integrations into `~/.gemini/config/mcp_config.json`, while the project allowlist controls use. Google Workspace launches a pinned package through a generated secret-safe wrapper. |
| Credentials | Never written to the generated project. The Google OAuth source must have mode `0600` and is copied to a user-only configuration directory. |

## Transaction and validation

Generation occurs in a temporary sibling directory. The initializer:

1. resolves the host, documentation provider, capabilities, bundles, and integrations;
2. copies only the portable contract and selected source assets;
3. writes native host settings, permissions, hooks, MCP, and skill locations;
4. replaces identity placeholders and writes a pending receipt;
5. optionally provisions the `.venv` and runs the harness validator and Ruff;
6. runs Gitleaks when selected, whether or not Python provisioning was selected;
7. atomically publishes the destination only after success;
8. for Antigravity 2.0, backs up and atomically merges only the selected integrations into its shared MCP discovery file, refusing conflicting definitions.

Failure removes the staging directory and leaves a new destination absent or a
supplied empty destination unchanged.

## Installation receipt

`.agent-harness/installation.yaml` records:

- `schema_version: "2.0"`
- canonical host
- `execution: host-native`
- `run_identity: host-session`
- documentation provider, bundles, selected capabilities, and integrations
- template repository and initialized revision
- immutable provenance and audit verdicts for subsequently imported skills
- environment and security-tool choices
- approved external commands
- non-secret integration setup metadata, including selected Google Workspace services
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
  --integration atlassian-rovo \
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
| `--capability ID` | Select an optional capability; repeat for more. If omitted, use configured optional defaults. |
| `--integration ID` | Configure an active host-compatible integration; repeat for more. |
| `--bundle ID` | Include a named bundle of capabilities and integrations; repeat for more. |
| `--python VERSION` | Python 3.11–3.14 passed to `uv`; defaults to 3.13. |
| `--install` | Provision and validate the generated project. |
| `--dev-tools` / `--no-dev-tools` | Include or omit development tools. |
| `--security-tools` | Run Gitleaks; on macOS, a missing binary can be installed through Homebrew after plan approval. |
| `--install-host-tool` | Plan an approved Codex or Claude Code CLI installation when absent. |
| `--google-workspace-client PATH` | Existing Google Desktop OAuth client, or Web client with `http://localhost:8000/oauth2callback`; required when Google Workspace is selected. |
| `--google-workspace-service SERVICE` | Workspace service to configure; repeat as needed. Defaults to Gmail, Drive, and Calendar. |
| `--google-workspace-readonly` / `--no-google-workspace-readonly` | Keep selected services read-only (default) or request full service scopes. |
| `--yes` | Approve external commands non-interactively. |
| `--dry-run` | Print the plan without writing. |
| `--no-color` | Disable terminal color. |

There is intentionally no `--runtime` or provider-SDK option.
