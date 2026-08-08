# __AGENT_NAME__

__AGENT_ROLE__ built from the Agent Template governed runtime.

## Goal

__AGENT_GOAL__

## Get started

```bash
uv sync --extra dev
uv run python scripts/validate_repository.py
uv run python -m unittest discover -s tests -v
```

The canonical agent contract is `agent/AGENT.md`. Deployment choices live in
`config/deployment.yaml`; tools, guardrails, approvals, lifecycle policy, and
capabilities live under `config/`.

## Runtime

The default runtime adapter is intentionally disabled. Initialize with
`--runtime reference` to use the deterministic reference boundary, or implement
a provider adapter behind the same governed interface.

Run a complete isolated plan, approval, tool, validation, and lifecycle example:

```bash
uv run python scripts/run_reference.py
```

The runner creates `runtime/reference-demo`, which is ignored by Git. It does not
activate a tool or change canonical configuration. Pass `--yes` and a fresh
`--workspace` for a non-interactive smoke test.

Runtime adapter implementations inherit the reusable contract in
`harness/adapter_conformance.py`. See `tests/test_adapter_conformance.py` for the
reference implementation and run it with:

```bash
uv run python -m unittest tests.test_adapter_conformance -v
```

## License

Apache-2.0. See `LICENSE`.
