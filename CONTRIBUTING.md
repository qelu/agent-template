# Contributing

Contributions are welcome through pull requests.

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
git diff --check
```

Use imperative commit subjects, keep unrelated work in separate commits, and do
not commit generated caches, credentials, local environment files, or secrets.
Maintainers may squash merge a pull request to keep release history concise.

## Compatibility and releases

The project follows Semantic Versioning. Before 1.0, document breaking changes in
the changelog and increment the minor version. User-visible changes should add an
entry under `Unreleased` in `CHANGELOG.md`.

## Security reports

Do not disclose vulnerabilities in issues or pull requests. Follow `SECURITY.md`.
