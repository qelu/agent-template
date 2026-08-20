# Compatibility policy

Agent Template follows Semantic Versioning. This document defines the public
interfaces covered by the 1.x compatibility promise and how changes to generated
harnesses are communicated.

## Supported 1.x interfaces

The following documented surfaces are public interfaces:

- the `scripts/initialize_agent.py` command-line flags and values documented in
  `docs/initializer.md`;
- the supported host IDs `portable`, `codex`, `claude-code`, and `antigravity`,
  plus the `gemini-cli` compatibility alias;
- the generated project paths and responsibilities documented in the README and
  initializer guide;
- `config/policies.yaml` version 1.0, including its allow, ask, deny, path-scope,
  shell, and audit semantics;
- `config/capabilities.yaml` version 1.0 and its `id`, `type`, `status`, `path`,
  `description`, and `when` fields;
- `config/integrations.yaml` version 1.0 and its integration identity, trust,
  authentication, host, approval, transport, credential-environment, and CLI
  installation fields;
- `config/initializer.yaml` version 1.0 and the required/default capability,
  bundle, and environment selections it controls;
- installation receipt schema 2.0 in
  `config/schemas/installation.schema.json`;
- secure Google Workspace OAuth configuration for the pinned community stdio MCP on
  Codex, Claude Code, and Antigravity, including user-only permission guarantees;
- the generated `scripts/validate_harness.py` and `scripts/update_scope.py`
  command-line behavior documented in generated projects;
- the native hook events generated for each supported host and the portable
  allow, ask, and deny outcomes described below; and
- the skill contract requiring `name` and `description` frontmatter and a
  matching registered capability entry.

Python 3.11 through 3.14 are supported for the 1.x release line. Security support
for release lines is defined separately in `SECURITY.md`.

## Host and hook contracts

The generated profiles currently use these host-native events:

| Host | Prompt event | Tool event | Portable decision behavior |
| --- | --- | --- | --- |
| Codex | `UserPromptSubmit` | `PreToolUse` | The hook returns hard denials; the generated read-only sandbox and native approval flow handle `ask`. |
| Claude Code | `UserPromptSubmit` | `PreToolUse` | The hook returns native allow, ask, or deny decisions. |
| Antigravity | `PreInvocation` | `PreToolUse` | The hook injects prompt context and returns native allow, ask, or deny decisions. |
| Portable | Host-defined | Host-defined | The portable contract and policy are supplied without a generated native bridge. |

The selected host owns inference, authentication, sessions, sandboxing, tool
dispatch, and the final native protocol. Agent Template owns the generated
configuration, the portable policy semantics, strict parsing, and bridge behavior.
When an upstream host changes its native contract, the project updates the
corresponding profile and conformance fixtures.

## Behavioral evaluation requirements

Every supported native host profile must have automated, official-shaped event
fixtures covering:

- allowed reads and confirmed writes inside configured scope;
- denied paths and the invariant that deletion remains denied;
- conservative handling of unknown tools and shell commands;
- selected MCP calls reaching native approval and unselected global MCP calls being denied;
- external side effects flowing through native confirmation;
- prompt-context injection and host session or conversation ID normalization;
- redacted, run-scoped audit metadata; and
- fail-closed behavior for malformed policy or hook input.

Changes to portable policy decisions, generated permissions, native hook payloads,
or audit behavior must update the cross-host conformance tests in the same pull
request. A host profile is not release-ready when its required event fixtures are
missing or failing.

## Interfaces that are not public

The `harness` package and functions in `scripts/guardrails` are repository
implementation details. The project does not currently provide a supported Python
import API. Internal function names, dataclasses, helper signatures, and module
layout may change in any release when the documented interfaces above remain
compatible.

Console formatting, diagnostic wording, temporary staging paths, test helpers,
and undocumented files are also not compatibility promises. Observable safety
decisions, exit success or failure, generated artifacts, and documented receipt
fields remain covered.

## Compatible and breaking changes

- Patch releases may fix defects without changing documented successful behavior.
- Minor releases may add optional flags, fields, hosts, capabilities, or generated
  artifacts when existing inputs and generated projects remain valid.
- Removing, renaming, or incompatibly changing a documented interface requires a
  new major release.
- A documented 1.x interface is not removed before 2.0. Deprecations must identify
  the replacement and appear in the README or relevant guide and `CHANGELOG.md`.
- New strict validation may reject input that was already invalid according to the
  documented contract; that is a compatible bug fix.

Safety takes precedence over preserving unsafe behavior. A security release may
tighten permissions or reject an unsafe input in a patch release. The changelog
and security advisory must identify the behavior change, affected versions, and
required operator action.

An upstream host may remove or change a native surface outside this project's
control. When compatibility cannot be preserved, the release must name the host
version or contract change, describe the impact, provide migration steps, and
avoid silently weakening the portable policy.

## Migration policy

The initializer creates new harnesses transactionally and does not overwrite a
non-empty destination. Existing generated harnesses are never silently upgraded.
The template skill importer adds only missing skills from a stable tagged release;
it does not update, merge, or replace locally installed skills.

When a release requires operator changes, its changelog or linked migration guide
must include:

1. the affected versions, hosts, configuration versions, and generated paths;
2. a before-and-after example for every changed public format;
3. ordered update and validation commands;
4. rollback or recovery instructions; and
5. security or authority implications.

Installation receipts record the source repository and revision so operators can
identify the template used to create a harness. Operators remain responsible for
reviewing release notes and applying documented migrations to generated projects.
