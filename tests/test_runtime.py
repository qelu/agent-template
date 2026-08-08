import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from harness.reference_adapter import (
    PartialToolFailure,
    ReferenceRuntimeAdapter,
    ToolOutput,
)
from harness.deployment import load_deployment
from harness.runtime import (
    ControlState,
    RunContext,
    RuntimeBoundary,
    RuntimeBoundaryError,
    SideEffect,
    ToolCallControl,
    validate_runtime_event,
    validate_runtime_schemas,
)
from harness.runtime_factory import configured_runtime


class Sequence:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def __call__(self) -> str:
        return next(self._values)


class RuntimeBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent.parent

    def test_adapter_owns_normalized_event_fields(self) -> None:
        arguments = {"path": "notes.txt", "nested": {"count": 1}}
        adapter = self._adapter({"inspect": lambda payload: payload})
        boundary = RuntimeBoundary(adapter)

        run = boundary.start_run()
        control = boundary.prepare_tool_call(run, "inspect", arguments)
        arguments["nested"]["count"] = 99

        self.assertTrue(boundary.hooks_enabled)
        self.assertEqual(run, RunContext(run_id="run-1", actor="test-runtime"))
        self.assertEqual(control.event.tool_call_id, "call-1")
        self.assertEqual(control.event.arguments["nested"]["count"], 1)
        validate_runtime_event(self.root, control.event)

        result = boundary.execute(control)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.output_trust, "unclassified")
        self.assertEqual(result.output["nested"]["count"], 1)
        self.assertEqual(result.run_id, control.event.run_id)
        self.assertEqual(result.tool_call_id, control.event.tool_call_id)
        validate_runtime_event(self.root, result)

    def test_checked_in_runtime_schemas_are_valid(self) -> None:
        validate_runtime_schemas(self.root)

    def test_invalid_runtime_schema_has_a_boundary_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            schemas = root / "config" / "schemas"
            schemas.mkdir(parents=True)
            for name in ("pre-tool-event", "post-tool-event"):
                payload = json.loads(
                    (self.root / "config" / "schemas" / f"{name}.schema.json").read_text(
                        encoding="utf-8"
                    )
                )
                if name == "pre-tool-event":
                    payload["type"] = "not-a-json-schema-type"
                (schemas / f"{name}.schema.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeBoundaryError, "Invalid runtime schema"):
                validate_runtime_schemas(root)

    def test_factory_builds_the_deployment_selected_runtime(self) -> None:
        profile = load_deployment(self.root)
        boundary = configured_runtime(
            self.root,
            actor="configured-runtime",
            handlers={"inspect": lambda payload: payload},
        )
        expected = profile["runtime"]["adapter"] == "reference"
        self.assertEqual(boundary.hooks_enabled, expected)
        if expected:
            run = boundary.start_run()
            control = boundary.prepare_tool_call(run, "inspect", {"value": 1})
            self.assertEqual(control.state, ControlState.BLOCKED)
            self.assertIn("not in the trusted registry", control.reason)

    def test_runtime_hooks_require_an_adapter(self) -> None:
        boundary = RuntimeBoundary(None)
        self.assertFalse(boundary.hooks_enabled)
        with self.assertRaisesRegex(RuntimeBoundaryError, "require a configured adapter"):
            boundary.start_run()

    def test_rejects_unknown_tools_and_foreign_runs(self) -> None:
        adapter = self._adapter({"inspect": lambda payload: payload})
        boundary = RuntimeBoundary(adapter)
        run = boundary.start_run()
        with self.assertRaisesRegex(ValueError, "not registered"):
            boundary.prepare_tool_call(run, "missing", {})
        with self.assertRaisesRegex(ValueError, "not created by this adapter"):
            boundary.prepare_tool_call(RunContext("foreign", "test-runtime"), "inspect", {})

    def test_blocks_execution_permanently(self) -> None:
        boundary, control = self._prepared(lambda payload: payload)
        blocked = boundary.block(control, "Policy denied this call")
        self.assertEqual(blocked.state, ControlState.BLOCKED)
        with self.assertRaises(RuntimeBoundaryError):
            boundary.execute(blocked)
        with self.assertRaisesRegex(RuntimeBoundaryError, "already closed"):
            boundary.execute(control)

    def test_pauses_and_resumes_without_recreating_the_event(self) -> None:
        boundary, control = self._prepared(lambda payload: "done")
        paused = boundary.pause_for_approval(control, "Approval required")
        self.assertEqual(paused.state, ControlState.AWAITING_APPROVAL)
        with self.assertRaisesRegex(RuntimeBoundaryError, "not executable"):
            boundary.execute(paused)
        with self.assertRaisesRegex(RuntimeBoundaryError, "awaiting approval"):
            boundary.execute(control)

        resumed = boundary.resume(control.event.tool_call_id)
        self.assertEqual(resumed.event, control.event)
        self.assertEqual(boundary.execute(resumed).status, "succeeded")
        with self.assertRaisesRegex(RuntimeBoundaryError, "not awaiting approval"):
            boundary.resume(control.event.tool_call_id)

    def test_rejects_forged_or_changed_events(self) -> None:
        boundary, control = self._prepared(lambda payload: payload)
        forged_event = replace(control.event, tool_call_id="forged-call")
        forged = ToolCallControl(forged_event, ControlState.READY)
        with self.assertRaisesRegex(RuntimeBoundaryError, "not prepared"):
            boundary.execute(forged)

        control.event.arguments["changed"] = True
        with self.assertRaisesRegex(RuntimeBoundaryError, "fields changed"):
            boundary.execute(control)

    def test_rejects_invalid_or_mismatched_adapter_events(self) -> None:
        invalid_clock = ReferenceRuntimeAdapter(
            "test-runtime",
            {"inspect": lambda payload: payload},
            id_factory=Sequence("run-1", "call-1"),
            clock=Sequence("not-a-timestamp"),
        )
        boundary = RuntimeBoundary(invalid_clock, schema_root=self.root)
        run = boundary.start_run()
        with self.assertRaisesRegex(RuntimeBoundaryError, "Invalid pre-tool-event"):
            boundary.prepare_tool_call(run, "inspect", {})

        class MismatchedAdapter(ReferenceRuntimeAdapter):
            def execute(self, event):  # type: ignore[no-untyped-def]
                return replace(super().execute(event), run_id="different-run")

        mismatch = MismatchedAdapter(
            "test-runtime",
            {"inspect": lambda payload: payload},
            id_factory=Sequence("run-1", "call-1"),
            clock=Sequence(
                "2026-08-07T10:00:00Z",
                "2026-08-07T10:00:01Z",
                "2026-08-07T10:00:02Z",
            ),
        )
        boundary = RuntimeBoundary(mismatch, schema_root=self.root)
        control = boundary.prepare_tool_call(boundary.start_run(), "inspect", {})
        with self.assertRaisesRegex(RuntimeBoundaryError, "does not match"):
            boundary.execute(control)

    def test_failed_tool_is_normalized(self) -> None:
        def fail(_payload: dict[str, object]) -> None:
            raise RuntimeError("tool failed")

        boundary, control = self._prepared(fail)
        result = boundary.execute(control)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "tool failed")
        self.assertEqual(result.side_effects, ())
        validate_runtime_event(self.root, result)

    def test_partial_failure_reports_completed_side_effects(self) -> None:
        effect = SideEffect(
            kind="file-write",
            target="notes.txt",
            description="Created the destination file before indexing failed.",
            reversible=True,
        )

        def partial(_payload: dict[str, object]) -> None:
            raise PartialToolFailure("indexing failed", (effect,), {"bytes_written": 12})

        boundary, control = self._prepared(partial)
        result = boundary.execute(control)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.error, "indexing failed")
        self.assertEqual(result.side_effects, (effect,))
        validate_runtime_event(self.root, result)

    def test_success_can_report_side_effects(self) -> None:
        effect = SideEffect("file-write", "notes.txt", "Updated notes.", True)
        boundary, control = self._prepared(lambda payload: ToolOutput({"saved": True}, (effect,)))
        result = boundary.execute(control)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.side_effects, (effect,))
        validate_runtime_event(self.root, result)

    def test_reference_adapter_rejects_unenforceable_hard_timeout(self) -> None:
        executed: list[bool] = []

        def handler(_payload: dict[str, object]) -> str:
            executed.append(True)
            return "done"

        boundary, control = self._prepared(handler)
        with self.assertRaisesRegex(RuntimeBoundaryError, "cannot enforce hard tool timeouts"):
            boundary.execute(control, timeout_seconds=1)
        self.assertEqual(executed, [])

    def _adapter(self, handlers: dict[str, object]) -> ReferenceRuntimeAdapter:
        return ReferenceRuntimeAdapter(
            "test-runtime",
            handlers,  # type: ignore[arg-type]
            id_factory=Sequence("run-1", "call-1"),
            clock=Sequence(
                "2026-08-07T10:00:00Z",
                "2026-08-07T10:00:01Z",
                "2026-08-07T10:00:02Z",
            ),
        )

    def _prepared(self, handler: object) -> tuple[RuntimeBoundary, ToolCallControl]:
        adapter = self._adapter({"test-tool": handler})
        boundary = RuntimeBoundary(adapter)
        run = boundary.start_run()
        return boundary, boundary.prepare_tool_call(run, "test-tool", {"value": 1})


if __name__ == "__main__":
    unittest.main()
