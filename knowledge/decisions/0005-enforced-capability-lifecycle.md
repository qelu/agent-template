# ADR 0005: Keep capability governance lightweight

- Status: accepted
- Date: 2026-08-08

## Context

The original registry persisted artifact, definition, evaluation, activation, and transition
digests for every capability. That was appropriate for a multi-actor service, but it duplicated
Git history and made routine skill changes needlessly ceremonial in a single-operator project.

## Decision

`config/capabilities.yaml` remains the selection source and records only identity, type, semantic
version, status, path, description, risk, compatible hosts, dependencies, and an evaluation suite.
Validation rejects missing artifacts, missing evaluations for active capabilities, incompatible
dependencies, old dependency versions, and cycles. Git history supplies change attribution and
review evidence. Promotion is an ordinary reviewed registry edit after the evaluation passes.

## Consequences

The registry stays readable and portable. Teams needing cryptographic attestations or external
approval records can add that as an optional governance capability without burdening the core
template.
