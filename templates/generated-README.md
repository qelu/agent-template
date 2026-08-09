# __AGENT_NAME__

__AGENT_ROLE__ running as a host-native agent harness.

## Goal

__AGENT_GOAL__

## Start

Run the selected host from this project directory. The canonical contract is
`agent/AGENT.md`; the root host instruction file loads it automatically.

Validate the generated harness with:

```bash
uv sync --extra dev
uv run python scripts/validate_harness.py
```

The installation choices are recorded in
`.agent-harness/installation.yaml`. `execution: host-native` means the selected
host owns inference, authentication, sessions, sandboxing, and tool execution.
No provider SDK or duplicate model runtime is installed.

Selected skills live in the host's native project directory. Native permission
and hook configuration supplies project-level safety controls. The shared hook
uses the host session/conversation identifier as the run ID, blocks a small set
of deterministic destructive and credential-access patterns, and writes
redacted metadata under `.agent-harness/audit/`.

Plan approval applies only to the exact plan presented. A later state-changing
request is new scope, even in the same conversation. Native tool approval is a
separate host decision.

An unbounded request such as "delete all my files" must be refused in favor of
an exact, recoverable target. The hook blocks common system, home, device, and
credential-path operations, while the host sandbox limits writes to the
workspace. Keep the workspace narrow: the run ID labels audit events but does
not authorize them, and the pattern-based hook is not a complete shell sandbox.

## License

Apache-2.0. See `LICENSE`.
