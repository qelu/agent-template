# Reusable AI Agent Template

This repository creates minimal, governed agent harnesses. The default output contains one agent contract, one canonical capability registry, executable configuration validation, four concise skills, extension scaffolding, and tests. Optional operational examples are kept in this source repository and are not copied into new agents.

## Create an agent

```bash
python3 scripts/initialize_agent.py --destination ../research-agent
```

The initializer prompts for name, identifier, mission, role, tone, and language. Every value can also be provided as a flag:

```bash
python3 scripts/initialize_agent.py \
  --destination ../research-agent \
  --name "Axiom" \
  --id axiom \
  --goal "Research technical questions and produce cited, reproducible answers." \
  --role "research and analysis partner" \
  --tone "clear, skeptical, and concise" \
  --language en-US \
  --host codex
```

The deployment profile separates three axes:

- `--host`: `portable`, `codex`, `claude-code`, or `gemini-cli`.
- `--docs-provider`: `none`, `openai`, `anthropic`, or `gemini`.
- `--runtime`: `none` or the executable, provider-neutral `reference` adapter.

When `--docs-provider` is omitted, each concrete host selects its matching documentation
provider. The portable default selects none. Documentation and host can also be mixed, such
as Gemini documentation in Claude Code:

```bash
python3 scripts/initialize_agent.py \
  --destination ../cross-provider-agent \
  --name "Atlas" \
  --goal "Build integrations from current primary documentation." \
  --role "implementation partner" \
  --tone "precise" \
  --host claude-code \
  --docs-provider gemini
```

The initializer writes only project-scoped configuration. It never modifies global Codex,
Claude Code, or Gemini CLI settings.

| Documentation provider | Generated capability | Official source |
| --- | --- | --- |
| OpenAI | HTTP MCP server | `https://developers.openai.com/mcp` |
| Gemini | HTTP MCP server | `https://gemini-api-docs-mcp.dev` |
| Anthropic | Documentation-fetch skill | Anthropic's official `llms.txt` indexes |
| None | No documentation integration | — |

Anthropic does not currently publish a verified first-party documentation MCP endpoint, so
that profile uses a small skill which discovers pages through the official Anthropic API and
Claude Code documentation indexes. Generated MCP files still require the host's normal trust
or approval flow before use.

Provider SDK adapters (`openai-agents`, `claude-agent-sdk`, and `google-adk`) are named future
targets but are rejected until they implement the same runtime contract.

Validate the generated agent:

```bash
cd ../research-agent
python3 scripts/validate_repository.py
python3 -m unittest discover -s tests -v
```

## Minimal generated structure

```text
agent/
├── AGENT.md
└── config.yaml
config/
├── capabilities.yaml
├── context-routes.yaml
├── deployment.yaml
├── persona.yaml
├── policies.yaml
└── schemas/
    ├── capability.schema.json
    ├── deployment.schema.json
    ├── post-tool-event.schema.json
    └── pre-tool-event.schema.json
harness/
├── configuration.py
├── deployment.py
├── policy.py
├── reference_adapter.py
├── registry.py
├── runtime.py
└── runtime_factory.py
knowledge/
└── decisions/
scripts/
├── create_extension.py
├── initialize_agent.py
└── validate_repository.py
skills/
├── documentation-maintenance/
├── evidence-gathering/
├── safe-tool-use/
└── task-planning/
templates/
├── skill/
├── workflow/
├── adr-template.md
└── runbook-template.md
tests/
```

Concrete host profiles additionally create exactly one thin instruction entrypoint
(`AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`) and, when required, that host's project-level MCP
file. `agent/AGENT.md` remains canonical.

## Runtime boundary

Select the reference adapter when developing or testing executable runtime behavior:

```bash
python3 scripts/initialize_agent.py \
  --destination ../runtime-agent \
  --name "Boundary" \
  --goal "Execute registered tools through a normalized boundary." \
  --role "runtime test agent" \
  --tone "concise" \
  --runtime reference
```

`harness/runtime.py` defines the adapter protocol and control boundary. The adapter—not model
output—creates the run ID, tool-call ID, actor, timestamps, tool identity, and normalized
argument snapshot. `harness/runtime_factory.py` reads the deployment profile and constructs
that selected boundary. A call may be allowed, permanently blocked, or paused and resumed
using the same integrity-checked event snapshot. Calls execute at most once.

Every execution produces a schema-validated post-tool event with `succeeded`, `failed`, or
`partial` status. Partial results must identify each completed side effect, its exact target,
and whether it is reversible. An active runtime hook is invalid unless a runtime adapter is
selected.

The reference adapter is deliberately in-process and provider-neutral. It proves the boundary
contract with registered handlers; it is not an OpenAI, Anthropic, or Google production SDK
adapter. Phase 3 will bind approval resumes to exact calls and derive authorization from a
trusted tool-policy registry.

## Canonical configuration

- `agent/AGENT.md` is the always-loaded behavioral contract.
- `config/persona.yaml` is the only persona source.
- `config/policies.yaml` is the only authorization-policy source.
- `config/capabilities.yaml` is the only activation source.
- `config/deployment.yaml` records host, documentation, and runtime selections.
- `config/schemas/capability.schema.json` is enforced by repository validation.
- `config/schemas/deployment.schema.json` enforces compatible deployment combinations.

Every active or tested capability must have a real path and evaluation suite. New capabilities are scaffolded as `proposed` and cannot activate themselves.

## Create an extension

```bash
python3 scripts/create_extension.py --type skill --id summarize-evidence --name "Summarize Evidence"
python3 scripts/create_extension.py --type workflow --id weekly-review --name "Weekly Review"
python3 scripts/create_extension.py --type runbook --id restore-service --name "Restore Service"
```

Skills and workflows are registered as proposed capabilities. Runbooks are human-operable documents and are not capabilities.

## Optional examples

The source template includes `examples/mcp/` and `examples/runbooks/`. They are references only and are never copied by the initializer. Adopt them deliberately when a generated agent has a demonstrated need.

## Design rules

1. Keep one authoritative source for each setting.
2. Load only task-relevant skills and references.
3. Keep secrets and generated runtime data outside the repository.
4. Keep optional integrations disabled until a runtime can enforce their permissions.
5. Validate every machine-consumed contract.
6. Require human review before promoting proposed capabilities.
