# ADR 0005: Enforce capability lifecycle in one registry

- Status: accepted
- Date: 2026-08-08

## Context

A status label alone cannot prevent an agent from silently activating changed behavior. The
template also needs to remain portable across Codex, Claude Code, Gemini CLI, and supported
runtime adapters without duplicating activation state.

## Decision

`config/capabilities.yaml` remains the only activation source. Each record binds its semantic
version to an artifact digest, compatibility declaration, versioned dependencies, evaluation
evidence, exact human activation attestation, disabled-state metadata, and contiguous transition
history.

The host-operated lifecycle manager enforces promotion, emergency disable and safe restore,
version reset, deprecation, and removal. Its `test` command executes the declared suite before
recording evidence. Its activation path is trusted host functionality and is not model-callable.

Active capabilities must have current evidence and approval, active compatible dependencies,
and compatibility with the configured deployment. Any unversioned artifact or evaluation-suite
change fails validation.

## Consequences

Capability updates require an explicit version bump, retest, and human activation. The registry
is more verbose, but authority remains local, reviewable, and provider-neutral. Removal drops the
registry entry only; deleting artifacts remains a separate reviewed action.
