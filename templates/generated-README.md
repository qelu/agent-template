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

This project was generated transactionally by the Agent Harness Initializer.
The resolved choices are recorded in `.agent-harness/installation.yaml`. A
`validation: passed` receipt means the initializer provisioned the environment
and completed repository validation, tests, and selected quality/security checks
before publishing this folder.

The canonical agent contract is `agent/AGENT.md`. Deployment choices live in
`config/deployment.yaml`; tools, guardrails, approvals, lifecycle policy, and
capabilities live under `config/`.

## Runtime

`runtime.adapter: none` means the selected host owns the model loop; it does not
mean the host agent is disabled. `reference` enables the deterministic local
runtime boundary. Provider SDK runtimes require a separately implemented and
conformance-tested adapter.

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
