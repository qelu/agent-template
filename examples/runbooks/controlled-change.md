# Runbook: Controlled change

## Purpose

Apply a scoped change with validation and rollback.

## Preconditions

- Confirm target and ownership.
- Capture current state or backup.
- Confirm the action is not denied and identify any native confirmation required
  by `config/policies.yaml`.

## Procedure

1. Run read-only diagnostics.
2. State the exact mutation and expected effect.
3. Execute only after the applicable native confirmation boundary is satisfied.
   Never treat confirmation as authority to override `deny`.
4. Stop on unexpected output; do not improvise a broader mutation.

## Validation

Check both the intended outcome and adjacent health signals.

## Rollback

Restore the captured state and validate recovery.

## Evidence

Record commands, timestamps, results, and unresolved uncertainty without secrets.
