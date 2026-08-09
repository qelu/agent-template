# Changelog

All notable changes are documented here. The format follows Keep a Changelog and
the project follows Semantic Versioning.

## [Unreleased]

### Added

- A terminal initializer with ASCII branding, host selection, locked
  core guardrails, optional capability selection, environment preflight, dry
  runs, explicit external-command approval, and installation receipts.
- Reusable initialization specification, resolution, transactional generation,
  provisioning, and validation layers with locked dependency propagation.
- Complete operator documentation for wizard controls, Agent IDs, host-native
  semantics, capability selection, installation scope, receipts, rollback, and
  non-interactive flags.
- Structured bug and feature issue forms plus community conduct guidance.
- Native Codex, Claude Code, and Antigravity project profiles with permissions,
  hooks, skill locations, and documentation integrations.
- A shared native guardrail hook that normalizes host sessions into run IDs,
  records redacted audit metadata, and blocks deterministic destructive or
  credential-path operations.
- Host-profile conformance tests and generated-project validation.

### Changed

- Realigned the project around host-native harnesses; the selected host now owns
  inference, authentication, sessions, sandboxing, and tool execution.
- Renamed the canonical Gemini CLI profile to Antigravity while retaining
  `gemini-cli` as an initializer compatibility alias.
- Simplified generated projects to contain only portable policy, selected
  capabilities, native host configuration, guardrails, and validation tools.

### Removed

- Provider SDK runtime selection and unimplemented adapter choices.
- The duplicate Python model loop, reference adapter, runtime lifecycle state,
  tool-event schemas, adapter conformance suite, and reference runner.

## [0.1.0] - 2026-08-08

### Added

- The original provider-neutral runtime experiment and deterministic reference adapter.
- Declarative tool policy, exact-scope approvals, and lifecycle state experiments.
- Revision-bound implementation plans and re-planning controls.
- A capability registry with evaluation, activation, drift, rollback, and audit history.
- Initialization profiles for portable, Codex, Claude Code, and Gemini CLI hosts.
- Official documentation integrations for OpenAI, Anthropic, and Gemini workflows.
- Repository validation, behavioral tests, CI, and dependency update automation.

[Unreleased]: https://github.com/qelu/agent-template/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/qelu/agent-template/releases/tag/v0.1.0
