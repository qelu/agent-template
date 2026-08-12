"""Shared deterministic policy evaluation for host-native hook bridges."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SYSTEM_DESTRUCTIVE_COMMANDS = (
    re.compile(
        r"(?:^|[;&|]\s*)(?:sudo\s+)?rm\s+-[^\s]*(?:r[^\s]*f|f[^\s]*r)[^\s]*\s+"
        r"(?:--[^\s]+\s+)*['\"]?(?:/|/\*|~|~/|\$HOME|\$\{HOME\})['\"]?"
        r"(?:\s|$|[;&|*])"
    ),
    re.compile(r"(?:^|[;&|]\s*)mkfs(?:\.|\s)"),
    re.compile(r"(?:^|[;&|]\s*)dd\s+[^\n]*\bof=/dev/"),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*;\s*\}\s*;\s*:"),
)
PATH_KEY_MARKERS = (
    "path",
    "file",
    "target",
    "directory",
    "cwd",
    "root",
    "uri",
    "source",
    "destination",
)


@dataclass(frozen=True)
class HookEvent:
    host: str
    event: str
    run_id: str
    turn_id: str | None
    tool_name: str | None
    tool_input: dict[str, Any]
    prompt: str | None = None


def load_policy(root: Path) -> dict[str, Any]:
    path = root / "config" / "policies.yaml"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("hook policy must be a JSON-compatible YAML object")
    if not isinstance(payload.get("safety", {}).get("deny_shell_patterns"), list):
        raise ValueError("hook policy must declare safety.deny_shell_patterns")
    if not isinstance(payload.get("secrets", {}).get("denied_path_markers"), list):
        raise ValueError("hook policy must declare secrets.denied_path_markers")
    if not isinstance(payload.get("audit"), dict):
        raise ValueError("hook policy must declare audit settings")
    return payload


def blocked_reason(event: HookEvent, policy: dict[str, Any]) -> str | None:
    command = _command(event.tool_input)
    configured = policy.get("safety", {}).get("deny_shell_patterns", [])
    if command and (
        any(str(pattern) in command for pattern in configured)
        or any(pattern.search(command) for pattern in SYSTEM_DESTRUCTIVE_COMMANDS)
    ):
        return "Blocked destructive command targeting a system, home, or device boundary."

    candidates = [command] if command else []
    candidates.extend(_path_values(event.tool_input))
    denied_markers = policy.get("secrets", {}).get("denied_path_markers", [])
    if any(_contains_path_marker(value, denied_markers) for value in candidates):
        return "Blocked access to a sensitive credential or environment path."
    return None


def plan_context(run_id: str) -> str:
    return (
        f"Harness run ID: {run_id}. "
        "Approvals are scoped to the exact plan or action explicitly presented. "
        "A new state-changing request requires a fresh plan when the planning rules apply; "
        "approval of an earlier plan never authorizes later requests. Native tool approvals "
        "remain separate from plan approval."
    )


def audit_event(root: Path, event: HookEvent, outcome: str, policy: dict[str, Any]) -> None:
    if not policy.get("audit", {}).get("enabled", False):
        return
    directory = root / ".agent-harness" / "audit"
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": event.host,
        "run_id": event.run_id,
        "turn_id": event.turn_id,
        "event": event.event,
        "tool_name": event.tool_name,
        "input_digest": _digest(event.tool_input),
        "prompt_digest": _digest(event.prompt) if event.prompt is not None else None,
        "outcome": outcome,
    }
    path = directory / f"{_safe_run_id(event.run_id)}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def read_payload() -> dict[str, Any]:
    import sys

    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    return payload


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def _command(tool_input: dict[str, Any]) -> str | None:
    for key in ("command", "CommandLine"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def _path_values(value: object, key: str = "") -> list[str]:
    if isinstance(value, str):
        return [value] if any(marker in key.lower() for marker in PATH_KEY_MARKERS) else []
    if isinstance(value, dict):
        result: list[str] = []
        for child_key, child in value.items():
            result.extend(_path_values(child, str(child_key)))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_path_values(child, key))
        return result
    return []


def _contains_path_marker(value: str, markers: object) -> bool:
    if not isinstance(markers, list):
        return False
    for marker in markers:
        if not isinstance(marker, str):
            continue
        pattern = re.compile(
            rf"(?:^|[/\\\s'\"]){re.escape(marker)}(?:[^/\\\s'\"]*)?(?:$|[/\\\s'\"])",
            re.IGNORECASE,
        )
        if pattern.search(value):
            return True
    return False


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_run_id(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return candidate[:120] or "unknown"
