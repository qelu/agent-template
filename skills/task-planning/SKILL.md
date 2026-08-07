---
name: task-planning
description: Convert ambiguous or multi-step requests into bounded execution plans with outcomes, scope, dependencies, risks, approvals, validation, and rollback. Use for complex changes, irreversible actions, cross-system work, or tasks where sequencing materially affects safety or success.
---

# Task planning

1. State the concrete outcome and non-goals.
2. Inspect enough current state to replace assumptions with facts.
3. Identify dependencies, authority boundaries, and external side effects.
4. Split work into independently verifiable steps.
5. Put read-only discovery before mutation.
6. Define success checks and rollback for every risky mutation.
7. Keep one step active at a time and update the plan when evidence changes.

Skip formal planning for a single safe, reversible action. Do not use a plan as a substitute for required approval.
