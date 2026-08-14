# Changelog

All notable changes are documented here. The format follows Keep a Changelog and
the project follows Semantic Versioning.

## [Unreleased]

### Changed

- Aligned source, initializer, generated-project, contribution, release, and
  security documentation with the v1.0 host-native implementation.
- Clarified the project's primary audience and documented the end-to-end path
  for contributing, reviewing, and activating reusable capabilities.
- Added Python 3.14 to the initializer's supported environment choices and
  installation receipt schema.

### Fixed

- Corrected `map-skill-command` instructions to invoke the registered bundled
  helper instead of a nonexistent project-level script.

## [1.0.0] - 2026-08-13

### Added

- A terminal initializer with ASCII branding, host selection, locked
  core guardrails, optional capability selection, environment preflight, dry
  runs, explicit external-command approval, and installation receipts.
- Reusable initialization specification, resolution, transactional generation,
  provisioning, and validation layers with a minimal generated capability manifest.
- Complete operator documentation for wizard controls, Agent IDs, host-native
  semantics, capability selection, installation scope, receipts, rollback, and
  non-interactive flags.
- Structured bug and feature issue forms plus community conduct guidance.
- Native Codex, Claude Code, and Antigravity project profiles with permissions,
  hooks, skill locations, and documentation integrations.
- Host-specific guardrail bridges backed by one portable policy,
  redacted run-aware audit metadata, path scope, write confirmation, deletion
  denial, and conservative handling of unknown actions.
- Official-shaped hook protocol fixtures, host-profile conformance tests, and
  generated-project validation.
- Required project-scope and skill-command helpers with host-native skill paths.
- Static skill auditing plus manually triggered import workflows for immutable
  external sources and genuinely new skills from stable tagged template releases.
- Optional Devoteam branding support for documents, presentations, spreadsheets,
  PDFs, CVs, proposals, reports, and visual assets using authenticated official sources.
- A host-independent generated `scripts/update_scope.py` launcher, including
  Antigravity/Linux regression coverage.

### Changed

- Realigned the project around host-native harnesses; the selected host now owns
  inference, authentication, sessions, sandboxing, and tool execution.
- Renamed the canonical Gemini CLI profile to Antigravity while retaining
  `gemini-cli` as an initializer compatibility alias.
- Simplified generated projects to contain only portable policy, selected
  capabilities, native host configuration, guardrails, and validation tools.
- Replaced the multi-actor capability attestation state machine with a concise
  Git-reviewed discovery registry of IDs, descriptions, triggers, states, and paths.
- Unified portable guardrail decisions around scoped reads, confirmed writes,
  prohibited deletions, denied paths, and conservative unknown actions.
- Updated repository, generated-project, contributor, security, example, and ADR
  documentation to describe the same host-native enforcement boundary.
- Improved wizard explanations, persona examples, existing-empty-destination handling,
  Gitleaks preflight, Codex CLI detection, and post-install capability examples.

### Removed

- Provider SDK runtime selection and unimplemented adapter choices.
- The duplicate Python model loop, reference adapter, runtime lifecycle state,
  tool-event schemas, adapter conformance suite, and reference runner.
- Policy and capability JSON Schemas superseded by strict validation in the code
  that consumes each file.

## [0.1.0] - 2026-08-08

### Added

- The original provider-neutral runtime experiment and deterministic reference adapter.
- Declarative tool policy, exact-scope approvals, and lifecycle state experiments.
- Revision-bound implementation plans and re-planning controls.
- A capability registry with evaluation, activation, drift, rollback, and audit history.
- Initialization profiles for portable, Codex, Claude Code, and Gemini CLI hosts.
- Official documentation integrations for OpenAI, Anthropic, and Gemini workflows.
- Repository validation, behavioral tests, CI, and dependency update automation.

[Unreleased]: https://github.com/qelu/agent-template/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/qelu/agent-template/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/qelu/agent-template/releases/tag/v0.1.0
