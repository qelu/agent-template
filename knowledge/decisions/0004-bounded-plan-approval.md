# ADR-0004: Bind plan approval to one exact run revision

- Status: accepted
- Date: 2026-08-08
- Owners: repository maintainers

## Context

Exact tool approvals prevented replay across calls, but a model could still interpret approval
of one implementation plan as broad conversational authority and skip planning for later
requests. Requiring a new plan for every message would add friction and confuse follow-up
instructions with new work.

## Decision

Use the existing run as the work boundary. Store versioned plan revisions inside persistent
run state. Each revision contains a summary and a manifest of exact normalized tool and
argument digests. Bind a host-created, single-use approval to the run ID, revision, and plan
digest. Permit each planned action once.

Allow read-only inspection before plan approval. Require the current approved plan to contain
every state-changing call. Supersede prior approval whenever the plan changes. Never reopen a
terminal run. Continue applying exact tool approval independently for destructive, external,
or permission-expanding actions.

## Alternatives

- Treat conversational consent as durable authority: rejected because its scope is ambiguous.
- Start a new run for every user message: rejected because ordinary follow-ups would require
  unnecessary plans and approvals.
- Approve only a natural-language summary: rejected because semantic scope cannot be enforced
  deterministically.
- Allow wildcard plan actions: rejected because they recreate blanket conversation approval.

## Consequences

Material scope changes require a new plan revision and approval. Dynamic state-changing calls
must be planned after their exact arguments are known. Plans remain small manifests rather
than a second workflow engine, and the existing lifecycle supplies persistence and terminal
boundaries.
