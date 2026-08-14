# ADR 0008: Separate optional capabilities from external integrations

- Status: accepted
- Date: 2026-08-14

## Context

The initializer must offer reusable skills, hooks, workflows, runbooks, validators,
and common external services without silently expanding authority, authentication,
tool context, or generated-project size. The existing capability registry describes
local artifacts but does not capture connection ownership, authentication, data
classes, write authority, or host compatibility.

## Decision

Keep the existing required safety capabilities. Classify new local artifacts as
optional capabilities and authenticated services as optional integrations.

`config/capabilities.yaml` remains the lightweight artifact registry.
`config/integrations.yaml` records only reviewed integration metadata: official
source, kind, authentication mode, supported hosts, approval default, data classes,
write capability, endpoint or CLI command, non-secret credential environment name,
and reviewed installation/setup commands where applicable.

The initializer exposes capabilities, integrations, and named bundles separately.
Current optional defaults remain explicit in `config/initializer.yaml`; future
catalog additions are opt-in unless a reviewed compatibility change adds them to
that list. Bundles are transparent selection shortcuts, never hidden authority.

Authentication occurs after generation through the selected host or provider.
Tokens and credentials are never written to the project. Optional integrations do
not make host startup fail when disconnected. Generated receipts record selection
and authentication as pending, not secret material.

## Consequences

The catalog remains provider-neutral and least-authority while supporting native
host adapters. Adding an integration requires validation, documentation, removal
guidance, permission review, and conformance fixtures. Provider-specific plugins or
official CLIs can coexist with remote MCP integrations without pretending every
service uses the same transport.
