# ADR-0003: Persist a bounded executable lifecycle

- Status: accepted
- Date: 2026-08-07
- Owners: repository maintainers

## Context

The Phase 3 runtime enforced trusted tool policy and exact approvals, but all run, pause,
approval, and authorization state lived in process memory. A restart lost pending work, and
there was no machine-enforced run lifecycle, budget, recovery rule, or completion-evidence
gate.

## Decision

Add one schema-validated lifecycle configuration and one persistent run-state contract. Store
atomic versioned snapshots lazily under ignored local runtime state with owner-only
permissions, operating-system locks, and optimistic revision checks. Persist exact approvals
in the same trusted boundary.

Enforce legal transitions through created, inspecting, ready, awaiting approval, executing,
validating, and completed states, with failed, cancelled, and blocked terminal alternatives.
Require passing evidence before completion. Bound model turns, tool calls, retries, and run
duration. Derive idempotency keys from trusted normalized calls and block ambiguous replay.

Resume persisted approval pauses. Treat interrupted execution, cancellation during execution,
timeouts without enforceable adapter support, and reported partial side effects as fail-closed
conditions. Reject raw sensitive-key arguments before persistence and require secret
references instead.

## Alternatives

- Keep state in memory: rejected because approval and interruption recovery would be illusory.
- Replay interrupted calls automatically: rejected because side effects may already exist.
- Use caller-supplied idempotency keys: rejected because callers could bypass duplicate
  detection by minting a new key.
- Apply thread-based timeouts to in-process handlers: rejected because a timed-out thread can
  continue causing side effects.
- Create runtime directories in every generated agent: rejected because unused operational
  structure violates the minimal-template goal.

## Consequences

Managed runs create ignored local state on first use. Provider adapters can share the same
lifecycle contract, but hard tool timeouts require an adapter that can actually terminate its
execution environment. Terminal blocked runs require a new run after human reconciliation;
they are never silently reopened.
