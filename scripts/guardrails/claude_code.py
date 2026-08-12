#!/usr/bin/env python3
"""Claude Code hook protocol bridge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core import (  # type: ignore[import-not-found]
    HookEvent,
    audit_event,
    emit,
    evaluate_policy,
    load_policy,
    plan_context,
    read_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        payload = read_payload()
        policy = load_policy(root)
        event = HookEvent(
            host="claude-code",
            event=str(payload.get("hook_event_name") or "unknown"),
            run_id=str(payload.get("session_id") or "unknown"),
            turn_id=None,
            tool_name=str(payload["tool_name"]) if payload.get("tool_name") is not None else None,
            tool_input=payload.get("tool_input")
            if isinstance(payload.get("tool_input"), dict)
            else {},
            prompt=payload.get("prompt") if isinstance(payload.get("prompt"), str) else None,
        )
        decision = evaluate_policy(event, policy, root)
        audit_event(root, event, decision, policy)
    except (OSError, ValueError) as exc:
        print(f"Claude Code guardrail failed closed: {exc}", file=sys.stderr)
        return 2

    if event.event == "PreToolUse":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision.outcome,
                    "permissionDecisionReason": decision.reason,
                }
            }
        )
    elif event.event == "UserPromptSubmit":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": plan_context(event.run_id),
                }
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
