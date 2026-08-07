"""Connect trusted guardrail decisions to the normalized runtime boundary."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from harness.approvals import ApprovalRecord, ApprovalStore
from harness.guardrails import GuardrailDecision, GuardrailOutcome, TrustedGuardrails
from harness.runtime import (
    PostToolEvent,
    PreToolEvent,
    RunContext,
    RuntimeBoundary,
    ToolCallControl,
)


class GuardedRuntimeError(RuntimeError):
    """Raised when callers bypass or misuse guarded runtime state."""


class GuardedRuntime:
    """Expose only calls authorized through trusted policy and exact approvals."""

    def __init__(
        self,
        boundary: RuntimeBoundary,
        guardrails: TrustedGuardrails,
        approvals: ApprovalStore,
    ) -> None:
        self._boundary = boundary
        self._guardrails = guardrails
        self._approvals = approvals
        self._pending: dict[str, PreToolEvent] = {}
        self._authorized: set[str] = set()
        self._decisions: dict[str, GuardrailDecision] = {}

    @property
    def hooks_enabled(self) -> bool:
        return self._boundary.hooks_enabled

    def start_run(self) -> RunContext:
        return self._boundary.start_run()

    def prepare_tool_call(
        self, run: RunContext, tool_id: str, arguments: dict[str, Any]
    ) -> ToolCallControl:
        control = self._boundary.prepare_tool_call(run, tool_id, arguments)
        decision = self._guardrails.evaluate(control.event)
        call_id = control.event.tool_call_id
        self._decisions[call_id] = decision
        if decision.outcome == GuardrailOutcome.ALLOW:
            self._authorized.add(call_id)
            return control
        if decision.outcome == GuardrailOutcome.BLOCK:
            return self._boundary.block(control, decision.reason)
        paused = self._boundary.pause_for_approval(control, decision.reason)
        self._pending[call_id] = control.event
        return paused

    def grant(self, tool_call_id: str, granted_by: str) -> ApprovalRecord:
        """Grant only a call currently paused by trusted policy."""
        try:
            event = self._pending[tool_call_id]
        except KeyError as exc:
            raise GuardedRuntimeError(
                f"Tool call is not pending trusted approval: {tool_call_id}"
            ) from exc
        return self._approvals.grant(event, granted_by)

    def resume(self, tool_call_id: str, approval_id: str) -> ToolCallControl:
        try:
            event = self._pending[tool_call_id]
        except KeyError as exc:
            raise GuardedRuntimeError(
                f"Tool call is not pending trusted approval: {tool_call_id}"
            ) from exc
        decision = self._guardrails.evaluate(event, approval_id)
        self._decisions[tool_call_id] = decision
        if decision.outcome != GuardrailOutcome.ALLOW:
            raise GuardedRuntimeError(decision.reason)
        control = self._boundary.resume(tool_call_id)
        del self._pending[tool_call_id]
        self._authorized.add(tool_call_id)
        return control

    def execute(self, control: ToolCallControl) -> PostToolEvent:
        call_id = control.event.tool_call_id
        if call_id not in self._authorized:
            raise GuardedRuntimeError(
                f"Tool call has not passed trusted guardrails: {call_id}"
            )
        self._authorized.remove(call_id)
        event = self._boundary.execute(control)
        decision = self._decisions[call_id]
        classified = replace(
            event,
            output_trust="untrusted" if decision.untrusted_output else "trusted",
        )
        self._boundary.validate_event(classified)
        return classified

    def decision_for(self, tool_call_id: str) -> GuardrailDecision:
        try:
            return self._decisions[tool_call_id]
        except KeyError as exc:
            raise GuardedRuntimeError(f"No guardrail decision for call: {tool_call_id}") from exc
