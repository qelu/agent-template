#!/usr/bin/env python3
"""Run a complete governed lifecycle using the deterministic reference adapter."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.reference_adapter import ToolOutput  # noqa: E402
from harness.runtime import ControlState, SideEffect  # noqa: E402
from harness.runtime_factory import configured_runtime  # noqa: E402

DEMO_TOOL_ID = "demo.write-note"
DEFAULT_MESSAGE = "Hello from the governed reference harness."


def run_reference_demo(
    source_root: Path,
    workspace: Path,
    *,
    message: str = DEFAULT_MESSAGE,
    assume_yes: bool = False,
) -> dict[str, Any]:
    """Execute one exact plan and approved local write in an isolated workspace."""
    source_root = source_root.resolve()
    workspace = workspace.resolve()
    normalized_message = message.strip()
    if not normalized_message:
        raise ValueError("Demo message must not be empty")
    if workspace.exists():
        raise FileExistsError(f"Demo workspace already exists; refusing to overwrite: {workspace}")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root / "config", workspace / "config")
    _write_demo_configuration(workspace)

    output_path = workspace / "output" / "welcome.txt"

    def write_note(arguments: dict[str, Any]) -> ToolOutput:
        target = Path(str(arguments["path"]))
        content = str(arguments["content"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        effect = SideEffect(
            kind="file-write",
            target=str(target),
            description="Created the reference demonstration note.",
            reversible=True,
        )
        return ToolOutput(
            output={"path": str(target), "bytes_written": len(content.encode("utf-8"))},
            side_effects=(effect,),
        )

    runtime = configured_runtime(
        workspace,
        actor="host:reference-runner",
        handlers={DEMO_TOOL_ID: write_note},
    )
    run = runtime.start_run()
    runtime.record_model_turn(run)
    arguments = {"path": str(output_path), "content": normalized_message + "\n"}
    plan_state = runtime.define_plan(
        run,
        "Write and validate one demonstration note through the governed runtime.",
        [{"tool_id": DEMO_TOOL_ID, "arguments": arguments}],
    )
    plan = plan_state["plans"][plan_state["active_plan_revision"] - 1]
    print(f"Plan revision {plan['revision']}: {plan['summary']}")
    if not _approved("Approve this exact plan revision?", assume_yes):
        runtime.cancel(run, "Reference plan was not approved")
        raise RuntimeError("Reference plan was not approved")
    runtime.approve_plan(run, "human:reference-runner")

    control = runtime.prepare_tool_call(run, DEMO_TOOL_ID, arguments)
    if control.state != ControlState.AWAITING_APPROVAL:
        raise RuntimeError(f"Expected an exact tool approval pause, got: {control.state.value}")
    print(f"Tool approval required: {control.event.tool_id}")
    print(json.dumps(control.event.arguments, indent=2, sort_keys=True))
    if not _approved("Approve this exact tool call?", assume_yes):
        runtime.cancel(run, "Reference tool call was not approved")
        raise RuntimeError("Reference tool call was not approved")
    approval = runtime.grant(control.event.tool_call_id, "human:reference-runner")
    executable = runtime.resume(control.event.tool_call_id, approval.approval_id)
    result = runtime.execute(executable)
    if result.status != "succeeded":
        runtime.fail(run, result.error or "Reference tool execution failed")
        raise RuntimeError(result.error or "Reference tool execution failed")

    runtime.begin_validation(run)
    expected = normalized_message + "\n"
    passed = output_path.is_file() and output_path.read_text(encoding="utf-8") == expected
    runtime.add_validation_evidence(
        run,
        "reference-runner",
        "The exact approved note exists with the expected content.",
        passed=passed,
    )
    if not passed:
        raise RuntimeError("Reference output validation failed")
    completed = runtime.complete(run)
    summary = {
        "run_id": run.run_id,
        "status": completed["status"],
        "plan_revision": plan["revision"],
        "tool_call_id": control.event.tool_call_id,
        "output_path": str(output_path),
        "state_directory": str(workspace / "runtime" / "state"),
        "workspace": str(workspace),
    }
    print("Reference run completed:")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def _write_demo_configuration(workspace: Path) -> None:
    deployment = {
        "version": "1.0",
        "host": "portable",
        "documentation": {"provider": "none", "mode": "none"},
        "runtime": {"adapter": "reference"},
    }
    tools = {
        "version": "1.0",
        "tools": [
            {
                "id": DEMO_TOOL_ID,
                "action_class": "reversible_local_change",
                "risk_level": "medium",
                "approval": "always",
                "argument_rules": [],
                "filesystem": {
                    "access": "write",
                    "path_arguments": ["path"],
                    "require_exact_targets": False,
                },
                "shell": {"access": "none", "command_arguments": []},
                "network": {
                    "access": "none",
                    "host_arguments": [],
                    "allowed_hosts": [],
                },
                "private_data_egress": "deny",
                "untrusted_output": False,
            }
        ],
    }
    (workspace / "config" / "deployment.yaml").write_text(
        yaml.safe_dump(deployment, sort_keys=False), encoding="utf-8"
    )
    (workspace / "config" / "tools.yaml").write_text(
        yaml.safe_dump(tools, sort_keys=False), encoding="utf-8"
    )


def _approved(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        print(f"{prompt} yes (--yes)")
        return True
    if not sys.stdin.isatty():
        raise RuntimeError(f"Interactive approval is unavailable: {prompt} Pass --yes to approve.")
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=ROOT / "runtime" / "reference-demo",
        help="New isolated demo directory; existing paths are never overwritten.",
    )
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve the deterministic demo plan and tool call non-interactively.",
    )
    args = parser.parse_args()
    try:
        run_reference_demo(
            ROOT,
            args.workspace,
            message=args.message,
            assume_yes=args.yes,
        )
    except (FileExistsError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
