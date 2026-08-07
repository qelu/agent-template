# ADR-0002: Derive tool authority from trusted configuration

- Status: accepted
- Date: 2026-08-07
- Owners: repository maintainers

## Context

The original policy helper accepted `action_class` and `explicit_approval` from its caller.
Those fields can originate in model output and therefore cannot establish authority. Phase 2
created trusted runtime events but intentionally did not classify or authorize them.

## Decision

Make `config/tools.yaml` the canonical, fail-closed tool-policy registry. The adapter
canonicalizes declared path and host arguments before creating the trusted event. Guardrails
derive action, risk, approval, filesystem, shell, network, private-data, and output-trust
behavior from the registered tool identity and normalized arguments.

Store approvals outside model arguments. Bind each approval to the exact run, call, tool, and
canonical-argument digest, and consume it once. Connect guardrail decisions to the runtime's
allow, block, and pause/resume states. Keep the registry empty by default.

## Alternatives

- Continue accepting caller classifications: rejected because a model could downgrade risk.
- Put approval booleans in tool arguments: rejected because they can be forged or replayed.
- Trust lexical path checks: rejected because relative paths and symlinks can escape roots.
- Enable common tools by default: rejected because generated agents should begin with no tool
  authority.

## Consequences

Adding a runtime handler no longer makes it executable by itself; maintainers must add and
review a matching trusted policy. Provider adapters must populate the same normalized events.
Handler implementations remain trusted code and must honor declared filesystem and network
capabilities. Persistent approval and run recovery remain Phase 4 work.
