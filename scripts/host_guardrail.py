#!/usr/bin/env python3
"""Portable safety hook for Codex, Claude Code, and Antigravity projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DANGEROUS_COMMANDS = (
    re.compile(
        r"(?:^|\s)(?:sudo\s+)?rm\s+-(?:[^\s]*r[^\s]*f|[^\s]*f[^\s]*r)\s+(?:/|~|\$HOME)(?:\s|$)"
    ),
    re.compile(r"(?:^|\s)mkfs(?:\.|\s)"),
    re.compile(r"(?:^|\s)dd\s+[^\n]*\bof=/dev/"),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*;\s*\}\s*;\s*:"),
)
SENSITIVE_PATH = re.compile(
    r"(?:^|[/\\])(?:\.env(?:\.[^/\\]+)?|\.ssh|credentials(?:\.[^/\\]+)?|secrets?(?:\.[^/\\]+)?)(?:$|[/\\])",
    re.IGNORECASE,
)


def _field(payload: dict[str, Any], snake: str, camel: str) -> Any:
    return payload.get(snake, payload.get(camel))


def normalize_event(payload: dict[str, Any], host: str) -> dict[str, Any]:
    run_id = _field(payload, "session_id", "conversationId")
    event = _field(payload, "hook_event_name", "hookEventName")
    tool_name = _field(payload, "tool_name", "toolName")
    tool_input = _field(payload, "tool_input", "toolInput")
    turn_id = _field(payload, "turn_id", "turnId")
    prompt = payload.get("prompt")
    return {
        "host": host,
        "run_id": str(run_id or "unknown"),
        "event": str(event or "unknown"),
        "turn_id": None if turn_id is None else str(turn_id),
        "tool_name": None if tool_name is None else str(tool_name),
        "tool_input": tool_input if isinstance(tool_input, dict) else {},
        "prompt": prompt if isinstance(prompt, str) else None,
    }


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_run_id(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return candidate[:120] or "unknown"


def _append_audit(root: Path, event: dict[str, Any], outcome: str) -> None:
    directory = root / ".agent-harness" / "audit"
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "host": event["host"],
        "run_id": event["run_id"],
        "turn_id": event["turn_id"],
        "event": event["event"],
        "tool_name": event["tool_name"],
        "input_digest": _digest(event["tool_input"]),
        "prompt_digest": _digest(event["prompt"]) if event["prompt"] is not None else None,
        "outcome": outcome,
    }
    path = directory / f"{_safe_run_id(event['run_id'])}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(_strings(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_strings(child))
        return result
    return []


def blocked_reason(event: dict[str, Any]) -> str | None:
    tool_input = event["tool_input"]
    command = tool_input.get("command")
    if isinstance(command, str) and any(pattern.search(command) for pattern in DANGEROUS_COMMANDS):
        return "Blocked destructive command targeting a system, home, or device boundary."

    tool_name = (event["tool_name"] or "").lower()
    path_sensitive_tool = any(
        marker in tool_name for marker in ("read", "write", "edit", "patch", "file")
    )
    if path_sensitive_tool and any(SENSITIVE_PATH.search(value) for value in _strings(tool_input)):
        return "Blocked access to a sensitive credential or environment path."
    return None


def _prompt_context(event: dict[str, Any]) -> dict[str, object]:
    context = (
        f"Harness run ID: {event['run_id']}. "
        "Approvals are scoped to the exact plan or action explicitly presented. "
        "A new state-changing request requires a fresh plan when the planning rules apply; "
        "approval of an earlier plan never authorizes later requests. Native tool approvals "
        "remain separate from plan approval."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=("codex", "claude-code", "antigravity"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Guardrail hook received invalid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("Guardrail hook input must be a JSON object", file=sys.stderr)
        return 2

    event = normalize_event(payload, args.host)
    root = args.root.resolve()
    reason = blocked_reason(event)
    try:
        _append_audit(root, event, "denied" if reason else "observed")
    except OSError as exc:
        print(f"Guardrail audit failed closed: {exc}", file=sys.stderr)
        return 2

    if reason:
        print(reason, file=sys.stderr)
        return 2
    if event["event"] == "UserPromptSubmit":
        print(json.dumps(_prompt_context(event)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
