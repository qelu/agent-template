# Durable maintenance review matrix

Use this matrix to route evidence to an existing authoritative artifact or a focused
proposal. Not every row should produce work.

| Surface | Create or update when | Avoid when |
| --- | --- | --- |
| ADR | A durable architectural or governance choice has meaningful alternatives and consequences. | The change is routine implementation or already governed by an accepted decision. |
| Technical debt | A known limitation is intentionally accepted and needs an impact, owner, or remediation trigger. | The problem was fixed or is merely a vague future idea. |
| Skill | The agent learned a reusable, non-obvious workflow with stable inputs, checks, and stopping conditions. | One incidental command or an existing skill already covers it. |
| Hook or policy | A deterministic rule can prevent an unsafe tool action, path, permission, or external write. | The decision is contextual and requires model or human judgment. |
| Runbook | Operators need repeatable setup, diagnosis, recovery, rotation, or revocation steps. | The procedure is fully automated and self-explanatory. |
| Integration | A service will recur and has an official MCP, CLI, plugin, or API with understood trust boundaries. | The source is unofficial, credentials would be embedded, or usage was one-off. |
| Configuration or schema | Runtime behavior, defaults, supported values, or generated output changed. | No machine-consumed contract changed. |
| Test or eval | Desired behavior, safety, compatibility, or routing should fail loudly on regression. | The assertion would only mirror implementation details without protecting behavior. |
| User documentation | Setup, supported behavior, limitation, or recovery guidance changed. | The information is internal process narration. |

## First-use external service example

After a first Jira Cloud review, inspect what was actually learned before recommending
artifacts:

- propose the official Atlassian Rovo MCP integration when recurring Jira access is
  expected, with OAuth, data classes, write prompting, a read-only smoke test, and a
  revoke procedure;
- propose a Jira workflow skill only when the interaction established a reusable
  process for finding, classifying, responding to, or transitioning issues;
- propose a hook or policy when deterministic guardrails are needed, such as requiring
  confirmation before comments, assignments, or transitions;
- propose a runbook for site selection, authentication, troubleshooting, and revocation;
- create an ADR only if Jira is adopted as a system of record or another durable
  architectural choice was made.

Do not turn every first use into every artifact. Recommend only the surfaces supported
by evidence from the completed work.
