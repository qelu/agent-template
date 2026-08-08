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

## License

Apache-2.0. See `LICENSE`.
