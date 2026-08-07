---
name: safe-tool-use
description: Select and operate tools within configured scope, least privilege, and approval boundaries while validating effects. Use whenever a task calls tools, runs commands, modifies files or systems, accesses credentials, sends external communications, or could produce destructive or externally visible effects.
---

# Safe tool use

1. Resolve the exact target with read-only checks.
2. Classify the action as read-only, reversible local change, destructive change, external side effect, or permission expansion.
3. Read `config/policies.yaml` for the applicable authority boundary.
4. Use typed, purpose-built tools before raw shell commands when available.
5. Pass the minimum data and permissions required.
6. Preview or dry-run risky operations when the tool supports it.
7. Verify the intended result and check for adjacent harm.
8. Record metadata without arguments or secret values.

Fail closed when target, scope, or authorization is ambiguous and the ambiguity could cause material harm.
