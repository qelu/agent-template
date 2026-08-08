import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

import yaml

from harness.approvals import ApprovalStore
from harness.guarded_runtime import GuardedRuntime, GuardedRuntimeError
from harness.guardrails import TrustedGuardrails
from harness.lifecycle import (
    LifecycleEngine,
    LifecycleError,
    load_lifecycle_config,
    validate_lifecycle_runtime_compatibility,
)
from harness.lifecycle_runtime import LifecycleRuntime
from harness.plans import PlanApprovalStore
from harness.reference_adapter import ReferenceRuntimeAdapter
from harness.runtime import PostToolEvent, PreToolEvent, RunContext, RuntimeBoundary, SideEffect
from harness.state_store import StateStoreError


class MutableClock:
    def __init__(self, value: str = "2026-08-07T12:00:00Z") -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class Sequence:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def __call__(self) -> str:
        return next(self._values)


def policy() -> dict[str, object]:
    return {
        "scope": {"read_roots": ["."], "write_roots": ["."], "denied_roots": []},
        "authorization": {
            "read_only": "autonomous",
            "reversible_local_change": "autonomous",
            "destructive_change": "explicit_approval",
            "external_side_effect": "explicit_approval",
            "permission_expansion": "explicit_approval",
        },
        "audit": {"redact_keys": ["password", "token", "secret", "api_key"]},
        "safety": {"deny_shell_patterns": ["rm -rf /", "mkfs"]},
    }


