# Terminal initializer guide

The Agent Harness Initializer turns this template into a configured, validated
harness in a new destination. Run it from a clone of the template:

```bash
uv run python scripts/initialize_agent.py
```

Git and `uv` are the bootstrap requirements. `uv` obtains the selected Python
version, creates the generated project's `.venv`, and installs locked Python
dependencies. The initializer does not replace the system Python.

## Wizard flow

The interactive wizard collects and resolves these choices:

1. **Destination** — a new directory outside the template repository. Existing
   destinations are never overwritten.
2. **Agent name** — the human-readable name shown in the generated harness.
3. **Agent ID** — the stable machine identifier used in package metadata,
   configuration, and the installation receipt. It is normalized to lowercase
   words separated by hyphens, such as `research-assistant`.
4. **Goal, role, tone, and language** — the initial agent persona and operating
   objective.
5. **Host** — Codex, Claude Code, Gemini CLI, or portable configuration.
6. **Documentation integration** — the provider-appropriate documentation MCP
   or governed documentation skill.
7. **Runtime** — host-managed execution or the deterministic reference runtime.
8. **Capabilities** — required guardrails plus compatible optional skills,
   hooks, runbooks, workflows, validators, and MCP servers.
9. **Environment** — Python, development tools, Gitleaks, and optional host CLI
   installation.
10. **Review** — the exact resolved plan and any external commands, followed by
    a final confirmation.

Use the arrow keys to choose a single option, Space to toggle checkbox entries,
Enter to continue, and Ctrl+C to cancel. Cancellation does not create the
destination.

## Host and runtime are separate

The host is the application in which the generated harness will be used. The
runtime determines who owns the model loop.

| Selection | Meaning |
| --- | --- |
| Claude Code + host-managed | Claude Code owns the model loop; no Claude Agent SDK is installed. |
| Codex + host-managed | Codex owns the model loop; no OpenAI Agents SDK is installed. |
| Gemini CLI + host-managed | Gemini CLI owns the model loop; no Google ADK is installed. |
| Any supported host + reference | The local deterministic adapter exercises the governed runtime without a provider API. |

Provider SDK runtimes remain named compatibility targets and are rejected until
their adapters are implemented and pass the adapter conformance suite.

## Capability selection

`task-planning` and `safe-tool-use` are required and cannot be deselected. The
wizard reads all other choices from the governed capability registry, groups
them by type, disables incompatible combinations, and automatically adds declared
dependencies.

The current packaged optional catalog contains `evidence-gathering` and
`documentation-maintenance`. Host-specific documentation capabilities are added
from the selected documentation profile. The selector already understands
skills, hooks, runbooks, workflows, validators, and MCP servers; newly packaged
and registered capabilities will appear automatically.

## Installation scope

| Requirement | Behavior |
| --- | --- |
| Python | Obtained by `uv` at the selected version; system Python is unchanged. |
| Python packages | Installed from `uv.lock` into the generated `.venv`. |
| Ruff, pytest, mypy, pre-commit | Installed through the locked `dev` extra when development tools are selected. |
| Gitleaks | Reused when detected; on systems with Homebrew it can be installed only after explicit approval. Other systems fail safely with installation guidance. |
| Host CLI | Reused when detected; an absent Codex, Claude Code, or Gemini CLI can be installed through its published npm package only after explicit approval. |
| Provider SDK | Not installed for host-managed execution. It will be installed only by a future implemented provider-runtime profile. |
| Credentials | Never collected or written. Authentication remains in the host's official login or first-launch flow. |

Global commands are listed in the review screen. Declining them does not prevent
generation unless the selected validation requires the missing tool.

## Transaction and validation behavior

The initializer resolves compatibility and dependencies before writing. It then
builds the harness in a temporary sibling directory, replaces placeholders,
filters unselected capabilities, refreshes attestations, and writes a pending
receipt.

When environment installation is selected, it runs:

```text
uv sync with the selected Python and extras
repository validation
the complete generated test suite
Ruff, when development tools are selected
Gitleaks, when security tools are selected
```

Only a successful staged project is moved to the requested destination. Failed
generation or validation removes the staged project and leaves the destination
absent. The initializer also rejects capability artifact paths that could escape
the staged project.

## Installation receipt

Every generated harness contains `.agent-harness/installation.yaml`. It records:

- Agent ID, host, runtime, and documentation provider
- The final capability set, including generated documentation capabilities
- Python and environment-tool choices
- Whether project dependencies or a host installation were requested
- The exact external commands approved for the run
- `validation: pending` when provisioning was skipped, or `validation: passed`
  after all selected checks succeed

The repository validator checks the receipt against
`config/schemas/installation.schema.json`.

## Non-interactive operation

All important wizard choices have command-line equivalents:

```bash
uv run python scripts/initialize_agent.py \
  --destination ../research-agent \
  --name "Research Agent" \
  --id research-agent \
  --goal "Produce cited research within an approved scope." \
  --role "research assistant" \
  --tone "clear and evidence-led" \
  --language en-US \
  --host claude-code \
  --docs-provider anthropic \
  --runtime none \
  --capability evidence-gathering \
  --python 3.13 \
  --install
```

| Flag | Purpose |
| --- | --- |
| `--wizard` | Force interactive mode. Running without a destination also starts it. |
| `--destination PATH` | New generated-project destination. |
| `--name`, `--id`, `--goal`, `--role`, `--tone`, `--language` | Identity and persona fields. |
| `--host` | `portable`, `codex`, `claude-code`, or `gemini-cli`. |
| `--docs-provider` | `none`, `openai`, `anthropic`, or `gemini`. |
| `--runtime` | `none` for host-managed execution or `reference`. Unimplemented provider adapters fail closed. |
| `--capability ID` | Include one optional capability; repeat for more. Required capabilities are automatic. Omitting the flag retains every packaged capability. |
| `--python VERSION` | Python version passed to `uv`; supported wizard choices are 3.11–3.13. |
| `--install` | Create the environment and run all selected validation. |
| `--dev-tools` / `--no-dev-tools` | Include or omit the development-tool extra. |
| `--security-tools` | Require and run Gitleaks. |
| `--install-host-tool` | Approve planning a missing host CLI installation. |
| `--yes` | Confirm planned external installation commands in non-interactive mode. |
| `--dry-run` | Print the resolved plan without changing anything. |
| `--no-color` | Disable Rich color output. |

For a safe preview:

```bash
uv run python scripts/initialize_agent.py \
  --destination ../research-agent \
  --name "Research Agent" \
  --goal "Produce cited research." \
  --role "research assistant" \
  --tone concise \
  --host claude-code \
  --dry-run
```
