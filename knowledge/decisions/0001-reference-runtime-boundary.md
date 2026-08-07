# ADR-0001: Establish a provider-neutral reference runtime boundary

- Status: accepted
- Date: 2026-08-07
- Owners: repository maintainers

## Context

Runtime hooks cannot enforce policy until tool requests pass through trusted code. Starting
with a provider SDK would mix the normalized contract with one vendor's event and lifecycle
semantics, making later adapters harder to compare.

## Decision

Define provider-neutral pre-tool and post-tool schemas plus a single in-process reference
adapter. The adapter owns run IDs, call IDs, actor identity, timestamps, tool identity, and
normalized arguments. The boundary supports terminal blocking, approval pause/resume,
single execution, and explicit partial-side-effect reports.

Keep the runtime disabled by default. Require an adapter before an active hook is valid. Defer
provider SDK adapters and approval binding to later phases.

## Alternatives

- OpenAI Agents SDK first: rejected because it would make the initial contract appear
  OpenAI-specific.
- Three provider adapters at once: rejected because parity could not be established before
  the normalized behavior was executable.
- Schemas without an executable adapter: rejected because structural contracts alone would
  not prove blocking, resumption, replay prevention, or partial failure behavior.

## Consequences

The harness can now test runtime behavior without a network dependency or provider account.
Provider adapters must satisfy this contract. Phase 3 must add trusted tool classification and
approval records before the approval resume path is suitable for real side-effecting tools.
