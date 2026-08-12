---
name: safe-tool-use
description: Select and operate tools within configured scope, least privilege, and approval boundaries while validating effects. Use whenever a task calls tools, runs commands, modifies files or systems, accesses credentials, sends external communications, or could produce destructive or externally visible effects.
---

# Safe tool use

1. Resolve the exact target with read-only checks.
2. Classify the action as read, write, delete, external side effect, or unknown.
3. Read `config/policies.yaml` for the applicable authority boundary.
4. Never attempt an action the policy classifies as denied; approval cannot override a denial.
5. Use typed, purpose-built tools before raw shell commands when available.
6. Pass the minimum data and permissions required.
7. Preview or dry-run approved risky operations when the tool supports it.
8. Verify the intended result and check for adjacent harm.
9. Record metadata without arguments or secret values.

Fail closed when target, scope, or authorization is ambiguous and the ambiguity could cause material harm.
