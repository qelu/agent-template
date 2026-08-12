# ADR 0007: Use one small action policy through native host controls

- Status: accepted
- Date: 2026-08-12

## Context

Codex, Claude Code, and Antigravity expose different pre-tool and permission
protocols. A provider runtime adapter cannot intercept tools owned by those hosts,
but duplicating policy logic in three handlers would create semantic drift.

## Decision

`config/policies.yaml` declares five action outcomes: reads allow, writes ask,
deletions deny, external side effects ask, and unknown actions ask. Scope uses the
explicit names `allowed_read_paths`, `allowed_write_paths`, and `denied_paths`.
No network allowlist is included without a concrete use case.

One dependency-free evaluator strictly parses this JSON-compatible YAML, rejects
unknown or malformed fields, classifies tool calls, and returns `allow`, `ask`, or
`deny`. Repository validation, generated-project validation, and host hooks use
that same parser. A separate policy JSON Schema is therefore unnecessary.

Each bridge translates the result through native host behavior. Claude Code and
Antigravity return all three outcomes from `PreToolUse`. Codex hooks hard-block
denials; its read-only sandbox and approval flow handle writes that require a user
decision.

## Consequences

Policy is readable and has one runtime meaning. Deletion approval is intentionally
impossible in the base template. Shell classification remains conservative:
unknown commands ask rather than run autonomously. Native host sandboxing and
managed policy remain independent, stronger boundaries where configured.
