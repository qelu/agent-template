"""Small deterministic policy primitives used by hooks and tests."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.configuration import load_yaml


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def evaluate_tool_call(root: Path, payload: dict[str, Any]) -> Decision:
    """Evaluate generic action metadata; platform adapters should normalize payloads."""
    policy = load_yaml(root / "config" / "policies.yaml")
    command = str(payload.get("command", ""))
    for denied in policy.get("safety", {}).get("deny_shell_patterns", []):
        if str(denied).lower() in command.lower():
            return Decision(False, f"Command matches denied pattern: {denied}")

    action_class = payload.get("action_class", "read_only")
    approval = bool(payload.get("explicit_approval", False))
    authorization = policy.get("authorization", {})
    requirement = authorization.get(action_class, "explicit_approval")
    if requirement == "explicit_approval" and not approval:
        return Decision(False, f"{action_class} requires explicit approval")
    return Decision(True, "Policy checks passed")
