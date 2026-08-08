"""Connect persistent lifecycle state to trusted guarded execution."""

from __future__ import annotations

from typing import Any

from harness.approvals import ApprovalRecord
from harness.guarded_runtime import GuardedRuntime
from harness.guardrails import GuardrailOutcome
from harness.lifecycle import LifecycleEngine, LifecycleError
from harness.runtime import (
    ControlState,
    PostToolEvent,
    PreToolEvent,
    RunContext,
    ToolTimeoutError,
    ToolCallControl,
)


class LifecycleRuntime:
    """Provider-neutral managed runtime with persistent bounded run state."""

    def __init__(self, guarded: GuardedRuntime, lifecycle: LifecycleEngine) -> None:
        self._guarded = guarded
        self.lifecycle = lifecycle

    @property
    def hooks_enabled(self) -> bool:
        return self._guarded.hooks_enabled

    def start_run(self) -> RunContext:
        """Create a run and advance through inspection to its first ready state."""
        run = self._guarded.start_run()
        self.lifecycle.create(run)
        self.lifecycle.inspect(run.run_id)
        self.lifecycle.ready(run.run_id)
        return run

    def recover_run(self, run_id: str) -> RunContext:
        """Restore safe state; ambiguous executing calls become terminally blocked."""
        state = self.lifecycle.recover(run_id)
        run = RunContext(run_id=state["run_id"], actor=state["actor"])
        if state["status"] in {"completed", "failed", "cancelled", "blocked"}:
            return run
        if state["status"] == "awaiting_approval":
            if state["pending_call"] is None:
                raise LifecycleError("Persisted approval state is missing its exact call")
            try:
                self._guarded.restore_pending(_pre_event(state["pending_call"]))
            except Exception:  # noqa: BLE001 - changed policy invalidates persisted authority
                self.lifecycle.block(
                    run_id,
                    "Persisted approval call no longer passes current trusted policy",
                )
                raise
        else:
            self._guarded.restore_run(run)
        return run

    def record_model_turn(self, run: RunContext) -> dict[str, Any]:
        return self.lifecycle.record_model_turn(run.run_id)

    def inspect(self, run: RunContext, reason: str = "Inspection started") -> dict[str, Any]:
        return self.lifecycle.inspect(run.run_id, reason)

    def ready(self, run: RunContext, reason: str = "Run is ready") -> dict[str, Any]:
        return self.lifecycle.ready(run.run_id, reason)

    def prepare_tool_call(
        self,
        run: RunContext,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        retry: bool = False,
    ) -> ToolCallControl:
        self.lifecycle.require_status(run.run_id, "ready")
        control = self._guarded.prepare_tool_call(run, tool_id, arguments)
        decision = self._guarded.decision_for(control.event.tool_call_id)
        if control.state == ControlState.BLOCKED:
            self.lifecycle.block(
                run.run_id, control.reason or "Trusted guardrails blocked the call"
            )
            return control
        if retry and decision.action_class != "read_only":
            reason = "Automatic retries are limited to trusted read-only calls"
            blocked = self._guarded.abandon(control, reason)
            self.lifecycle.block(run.run_id, reason)
            return blocked
        try:
            lifecycle_state = self.lifecycle.begin_tool_call(
                control.event,
                awaiting_approval=decision.outcome == GuardrailOutcome.PAUSE,
                retry=retry,
            )
        except LifecycleError as exc:
            blocked = self._guarded.abandon(control, str(exc))
            self.lifecycle.block(run.run_id, str(exc))
            return blocked
        if lifecycle_state["status"] == "blocked":
            return self._guarded.abandon(
                control, lifecycle_state["terminal_reason"] or "Lifecycle blocked the call"
            )
        return control

    def grant(self, tool_call_id: str, granted_by: str) -> ApprovalRecord:
        """Create a persistent exact approval through the host-only trusted path."""
        state = self._state_for_call(tool_call_id)
        self.lifecycle.require_status(state["run_id"], "awaiting_approval")
        return self._guarded.grant(tool_call_id, granted_by)

    def resume(self, tool_call_id: str, approval_id: str) -> ToolCallControl:
        state = self._state_for_call(tool_call_id)
        self.lifecycle.require_status(state["run_id"], "awaiting_approval")
        persisted_control = ToolCallControl(
            event=_pre_event(state["pending_call"]),
            state=ControlState.AWAITING_APPROVAL,
            reason="Persisted approval pause",
        )
        control: ToolCallControl | None = None
        try:
            control = self._guarded.resume(tool_call_id, approval_id)
            self.lifecycle.approval_resumed(control.event.run_id)
        except Exception:  # noqa: BLE001 - failed approval resume must terminate authority
            self._guarded.abandon(control or persisted_control, "Approval resume failed")
            self.lifecycle.block(
                state["run_id"],
                "Approval resume failed or was interrupted; start a new run",
            )
            raise
        if control is None:  # pragma: no cover - defensive type narrowing
            raise LifecycleError("Approval resume did not return an executable control")
        return control

    def execute(self, control: ToolCallControl) -> PostToolEvent:
        state = self.lifecycle.require_status(control.event.run_id, "executing")
        if (
            state["pending_call"] is None
            or state["pending_call"]["tool_call_id"] != control.event.tool_call_id
        ):
            raise LifecycleError("Executable control does not match persisted lifecycle state")
        try:
            result = self._guarded.execute(
                control, self.lifecycle.config["limits"]["tool_timeout_seconds"]
            )
        except ToolTimeoutError as exc:
            self.lifecycle.record_tool_timeout(
                control.event.run_id,
                control.event.tool_call_id,
                str(exc) or "Tool execution timed out",
            )
            raise
        except Exception:  # noqa: BLE001 - an interrupted dispatch is ambiguous
            self.lifecycle.block(
                control.event.run_id,
                "Execution dispatch failed; side effects may be ambiguous",
            )
            raise
        self.lifecycle.record_tool_result(result)
        return result

    def begin_validation(self, run: RunContext) -> dict[str, Any]:
        return self.lifecycle.begin_validation(run.run_id)

    def add_validation_evidence(
        self,
        run: RunContext,
        validator: str,
        summary: str,
        *,
        passed: bool,
    ) -> dict[str, Any]:
        return self.lifecycle.add_validation_evidence(run.run_id, validator, summary, passed=passed)

    def complete(self, run: RunContext) -> dict[str, Any]:
        return self.lifecycle.complete(run.run_id)

    def fail(self, run: RunContext, reason: str) -> dict[str, Any]:
        self._abandon_active_call(run, reason)
        return self.lifecycle.fail(run.run_id, reason)

    def cancel(self, run: RunContext, reason: str = "Run cancelled") -> dict[str, Any]:
        self._abandon_active_call(run, reason)
        return self.lifecycle.cancel(run.run_id, reason)

    def _abandon_active_call(self, run: RunContext, reason: str) -> None:
        state = self.lifecycle.get(run.run_id)
        pending = state.get("pending_call")
        if pending is not None and state["status"] in {"awaiting_approval", "executing"}:
            control = ToolCallControl(
                event=_pre_event(pending),
                state=(
                    ControlState.AWAITING_APPROVAL
                    if state["status"] == "awaiting_approval"
                    else ControlState.READY
                ),
                reason="Persisted active call",
            )
            self._guarded.abandon(control, reason)

    def state(self, run: RunContext | str) -> dict[str, Any]:
        run_id = run if isinstance(run, str) else run.run_id
        return self.lifecycle.get(run_id)

    def _state_for_call(self, tool_call_id: str) -> dict[str, Any]:
        """Resolve a run only from the adapter-owned persisted pending event."""
        event = self._guarded.pending_event(tool_call_id)
        state = self.lifecycle.get(event.run_id)
        pending = state.get("pending_call")
        if pending is None or pending.get("tool_call_id") != tool_call_id:
            raise LifecycleError("Persisted approval call does not exist")
        return state


def _pre_event(payload: dict[str, Any]) -> PreToolEvent:
    return PreToolEvent(
        schema_version=payload["schema_version"],
        event_type=payload["event_type"],
        run_id=payload["run_id"],
        tool_call_id=payload["tool_call_id"],
        tool_id=payload["tool_id"],
        arguments=payload["arguments"],
        requested_at=payload["requested_at"],
        actor=payload["actor"],
    )
