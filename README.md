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
├── lifecycle.yaml
├── persona.yaml
├── policies.yaml
├── tools.yaml
└── schemas/
    ├── approval.schema.json
    ├── capability.schema.json
    ├── deployment.schema.json
    ├── lifecycle.schema.json
    ├── post-tool-event.schema.json
    ├── policy.schema.json
    ├── plan-approval.schema.json
    ├── pre-tool-event.schema.json
    ├── run-state.schema.json
    └── tool-policy.schema.json
harness/
├── approvals.py
├── configuration.py
├── deployment.py
├── guarded_runtime.py
├── guardrails.py
├── lifecycle.py
├── lifecycle_runtime.py
├── policy.py
├── plans.py
├── reference_adapter.py
├── registry.py
├── runtime.py
├── runtime_factory.py
├── state_store.py
└── tool_policy.py
knowledge/
└── decisions/
scripts/
├── create_extension.py
├── initialize_agent.py
├── manage_capability.py
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

## Executable lifecycle

`config/lifecycle.yaml` defines bounded model turns, tool calls, retries, run duration, and an
optional hard tool timeout. The managed runtime persists this state machine:

```text
created → inspecting → ready → awaiting_approval → executing → validating → completed
```

`failed`, `cancelled`, and `blocked` are terminal alternatives. Execution may return to
`ready` for another bounded call, and validation may return to `ready` when more work is
required. Illegal transitions fail closed. Completion requires at least one passing
validation-evidence record and no failed evidence in the current validation round. Earlier
failed rounds remain in the durable history and can be superseded after remediation.

State is written atomically under the ignored `runtime/state/` directory, which is created
only when a run starts. Each update uses an optimistic revision and an operating-system lock;
files and directories use owner-only permissions. Exact approvals are persisted separately
under the same trusted state directory and remain single-use after restart. Raw arguments
whose keys match configured secret-redaction keys are blocked before persistence; handlers
should receive secret-manager or environment-variable references instead of secret values.

An interrupted approval pause can resume its exact persisted call. An interruption during
execution becomes `blocked`, because its side effects are ambiguous. Partial results persist
their reported side effects and also become `blocked`. Idempotency keys are derived from the
run, trusted tool identity, and normalized arguments; duplicate, successful, partial,
timed-out, or still-running keys are never executed again. Explicit retries are bounded and
the managed runtime permits automatic retry only for trusted read-only calls.

Run deadlines are always enforced before managed actions. Hard tool timeouts are enabled only
for adapters that can actually stop execution. The in-process reference adapter declares that
it cannot do so, and configuration requesting a hard tool timeout with that adapter is
rejected rather than pretending cancellation occurred.

The host orchestration layer must call `record_model_turn` for every model turn and use the
managed runtime for every tool call. Bypassing that API is outside the trusted runtime
contract and cannot claim lifecycle enforcement.

### Bounded implementation plans

Read-only inspection can proceed without a plan. Before any state-changing tool call, the
managed runtime requires an approved plan revision containing that exact normalized tool and
argument digest. Each planned action is usable once. Revising the summary or action manifest
creates a new digest, supersedes the previous revision, and removes its authority.

Plan approval is bound to the run ID, revision, and plan digest and is consumed once when the
revision becomes approved. It does not approve the conversation, future runs, revised plans,
or tool calls outside the manifest. Terminal runs never reopen, so a later request must start
a new run and obtain its own plan approval. The host-only `approve_plan` method must not be
exposed as a model-callable tool. Destructive and external calls still require their separate
exact Phase 3 tool approval even when they appear in an approved plan.

## Canonical configuration

- `agent/AGENT.md` is the always-loaded behavioral contract.
- `config/persona.yaml` is the only persona source.
- `config/policies.yaml` is the only authorization-policy source.
- `config/capabilities.yaml` is the only activation source.
- `config/deployment.yaml` records host, documentation, and runtime selections.
- `config/lifecycle.yaml` is the only lifecycle-limit and state-location source.
- `config/tools.yaml` is the only trusted tool-policy source and grants nothing when empty.
- `config/schemas/capability.schema.json` is enforced by repository validation.
- `config/schemas/deployment.schema.json` enforces compatible deployment combinations.
- Runtime, lifecycle, policy, tool, state, plan, and approval schemas are also enforced by repository validation.

Every capability is bound to the digest of its artifact. Tested capabilities require passing
evidence for the exact artifact and evaluation-suite digests. Active capabilities additionally
require a human approval bound to the exact version and both digests. Dependencies declare a
minimum version, cycles are rejected, and active capabilities must match the selected host and
runtime adapter.

The enforced lifecycle is `proposed → tested → active → deprecated → removal`. `disabled` is
an emergency side state that remembers its source status and rechecks evidence, dependencies,
and compatibility before restoring active authority. Behavior or contract changes require a
higher semantic version and reset the capability to `proposed`; silent artifact drift fails
repository validation.

## Create an extension

```bash
python3 scripts/create_extension.py --type skill --id summarize-evidence --name "Summarize Evidence"
python3 scripts/create_extension.py --type workflow --id weekly-review --name "Weekly Review"
python3 scripts/create_extension.py --type runbook --id restore-service --name "Restore Service"
```

Skills and workflows are registered as proposed capabilities. Runbooks are human-operable documents and are not capabilities.

Promote a capability through the lifecycle with the host-operated manager:

```bash
python3 scripts/manage_capability.py bump summarize-evidence --version 0.2.0 --actor human:reviewer
python3 scripts/manage_capability.py test summarize-evidence --actor human:reviewer
```

The scaffolder creates a deliberately failing evaluation placeholder. Implement the capability
and its behavioral evaluation, then bump the version before testing. `test` runs the declared
evaluation before recording evidence. Activation is available only through the host-owned
`CapabilityLifecycle.activate` approval path and must never be exposed as a model-callable tool
or shell command. Deprecation and removal fail
while dependents remain; removal deletes only the registry entry and deliberately leaves the
artifact for an explicit, separately reviewed filesystem change.

## Optional examples

The source template includes `examples/mcp/` and `examples/runbooks/`. They are references only and are never copied by the initializer. Adopt them deliberately when a generated agent has a demonstrated need.

## Design rules

1. Keep one authoritative source for each setting.
2. Load only task-relevant skills and references.
3. Keep secrets out of persistent state and generated runtime data outside version control.
4. Keep optional integrations disabled until a runtime can enforce their permissions.
5. Validate every machine-consumed contract.
6. Require human review before promoting proposed capabilities.
