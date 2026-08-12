#!/usr/bin/env python3
"""Antigravity 2.0 hook protocol bridge."""

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
    parser.add_argument("--event", required=True, choices=("PreToolUse", "PreInvocation"))
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        payload = read_payload()
        policy = load_policy(root)
        tool_call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
        event = HookEvent(
            host="antigravity",
            event=args.event,
            run_id=str(payload.get("conversationId") or "unknown"),
            turn_id=str(payload["stepIdx"]) if payload.get("stepIdx") is not None else None,
            tool_name=str(tool_call["name"]) if tool_call.get("name") is not None else None,
            tool_input=tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {},
        )
        decision = evaluate_policy(event, policy, root)
        audit_event(root, event, decision, policy)
    except (OSError, ValueError) as exc:
        message = f"Antigravity guardrail failed closed: {exc}"
        print(message, file=sys.stderr)
        if args.event == "PreToolUse":
            emit({"decision": "deny", "reason": "Project guardrail unavailable; tool denied."})
        else:
            emit({"injectSteps": [{"ephemeralMessage": message}]})
        return 0

    if args.event == "PreInvocation":
        emit({"injectSteps": [{"ephemeralMessage": plan_context(event.run_id)}]})
    else:
        emit({"decision": decision.outcome, "reason": decision.reason})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
