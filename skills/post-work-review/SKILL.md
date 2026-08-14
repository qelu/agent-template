---
name: post-work-review
description: Review durable project maintenance after a major piece of work or a first interaction with an unfamiliar service. Use after architecture, dependency, configuration, security, workflow, integration, or operational changes to decide whether ADRs, technical debt, skills, hooks, policies, runbooks, configuration, tests, or integration setup must be updated or proposed.
---

# Post-work review

Run this review after implementation and validation, before the final handoff. Skip it
for trivial edits that introduce no durable behavior, decision, dependency, authority,
external system, or repeatable procedure.

## Review workflow

1. Summarize the delivered delta, including new decisions, dependencies, external
   systems, authentication, permissions, write paths, repeated commands, recovery
   steps, surprises, and accepted limitations.
2. Inspect the repository's existing durable surfaces. Read
   [references/review-matrix.md](references/review-matrix.md) and examine only the
   relevant ADRs, debt records, skills, hooks, policies, runbooks, configuration,
   schemas, tests, integration catalog, and user documentation.
3. Compare the delivered behavior with those authoritative surfaces. Prefer updating
   an existing owner over creating a second source of truth.
4. Classify each gap:
   - **Required now** — the delivered work would otherwise be misleading, unsafe,
     unrepeatable, or unverifiable. Fix it when the original task already authorizes
     that local maintenance.
   - **Propose next** — useful durable work that materially expands the approved scope,
     authority, dependency set, or external state. Recommend it without implementing.
   - **No change** — current durable material already covers the interaction.
5. For every required or proposed item, name the target artifact, evidence, intended
   owner, authority or data impact, validation, and rollback or removal path.
6. End with a compact maintenance review. State explicitly when no durable update is
   warranted.

## Decision rules

- Capture a stable tradeoff in an ADR; do not use an ADR as a work log.
- Record accepted shortcomings as technical debt only when they have impact, evidence,
  and a concrete remediation trigger.
- Propose a skill when the agent learned a reusable, non-obvious procedure. Do not
  create one from a single incidental command or duplicate an existing skill.
- Propose a deterministic hook or policy for enforceable safety boundaries, not for
  nuanced guidance that requires judgment.
- Create or update a runbook for repeatable operator setup, diagnosis, recovery, or
  revocation.
- Propose an integration entry only from an official source. Declare authentication,
  data classes, supported hosts, write capability, approval behavior, smoke test, and
  revoke path. Never store credentials.
- Add tests or evals when the new behavior should fail loudly if it regresses.
- Keep secrets, personal data, volatile session state, and raw interaction transcripts
  out of durable artifacts.

Do not install tools, create external resources, or broaden permissions merely because
the review found an opportunity. Those actions require the user's authorization.
