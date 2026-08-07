# Reusable AI Agent Template

This repository creates minimal, governed agent harnesses. The default output contains one agent contract, canonical capability and tool-policy registries, executable configuration validation, four concise skills, extension scaffolding, and tests. Optional operational examples are kept in this source repository and are not copied into new agents.

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
├── tools.yaml
└── schemas/
    ├── approval.schema.json
    ├── capability.schema.json
    ├── deployment.schema.json
    ├── post-tool-event.schema.json
    ├── policy.schema.json
    ├── pre-tool-event.schema.json
    └── tool-policy.schema.json
harness/
├── approvals.py
├── configuration.py
├── deployment.py
├── guarded_runtime.py
├── guardrails.py
├── policy.py
├── reference_adapter.py
├── registry.py
├── runtime.py
├── runtime_factory.py
└── tool_policy.py
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
adapter. The guarded runtime binds approval resumes to exact calls and derives authorization
from the trusted tool-policy registry described below.

## Trusted guardrails

`config/tools.yaml` is the only source of tool authority and is empty by default. A runtime
handler that is not also present in that registry is blocked. Each entry declares its base
action and risk, monotonic argument rules, filesystem paths, shell command fields, exact
network hosts, private-data egress behavior, approval requirement, and output trust.

The adapter canonicalizes declared paths and hosts before creating the trusted pre-tool event.
Guardrails then:

- reject caller-supplied classification, identity, or approval fields;
- raise classifications based on trusted argument rules, never lower them;
- resolve paths against configured roots and follow existing symlinks before containment
  checks, then recheck canonical paths immediately before handler execution;
- reject patterns and allowed-root targets for destructive operations;
- block configured shell-deny patterns even when approval is supplied;
- require exact allowlisted hostnames for outbound tools;
- block sensitive-key egress unless the tool explicitly allows it with approval; and
- label guarded outputs as `trusted` or `untrusted` in the post-tool event.

Approval records are created from paused adapter-owned events and bind the run ID, call ID,
tool ID, and canonical-argument digest. They live in the trusted store and are single-use.
The host-only `GuardedRuntime.grant` method must never be exposed as a model-callable tool;
model-provided approval objects, IDs, booleans, or classifications have no authority.

The reference adapter executes trusted in-process handlers, so handler implementations remain
part of the trusted computing base. They must use the canonical arguments and must not perform
filesystem or network effects that their registry entry does not declare.

## Canonical configuration

- `agent/AGENT.md` is the always-loaded behavioral contract.
- `config/persona.yaml` is the only persona source.
- `config/policies.yaml` is the only authorization-policy source.
- `config/capabilities.yaml` is the only activation source.
- `config/deployment.yaml` records host, documentation, and runtime selections.
- `config/tools.yaml` is the only trusted tool-policy source and grants nothing when empty.
- `config/schemas/capability.schema.json` is enforced by repository validation.
- `config/schemas/deployment.schema.json` enforces compatible deployment combinations.
- Runtime, policy, tool, and approval schemas are also enforced by repository validation.

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
