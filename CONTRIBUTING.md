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

## Compatibility and releases

The project follows Semantic Versioning. Preserve documented 1.x interfaces within
the major release line; record breaking changes explicitly and reserve them for a
new major version. User-visible changes should add an entry under `Unreleased` in
`CHANGELOG.md`.

## Security reports

Do not disclose vulnerabilities in issues or pull requests. Follow `SECURITY.md`.
