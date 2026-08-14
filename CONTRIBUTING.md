# Contributing

Contributions are welcome through pull requests.

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development workflow

1. Fork the repository and create a focused branch from `main`.
2. Make small, reviewable changes with tests and documentation where appropriate.
3. Run the complete validation suite.
4. Open a pull request describing the problem, approach, risk, and validation.

```bash
uv sync --extra dev
uv run python scripts/validate_repository.py
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run mypy harness scripts tests
uv lock --check
git diff --check
```

Documentation changes must keep the source README, initializer guide, generated
README template, ADRs, security model, and changelog consistent with executable
behavior. When policy semantics change, update the cross-host conformance tests
and the accepted architecture decision in the same pull request.

Use imperative commit subjects, keep unrelated work in separate commits, and do
not commit generated caches, credentials, local environment files, or secrets.
Maintainers may squash merge a pull request to keep release history concise.

## Contributing a capability

Propose a capability when it adds reusable behavior rather than project-specific
instructions. Skills package model-facing procedures, workflows package reusable
automation, and runbooks document repeatable operator procedures. Open an issue
before implementing a capability that introduces a dependency, external service,
new write target, authentication requirement, or material policy change.

Scaffold the contribution from the repository root:

```bash
uv run python scripts/create_extension.py \
  --type skill \
  --id summarize-evidence \
  --name "Summarize Evidence"
```

Use `workflow` or `runbook` instead of `skill` when appropriate. Skill and
workflow scaffolds are registered in `config/capabilities.yaml` with an
`experimental` status. Keep the generated ID, path, description, and `when`
trigger accurate as the implementation evolves. Runbooks are not registered as
selectable capabilities.

A capability pull request must:

- explain the user need, trigger, expected behavior, and why the capability is
  reusable;
- identify permissions, write targets, external services, dependencies, trust
  boundaries, and failure behavior;
- contain no credentials, private links, personal data, or unlicensed assets;
- include focused tests and documentation, including generated-host coverage
  whenever installation or native host behavior changes;
- keep the default generated harness small and provider-neutral; and
- report the complete validation commands and results in the pull request.

Promote a registered capability from `experimental` to `active` only after its
implementation, safety review, tests, and documentation are complete. Make the
promotion in the same reviewed pull request so Git records the evidence and
approval together. Maintainers may keep a capability experimental, request a
narrower scope, or decline it when its authority or maintenance cost is not
justified by the reusable value.

## Contributing an integration

Register external services in `config/integrations.yaml`, independently from
model-facing capabilities. Use an official remote MCP, provider CLI, or host plugin;
link its authoritative setup source and declare authentication, supported hosts,
data classes, write capability, endpoint, and default approval posture. Integration
entries also declare credential environment variables or CLI installation and setup
commands when applicable; those values must remain non-secret and reviewable. Integration
changes must include native-host generation tests plus setup, smoke-test, and revoke
guidance. Never commit credentials or make an optional integration required for host
startup. Add it to a bundle only when that shortcut remains understandable in the
initializer's expanded plan.

## Compatibility and releases

The project follows Semantic Versioning. Preserve documented 1.x interfaces within
the major release line; record breaking changes explicitly and reserve them for a
new major version. User-visible changes should add an entry under `Unreleased` in
`CHANGELOG.md`. Review `docs/compatibility.md` before changing a documented CLI,
configuration format, generated path, or hook contract. Include migration guidance
whenever operator action is required. Maintainers must complete
`docs/releasing.md` before publishing a release.

## Security reports

Do not disclose vulnerabilities in issues or pull requests. Follow `SECURITY.md`.
