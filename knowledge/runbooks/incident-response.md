# Runbook: Incident response

## Purpose

Coordinate safe response from initial report through stabilization, recovery, handoff,
and durable follow-up.

## Scope and risk

Applies to availability, performance, security, privacy, data-integrity, deployment, and
third-party incidents. Emergency pressure does not authorize deletion, credential
disclosure, or unreviewed external changes.

## Prerequisites and approvals

- Name an incident lead, communications owner, affected systems, severity, and channel.
- Confirm access boundaries and who may authorize containment or recovery writes.
- Start a UTC timeline and use redacted references instead of sensitive payloads.

## Procedure

1. Assess impact, scope, onset, current symptoms, and whether harm is ongoing.
2. Preserve logs and recent-change evidence before actions that could alter them.
3. Apply the smallest reversible containment approved for the incident.
4. Rank hypotheses and run bounded diagnostics that distinguish them.
5. Communicate status, impact, actions, uncertainty, owner, and next update time.
6. Implement approved remediation with a rollback point and independent observer when
   risk warrants it.
7. Validate user-visible recovery, data integrity, security posture, and monitoring.
8. Close only after ownership transfers to follow-up work and the timeline is complete.

## Validation

Confirm affected user paths, health signals, error rates, data checks, security alerts,
and third-party dependencies have returned to the agreed baseline.

## Rollback

Revert the remediation at its documented rollback point when validation fails or impact
worsens. Escalate when rollback is unavailable; do not improvise destructive recovery.

## Troubleshooting

If evidence conflicts, preserve both observations, lower confidence, widen the timeline,
and choose the next least-invasive discriminating probe.

## References

After stabilization, use `post-work-review` to propose tests, debt, ADRs, guardrails, or
runbook updates supported by incident evidence.
