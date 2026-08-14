# Release process

This checklist defines the minimum evidence required for an Agent Template
release. Complete it for every release and apply the additional stable-release
review before publishing a new major version.

## Prepare the release

- [ ] Classify the release as patch, minor, or major using
  `docs/compatibility.md`.
- [ ] Inventory changes to the initializer CLI, configuration versions,
  installation receipt, generated paths, skills, integrations, bundles, and host
  hook contracts.
- [ ] Add deprecation and migration guidance for every affected public interface.
- [ ] Confirm the version agrees in `pyproject.toml`, the README badge,
  `CHANGELOG.md`, and the planned tag.
- [ ] Confirm `SECURITY.md` names the release line that will receive fixes.
- [ ] Resolve every release-blocking defect and document any accepted limitation.

## Validate behavior

- [ ] Run a clean initializer dry run and installed generation for every supported
  host profile.
- [ ] Validate the generated harnesses and inspect their native configuration,
  hook events, capability and integration selection, receipt, and documentation.
- [ ] Exercise migrations described for this release against a representative
  harness from the previous supported version.
- [ ] Run the complete local suite:

```bash
uv run python scripts/validate_repository.py
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run mypy harness scripts tests
uv lock --check
git diff --check
```

- [ ] Confirm required CI and CodeQL jobs pass on every supported Python version.

## Review security and supply chain

- [ ] Review policy, permission, hook, authentication, write-target, and external
  side-effect changes.
- [ ] Verify every active integration still uses its official source and current
  endpoint, requests no embedded credential, and has a documented revoke path.
- [ ] Confirm generated Actions use immutable commit SHAs and least-privilege
  permissions.
- [ ] Review dependency and lockfile changes and address known vulnerabilities.
- [ ] Run the repository's secret-scanning preflight and confirm the release
  contains no credentials, personal paths, private links, or generated audit data.
- [ ] Confirm security-sensitive behavior has regression coverage and does not
  silently weaken the portable policy.

## Review documentation and support

- [ ] Keep the README, initializer guide, generated README, compatibility policy,
  ADRs, security model, and changelog consistent with executable behavior.
- [ ] Confirm supported hosts, Python versions, prerequisites, and recovery steps
  are current.
- [ ] Confirm links and example commands resolve and run as documented.
- [ ] Record support boundaries, known limitations, and maintainer ownership for
  release-critical paths.

## Publish and verify

- [ ] Merge the release pull request only after review and required checks pass.
- [ ] Create the signed or annotated `vX.Y.Z` tag from the reviewed main-branch
  commit and push it without rewriting existing tags.
- [ ] Publish a GitHub Release whose notes summarize behavior changes,
  compatibility, migrations, security impact, and validation evidence.
- [ ] Verify the tag, source archive, README badge, changelog links, and repository
  default branch after publication.
- [ ] Run one clean clone-and-initialize smoke test from the published tag.

## Additional major-release readiness

Before the first release in a new major line:

- [ ] Re-inventory every public interface and remove only deprecations announced
  in the previous major line.
- [ ] Provide complete migration and rollback guidance from the latest supported
  prior-major release.
- [ ] Confirm security, support, issue-reporting, and release ownership are
  documented and operational.
- [ ] Confirm no unresolved breaking changes remain assigned to the milestone.
