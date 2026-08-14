---
name: dependency-change-review
description: Review additions, updates, removals, lockfile changes, actions, images, and toolchain dependencies for necessity, provenance, compatibility, supply-chain risk, validation, and rollback. Use whenever a dependency or its resolved graph changes materially.
---

# Dependency change review

1. Identify the user need and confirm whether existing code or an installed dependency
   already satisfies it.
2. Verify the authoritative package, publisher, release, license, support status,
   maintenance activity, and current security advisories using primary sources.
3. Inspect the manifest and lockfile diff. Account for transitive additions, install or
   build scripts, source registries, checksums, binary downloads, and platform variance.
4. Review new runtime authority: network access, filesystem writes, environment or secret
   access, subprocesses, native code, external services, and generated artifacts.
5. Prefer the narrowest supported version constraint and immutable pinning where the
   ecosystem expects it. Never weaken integrity checks to make resolution succeed.
6. Validate supported runtimes, clean installation, static checks, focused behavior,
   complete tests, and a vulnerability scan appropriate to the ecosystem.
7. Define rollback by restoring the manifest and lockfile together, then rerunning the
   same clean validation.
8. Report the decision, evidence, residual risk, transitive impact, and any required
   migration or durable documentation.

Do not install or approve a dependency solely because this review recommends it; the
original task must authorize the change.
