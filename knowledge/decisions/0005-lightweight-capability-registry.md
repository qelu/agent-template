# ADR 0005: Keep capability discovery lightweight

- Status: accepted
- Date: 2026-08-08

## Context

The original registry persisted versions, risk levels, evaluations, dependencies,
compatibility metadata, digests, and lifecycle transitions. That duplicated Git
history and made routine skill changes ceremonial in a single-operator project.

## Decision

`config/capabilities.yaml` is a discovery manifest. Each entry records only its ID,
type, status, artifact path, description, and a plain-language trigger explaining
when it should be used. Status is one of `active`, `experimental`, or `disabled`.

The registry validator rejects unknown fields, invalid states, duplicate IDs,
missing artifacts, and paths that escape the repository. Behavioral tests remain
ordinary repository tests rather than governance metadata attached to every entry.
Git history supplies attribution and review evidence.

## Consequences

The registry is readable, portable, and sufficient for host-native discovery and
initializer selection. Teams needing dependencies, attestations, or compatibility
matrices can add those as optional governance outside the core template.
