"""Reusable behavioral contract tests for runtime adapter implementations."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from harness.runtime import (
    ControlState,
    RuntimeAdapter,
    RuntimeBoundary,
    RuntimeBoundaryError,
    SideEffect,
    ToolCallControl,
    ToolTimeoutError,
    validate_runtime_event,
)


@dataclass(frozen=True)
class AdapterConformanceFixture:
    """One isolated adapter configured with deterministic conformance scenarios."""

    adapter: RuntimeAdapter
    schema_root: Path
    actor: str
    success_tool_id: str
    success_arguments: dict[str, Any]
    success_output: Any
    failure_tool_id: str
    failure_error: str
    partial_tool_id: str
    partial_output: Any
    partial_effects: tuple[SideEffect, ...]
    timeout_tool_id: str


class RuntimeAdapterConformanceMixin:
    """Mixin supplying the contract every runtime adapter must satisfy.

    Concrete test cases inherit from this mixin and ``unittest.TestCase``, then
    implement ``make_adapter_fixture`` with a fresh adapter for each invocation.
    Keeping the factory outside the suite allows provider adapters to use fake SDK
    clients while exercising the same trusted boundary behavior.
    """

    def make_adapter_fixture(self) -> AdapterConformanceFixture:
        raise NotImplementedError

    def test_conformance_adapter_owns_identity_and_argument_snapshot(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)
        supplied = copy.deepcopy(fixture.success_arguments)

        run = boundary.start_run()
        control = boundary.prepare_tool_call(run, fixture.success_tool_id, supplied)
        supplied["mutated_after_preparation"] = True

        self.assertEqual(run.actor, fixture.actor)  # type: ignore[attr-defined]
        self.assertTrue(run.run_id)  # type: ignore[attr-defined]
        self.assertTrue(control.event.tool_call_id)  # type: ignore[attr-defined]
        self.assertNotIn(  # type: ignore[attr-defined]
            "mutated_after_preparation", control.event.arguments
        )
        validate_runtime_event(fixture.schema_root, control.event)

    def test_conformance_run_and_call_ids_are_unique(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)

        first_run = boundary.start_run()
        second_run = boundary.start_run()
        first_call = boundary.prepare_tool_call(
            first_run, fixture.success_tool_id, fixture.success_arguments
        )
        second_call = boundary.prepare_tool_call(
            first_run, fixture.success_tool_id, fixture.success_arguments
        )

        self.assertNotEqual(first_run.run_id, second_run.run_id)  # type: ignore[attr-defined]
        self.assertNotEqual(  # type: ignore[attr-defined]
            first_call.event.tool_call_id, second_call.event.tool_call_id
        )

    def test_conformance_success_is_correlated_and_single_dispatch(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)
        run = boundary.start_run()
        control = boundary.prepare_tool_call(
            run, fixture.success_tool_id, fixture.success_arguments
        )

        result = boundary.execute(control)

        self.assertEqual(result.status, "succeeded")  # type: ignore[attr-defined]
        self.assertEqual(result.output, fixture.success_output)  # type: ignore[attr-defined]
        self.assertEqual(result.run_id, control.event.run_id)  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            result.tool_call_id, control.event.tool_call_id
        )
        self.assertEqual(result.tool_id, control.event.tool_id)  # type: ignore[attr-defined]
        self.assertEqual(result.arguments, control.event.arguments)  # type: ignore[attr-defined]
        validate_runtime_event(fixture.schema_root, result)
        with self.assertRaisesRegex(  # type: ignore[attr-defined]
            RuntimeBoundaryError, "already closed"
        ):
            boundary.execute(control)

    def test_conformance_failure_is_normalized(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)
        control = boundary.prepare_tool_call(
            boundary.start_run(), fixture.failure_tool_id, {}
        )

        result = boundary.execute(control)

        self.assertEqual(result.status, "failed")  # type: ignore[attr-defined]
        self.assertEqual(result.error, fixture.failure_error)  # type: ignore[attr-defined]
        self.assertEqual(result.side_effects, ())  # type: ignore[attr-defined]
        validate_runtime_event(fixture.schema_root, result)

    def test_conformance_partial_result_reports_exact_side_effects(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)
        control = boundary.prepare_tool_call(
            boundary.start_run(), fixture.partial_tool_id, {}
        )

        result = boundary.execute(control)

        self.assertEqual(result.status, "partial")  # type: ignore[attr-defined]
        self.assertEqual(result.output, fixture.partial_output)  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            result.side_effects, fixture.partial_effects
        )
        self.assertTrue(result.error)  # type: ignore[attr-defined]
        validate_runtime_event(fixture.schema_root, result)

    def test_conformance_pause_resume_preserves_exact_event(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)
        control = boundary.prepare_tool_call(
            boundary.start_run(), fixture.success_tool_id, fixture.success_arguments
        )

        paused = boundary.pause_for_approval(control, "Exact approval required")

        self.assertEqual(  # type: ignore[attr-defined]
            paused.state, ControlState.AWAITING_APPROVAL
        )
        with self.assertRaises(RuntimeBoundaryError):  # type: ignore[attr-defined]
            boundary.execute(control)
        resumed = boundary.resume(control.event.tool_call_id)
        self.assertEqual(resumed.event, control.event)  # type: ignore[attr-defined]
        self.assertEqual(  # type: ignore[attr-defined]
            boundary.execute(resumed).status, "succeeded"
        )
        with self.assertRaises(RuntimeBoundaryError):  # type: ignore[attr-defined]
            boundary.resume(control.event.tool_call_id)

    def test_conformance_tampered_trusted_fields_are_rejected(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)
        control = boundary.prepare_tool_call(
            boundary.start_run(), fixture.success_tool_id, fixture.success_arguments
        )
        forged = ToolCallControl(
            event=replace(control.event, actor="model:forged"),
            state=ControlState.READY,
        )

        with self.assertRaisesRegex(  # type: ignore[attr-defined]
            RuntimeBoundaryError, "fields changed"
        ):
            boundary.execute(forged)

    def test_conformance_rejects_non_json_arguments(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)

        with self.assertRaises(  # type: ignore[attr-defined]
            (RuntimeBoundaryError, TypeError, ValueError)
        ):
            boundary.prepare_tool_call(
                boundary.start_run(), fixture.success_tool_id, {"value": float("nan")}
            )

    def test_conformance_timeout_capability_is_honest(self) -> None:
        fixture = self.make_adapter_fixture()
        boundary = RuntimeBoundary(fixture.adapter, schema_root=fixture.schema_root)
        control = boundary.prepare_tool_call(
            boundary.start_run(), fixture.timeout_tool_id, {}
        )

        if fixture.adapter.supports_hard_timeouts:
            with self.assertRaises(ToolTimeoutError):  # type: ignore[attr-defined]
                boundary.execute(control, timeout_seconds=1)
        else:
            with self.assertRaisesRegex(  # type: ignore[attr-defined]
                RuntimeBoundaryError, "cannot enforce hard tool timeouts"
            ):
                boundary.execute(control, timeout_seconds=1)
