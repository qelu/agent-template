---
name: documentation-maintenance
description: Create or update durable architecture, decision, environment, runbook, and operational documentation after material changes. Use when behavior, topology, dependencies, authority, recovery procedures, or repeatable operations change, or when documentation drift is discovered.
---

# Documentation maintenance

1. Choose the durable artifact: ADR for a decision, runbook for operations, environment document for inventory, standard for conventions, or report for point-in-time analysis.
2. Update the authoritative document instead of duplicating facts.
3. Include prerequisites, risk, validation, rollback, ownership, and source references where relevant.
4. Keep secrets and volatile runtime state out of documentation.
5. Verify links, commands, paths, and examples against the current repository.
6. Record uncertainty or untested recovery steps explicitly.

Do not create documentation whose only purpose is to narrate the editing process.
