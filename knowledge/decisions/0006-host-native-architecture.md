# ADR 0006: Make the selected host the agent runtime

- Status: accepted
- Date: 2026-08-09

## Context

The template is installed inside Codex, Claude Code, or Antigravity projects.
Each host already owns inference, host authentication, sessions, tool dispatch,
permissions, and sandboxing. Selected external integrations retain their own
provider authentication. A second model-provider SDK runtime duplicated the host
responsibilities, introduced separate token billing, and could not automatically
intercept work performed by the actual host.

## Decision

The initializer generates a host-native project harness. Selecting the host also
selects the runtime; there is no provider adapter choice.

The portable layer owns the agent contract, persona, authority intent,
capability selection, plan semantics, validation, and installation receipt.
Host profiles map that layer to native instruction files, permissions, hooks,
skills, and MCP configuration.

Native hook metadata supplies the run identity. Codex and Claude Code session
IDs and Antigravity conversation IDs are normalized as harness run IDs. Host-specific
protocol bridges share one policy evaluator, record redacted metadata, and enforce
deterministic allow, ask, and deny decisions without assuming a common event schema.

Claude Code and Antigravity translate all three outcomes through their native
`PreToolUse` responses. Codex hooks enforce `deny`; Codex's read-only sandbox and
native approval system implement `ask` for writes because its pre-tool response
does not expose an interactive ask outcome.

Exact semantic plan approval remains a behavioral contract unless a host exposes
a stable, trustworthy approval event. Native tool approval remains mechanically
enforced and is never treated as blanket plan approval.

## Consequences

Generated projects are smaller and do not require model-provider API keys or
separate SDK token billing. Selected integrations may still require their own
OAuth clients or credentials. The repository no longer claims enforcement through
a model runtime that the selected host bypasses. Host conformance tests and
documentation must evolve with the supported products' native configuration
contracts.