def tool(*, approval: str = "inherit", action_class: str = "read_only") -> dict[str, object]:
    return {
        "id": "test.tool",
        "action_class": action_class,
        "risk_level": "low" if action_class == "read_only" else "medium",
        "approval": approval,
        "argument_rules": [],
        "filesystem": {
            "access": "none",
            "path_arguments": [],
            "require_exact_targets": False,
        },
        "shell": {"access": "none", "command_arguments": []},
        "network": {"access": "none", "host_arguments": [], "allowed_hosts": []},
        "private_data_egress": "deny",
        "untrusted_output": False,
    }


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = Path(__file__).resolve().parent.parent
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self._copy_contracts()
        self.clock = MutableClock()
        self.lifecycle = LifecycleEngine(self.root, clock=self.clock)

    def test_legal_transitions_and_evidence_gate_completion(self) -> None:
        run = RunContext("run-1", "trusted-host")
        created = self.lifecycle.create(run)
        self.assertEqual(created["status"], "created")
        self.lifecycle.inspect(run.run_id)
        self.lifecycle.ready(run.run_id)
        self.lifecycle.begin_validation(run.run_id)
        with self.assertRaisesRegex(LifecycleError, "evidence"):
            self.lifecycle.complete(run.run_id)
        self.lifecycle.add_validation_evidence(
            run.run_id, "tests", "All lifecycle tests passed", passed=True
        )
        completed = self.lifecycle.complete(run.run_id)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["terminal_reason"], "Validation evidence passed")
        with self.assertRaisesRegex(LifecycleError, "terminal"):
            self.lifecycle.inspect(run.run_id)

    def test_runtime_state_is_lazy_atomic_and_owner_only(self) -> None:
        state_root = self.root / "runtime" / "state"
        self.assertFalse(state_root.exists())
        self.lifecycle.create(RunContext("secure-run", "trusted-host"))
        run_files = list((state_root / "runs").glob("*.json"))
        self.assertEqual(len(run_files), 1)
        self.assertEqual(stat.S_IMODE(run_files[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(state_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((state_root / "runs").stat().st_mode), 0o700)

    def test_failed_validation_round_can_be_remediated_without_losing_history(self) -> None:
        self._ready("validation-run")
        self.lifecycle.begin_validation("validation-run")
        self.lifecycle.add_validation_evidence(
            "validation-run", "tests", "One check failed", passed=False
        )
        with self.assertRaisesRegex(LifecycleError, "evidence"):
            self.lifecycle.complete("validation-run")
        self.lifecycle.ready("validation-run", "Remediation required")
        self.lifecycle.begin_validation("validation-run")
        self.lifecycle.add_validation_evidence(
            "validation-run", "tests", "Remediation passed", passed=True
        )
        state = self.lifecycle.complete("validation-run")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["validation_evidence"]), 2)

    def test_illegal_transition_and_stale_writer_fail_closed(self) -> None:
        self.lifecycle.create(RunContext("run-1", "trusted-host"))
        with self.assertRaisesRegex(LifecycleError, "requires ready state"):
            self.lifecycle.begin_validation("run-1")

        first = self.lifecycle.store.load("run-1")
        stale = self.lifecycle.store.load("run-1")
        self.lifecycle.store.save(first, expected_revision=first["revision"])
        with self.assertRaisesRegex(StateStoreError, "revision conflict"):
            self.lifecycle.store.save(stale, expected_revision=stale["revision"])

    def test_schema_valid_but_forged_transition_history_is_rejected(self) -> None:
        self.lifecycle.create(RunContext("forged-run", "trusted-host"))
        forged = self.lifecycle.store.load("forged-run")
        forged["status"] = "ready"
        self.lifecycle.store.save(forged, expected_revision=forged["revision"])
        with self.assertRaisesRegex(LifecycleError, "history"):
            self.lifecycle.get("forged-run")

    def test_turn_limit_and_timeout_become_terminal_blocks(self) -> None:
        self._set_limits(max_model_turns=1, run_timeout_seconds=10)
        lifecycle = LifecycleEngine(self.root, clock=self.clock)
        lifecycle.create(RunContext("turn-run", "trusted-host"))
        lifecycle.inspect("turn-run")
        lifecycle.record_model_turn("turn-run")
        blocked = lifecycle.record_model_turn("turn-run")
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("Model-turn limit", blocked["terminal_reason"])

        lifecycle.create(RunContext("timeout-run", "trusted-host"))
        self.clock.value = "2026-08-07T12:00:11Z"
        with self.assertRaisesRegex(LifecycleError, "timeout"):
            lifecycle.inspect("timeout-run")
        self.assertEqual(lifecycle.get("timeout-run")["status"], "blocked")

    def test_reference_adapter_cannot_claim_unenforceable_tool_timeout(self) -> None:
        configuration = load_lifecycle_config(self.root)
        configuration["limits"]["tool_timeout_seconds"] = 5
        with self.assertRaisesRegex(LifecycleError, "cannot enforce"):
            validate_lifecycle_runtime_compatibility(configuration, "reference")
        validate_lifecycle_runtime_compatibility(configuration, "future-isolated-adapter")

    def test_tool_call_limit_blocks_before_a_second_execution(self) -> None:
        self._set_limits(max_tool_calls=1)
        lifecycle = LifecycleEngine(self.root, clock=self.clock)
        lifecycle.create(RunContext("tool-run", "trusted-host"))
        lifecycle.inspect("tool-run")
        lifecycle.ready("tool-run")
        first = self._pre("tool-run", "call-1")
        lifecycle.begin_tool_call(first, awaiting_approval=False)
        lifecycle.record_tool_result(self._post(first, status="failed", error="failed"))
        second = self._pre("tool-run", "call-2", {"different": True})
        blocked = lifecycle.begin_tool_call(second, awaiting_approval=False)
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("Tool-call limit", blocked["terminal_reason"])

    def test_interrupted_execution_and_partial_effects_require_reconciliation(self) -> None:
        self._ready("interrupted")
        event = self._pre("interrupted", "call-1")
        self.lifecycle.begin_tool_call(event, awaiting_approval=False)
        recovered = self.lifecycle.recover("interrupted")
        self.assertEqual(recovered["status"], "blocked")
        self.assertIn("ambiguous", recovered["terminal_reason"])
        self.assertEqual(self.lifecycle.get("interrupted")["status"], "blocked")

        self._ready("partial")
        partial_event = self._pre("partial", "call-2")
        self.lifecycle.begin_tool_call(partial_event, awaiting_approval=False)
        result = self._post(
            partial_event,
            status="partial",
            error="write completed before indexing failed",
            effects=(SideEffect("file-write", "notes.txt", "Created file", True),),
        )
        state = self.lifecycle.record_tool_result(result)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["side_effects"][0]["target"], "notes.txt")

    def test_enforced_timeout_is_persisted_and_never_retried_implicitly(self) -> None:
        self._ready("timed-out")
        event = self._pre("timed-out", "call-timeout")
        self.lifecycle.begin_tool_call(event, awaiting_approval=False)
        state = self.lifecycle.record_tool_timeout(
            "timed-out", "call-timeout", "Worker terminated at deadline"
        )
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["attempts"][0]["status"], "timed_out")
        self.assertIsNone(state["pending_call"])

    def test_retry_and_idempotency_prevent_duplicate_execution(self) -> None:
        self._ready("retry-run")
        first = self._pre("retry-run", "call-1", {"value": 1})
        self.lifecycle.begin_tool_call(first, awaiting_approval=False)
        failed = self._post(first, status="failed", error="temporary failure")
        self.assertEqual(self.lifecycle.record_tool_result(failed)["status"], "ready")

        second = self._pre("retry-run", "call-2", {"value": 1})
        retrying = self.lifecycle.begin_tool_call(second, awaiting_approval=False, retry=True)
        self.assertEqual(retrying["usage"]["retries"], 1)
        self.lifecycle.record_tool_result(self._post(second, status="succeeded"))

        duplicate = self._pre("retry-run", "call-3", {"value": 1})
        blocked = self.lifecycle.begin_tool_call(duplicate, awaiting_approval=False, retry=True)
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("idempotency", blocked["terminal_reason"])

    def test_retry_limit_is_enforced_before_an_extra_attempt(self) -> None:
        self._set_limits(max_retries=1)
        lifecycle = LifecycleEngine(self.root, clock=self.clock)
        lifecycle.create(RunContext("retry-limit", "trusted-host"))
        lifecycle.inspect("retry-limit")
        lifecycle.ready("retry-limit")
        first = self._pre("retry-limit", "call-1", {"value": 1})
        lifecycle.begin_tool_call(first, awaiting_approval=False)
        lifecycle.record_tool_result(self._post(first, status="failed", error="first"))
        second = self._pre("retry-limit", "call-2", {"value": 1})
        lifecycle.begin_tool_call(second, awaiting_approval=False, retry=True)
        lifecycle.record_tool_result(self._post(second, status="failed", error="second"))
        third = self._pre("retry-limit", "call-3", {"value": 1})
        blocked = lifecycle.begin_tool_call(third, awaiting_approval=False, retry=True)
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("Retry limit", blocked["terminal_reason"])

    def test_persistent_approval_resumes_exact_call_after_restart(self) -> None:
        runtime = self._runtime(approval="always", adapter_ids=Sequence("run-1", "call-1"))
        run = runtime.start_run()
        control = runtime.prepare_tool_call(run, "test.tool", {"value": 1})
        self.assertEqual(control.state.value, "awaiting_approval")
        approval = runtime.grant(control.event.tool_call_id, "human:reviewer")

        restarted = self._runtime(approval="always", adapter_ids=Sequence())
        restored_run = restarted.recover_run(run.run_id)
        resumed = restarted.resume(control.event.tool_call_id, approval.approval_id)
        result = restarted.execute(resumed)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(restarted.state(restored_run)["status"], "ready")

        restarted.begin_validation(restored_run)
        restarted.add_validation_evidence(
            restored_run, "unit-test", "Restart recovery passed", passed=True
        )
        self.assertEqual(restarted.complete(restored_run)["status"], "completed")

    def test_runtime_cancellation_closes_persisted_approval_call(self) -> None:
        runtime = self._runtime(approval="always", adapter_ids=Sequence("run-1", "call-1"))
        run = runtime.start_run()
        control = runtime.prepare_tool_call(run, "test.tool", {})
        cancelled = runtime.cancel(run, "Operator cancelled")
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(GuardedRuntimeError):
            runtime.resume(control.event.tool_call_id, "forged")

    def test_invalid_approval_resume_revokes_pending_authority(self) -> None:
        runtime = self._runtime(approval="always", adapter_ids=Sequence("run-1", "call-1"))
        run = runtime.start_run()
        control = runtime.prepare_tool_call(run, "test.tool", {})
        with self.assertRaises(GuardedRuntimeError):
            runtime.resume(control.event.tool_call_id, "forged")
        self.assertEqual(runtime.state(run)["status"], "blocked")
        with self.assertRaises(GuardedRuntimeError):
            runtime.grant(control.event.tool_call_id, "human:late")

    def test_cancellation_during_execution_blocks_and_revokes_control(self) -> None:
        runtime = self._runtime(approval="inherit", adapter_ids=Sequence("run-1", "call-1"))
        run = runtime.start_run()
        control = runtime.prepare_tool_call(run, "test.tool", {})
        blocked = runtime.cancel(run, "Operator interrupted execution")
        self.assertEqual(blocked["status"], "blocked")
        with self.assertRaises(LifecycleError):
            runtime.execute(control)

    def test_raw_sensitive_arguments_never_enter_persistent_state(self) -> None:
        runtime = self._runtime(approval="inherit", adapter_ids=Sequence("run-1", "call-1"))
        run = runtime.start_run()
        control = runtime.prepare_tool_call(
            run, "test.tool", {"credentials": {"token": "raw-secret"}}
        )
        self.assertEqual(control.state.value, "blocked")
        state = runtime.state(run)
        self.assertEqual(state["status"], "blocked")
        serialized = json.dumps(state)
        self.assertNotIn("raw-secret", serialized)

    def test_state_change_requires_exact_approved_plan(self) -> None:
        runtime = self._runtime(
            approval="inherit",
            adapter_ids=Sequence("run-1", "call-1"),
            action_class="reversible_local_change",
        )
        run = runtime.start_run()
        blocked = runtime.prepare_tool_call(run, "test.tool", {"value": 1})
        self.assertEqual(blocked.state.value, "blocked")
        self.assertIn("approved plan", blocked.reason)

    def test_approved_plan_binds_exact_arguments_and_call_count(self) -> None:
        runtime = self._runtime(
            approval="inherit",
            adapter_ids=Sequence("run-1", "call-1", "call-2"),
            action_class="reversible_local_change",
        )
        run = runtime.start_run()
        runtime.define_plan(
            run,
            "Write the exact requested value once",
            [{"tool_id": "test.tool", "arguments": {"value": 1}}],
        )
        runtime.approve_plan(run, "human:reviewer")
        control = runtime.prepare_tool_call(run, "test.tool", {"value": 1})
        self.assertEqual(runtime.execute(control).status, "succeeded")
        exhausted = runtime.prepare_tool_call(run, "test.tool", {"value": 1})
        self.assertEqual(exhausted.state.value, "blocked")
        self.assertIn("already been used", exhausted.reason)

    def test_new_plan_revision_invalidates_previous_approval(self) -> None:
        runtime = self._runtime(
            approval="inherit",
            adapter_ids=Sequence("run-1", "call-1"),
            action_class="reversible_local_change",
        )
        run = runtime.start_run()
        runtime.define_plan(
            run,
            "First scope",
            [{"tool_id": "test.tool", "arguments": {"value": 1}}],
        )
        runtime.approve_plan(run, "human:reviewer")
        revised = runtime.define_plan(
            run,
            "Expanded scope",
            [{"tool_id": "test.tool", "arguments": {"value": 2}}],
        )
        self.assertEqual(revised["plans"][0]["status"], "superseded")
        self.assertEqual(revised["plans"][1]["status"], "draft")
        blocked = runtime.prepare_tool_call(run, "test.tool", {"value": 2})
        self.assertEqual(blocked.state.value, "blocked")

    def _ready(self, run_id: str) -> None:
        self.lifecycle.create(RunContext(run_id, "trusted-host"))
        self.lifecycle.inspect(run_id)
        self.lifecycle.ready(run_id)

    def _pre(
        self, run_id: str, call_id: str, arguments: dict[str, object] | None = None
    ) -> PreToolEvent:
        return PreToolEvent(
            schema_version="1.0",
            event_type="pre_tool",
            run_id=run_id,
            tool_call_id=call_id,
            tool_id="test.tool",
            arguments=arguments or {},
            requested_at=self.clock(),
            actor="trusted-host",
        )

    def _post(
        self,
        pre: PreToolEvent,
        *,
        status: str,
        error: str | None = None,
        effects: tuple[SideEffect, ...] = (),
    ) -> PostToolEvent:
        return PostToolEvent(
            schema_version="1.0",
            event_type="post_tool",
            run_id=pre.run_id,
            tool_call_id=pre.tool_call_id,
            tool_id=pre.tool_id,
            arguments=pre.arguments,
            requested_at=pre.requested_at,
            actor=pre.actor,
            started_at=self.clock(),
            completed_at=self.clock(),
            status=status,
            output_trust="trusted",
            output=None,
            error=error,
            side_effects=effects,
        )

    def _runtime(
        self,
        *,
        approval: str,
        adapter_ids: Sequence,
        action_class: str = "read_only",
    ) -> LifecycleRuntime:
        state_directory = self.lifecycle.store.directory
        approvals = ApprovalStore(
            self.root,
            storage_directory=state_directory,
            clock=self.clock,
            id_factory=Sequence("approval-1"),
        )
        plan_approvals = PlanApprovalStore(
            self.root,
            storage_directory=state_directory,
            clock=self.clock,
        )
        policies = {"test.tool": tool(approval=approval, action_class=action_class)}
        guardrails = TrustedGuardrails(
            self.root,
            policies,  # type: ignore[arg-type]
            policy(),  # type: ignore[arg-type]
            approvals,
        )
        adapter = ReferenceRuntimeAdapter(
            "trusted-host",
            {"test.tool": lambda arguments: arguments},
            id_factory=adapter_ids,
            clock=self.clock,
            argument_normalizer=guardrails.normalize_arguments,
        )
        guarded = GuardedRuntime(RuntimeBoundary(adapter, self.root), guardrails, approvals)
        return LifecycleRuntime(
            guarded,
            LifecycleEngine(self.root, clock=self.clock),
            plan_approvals,
        )

    def _copy_contracts(self) -> None:
        schemas = self.root / "config" / "schemas"
        schemas.mkdir(parents=True)
        for filename in (
            "approval.schema.json",
            "lifecycle.schema.json",
            "post-tool-event.schema.json",
            "policy.schema.json",
            "plan-approval.schema.json",
            "pre-tool-event.schema.json",
            "run-state.schema.json",
        ):
            shutil.copy2(self.source / "config" / "schemas" / filename, schemas / filename)
        shutil.copy2(
            self.source / "config" / "lifecycle.yaml",
            self.root / "config" / "lifecycle.yaml",
        )
        shutil.copy2(
            self.source / "config" / "policies.yaml",
            self.root / "config" / "policies.yaml",
        )

    def _set_limits(self, **changes: int) -> None:
        path = self.root / "config" / "lifecycle.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["limits"].update(changes)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
