---
name: incident-triage
description: Triage operational incidents by establishing impact, preserving evidence, stabilizing safely, testing ranked hypotheses, and producing a clear handoff. Use for outages, degraded behavior, security events, data incidents, failed deployments, or unexplained production symptoms.
---

# Incident triage

1. Establish the incident owner, affected service, start time, user impact, severity,
   and current safety constraints. Mark unknown facts explicitly.
2. Preserve relevant logs, identifiers, timestamps, versions, and recent changes without
   collecting unnecessary secrets or personal data.
3. Separate observed facts from hypotheses. Rank hypotheses by explanatory power, risk,
   and cost of the next diagnostic probe.
4. Prefer reversible containment that reduces harm without destroying evidence. Obtain
   approval before external, destructive, or scope-expanding action.
5. Run the smallest read-only probe that can distinguish the leading hypotheses. Record
   the expected result before the probe and update the timeline afterward.
6. Validate stabilization using user-visible signals and independent health evidence;
   do not equate a successful command with recovery.
7. Produce a handoff containing status, impact, timeline, evidence, actions and results,
   remaining hypotheses, risks, owner, and next checkpoint.
8. After stabilization, invoke the installed post-work review when available to route
   durable follow-up to tests, runbooks, debt, decisions, or guardrails.

Do not guess a root cause, leak sensitive incident content, or use irreversible
remediation merely because it is fast.
