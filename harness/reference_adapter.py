"""Deterministic executable adapter used to prove the runtime boundary."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from harness.runtime import PostToolEvent, PreToolEvent, RunContext, SideEffect

ToolHandler = Callable[[dict[str, Any]], Any]
ArgumentNormalizer = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolOutput:
    output: Any
    side_effects: tuple[SideEffect, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", _json_copy(self.output))
        object.__setattr__(self, "side_effects", _side_effects(self.side_effects))


class PartialToolFailure(RuntimeError):
    """Report a failed call that already produced concrete side effects."""

    def __init__(
        self,
        message: str,
        side_effects: tuple[SideEffect, ...],
        output: Any = None,
    ) -> None:
        if not side_effects:
            raise ValueError("PartialToolFailure requires at least one side effect")
        super().__init__(_required(message, "partial failure message"))
        self.side_effects = _side_effects(side_effects)
        self.output = _json_copy(output)


class ReferenceRuntimeAdapter:
    """In-process adapter with explicit registered handlers and adapter-owned metadata."""

    name = "reference"
    supports_hard_timeouts = False

    def __init__(
        self,
        actor: str,
        handlers: Mapping[str, ToolHandler],
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
        argument_normalizer: ArgumentNormalizer | None = None,
    ) -> None:
        self._actor = _required(actor, "actor")
        self._handlers = dict(handlers)
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock or _utc_now
        self._argument_normalizer = argument_normalizer
        self._runs: set[str] = set()
        self._calls: set[str] = set()

    def start_run(self) -> RunContext:
        run_id = _required(self._id_factory(), "generated run ID")
        if run_id in self._runs:
            raise ValueError(f"Generated duplicate run ID: {run_id}")
        self._runs.add(run_id)
        return RunContext(run_id=run_id, actor=self._actor)

    def restore_run(self, run: RunContext) -> None:
        """Re-register a persisted run without minting trusted identity fields."""
        if run.actor != self._actor:
            raise ValueError("Persisted run actor does not match this adapter")
        self._runs.add(_required(run.run_id, "run ID"))

    def restore_call(self, event: PreToolEvent) -> None:
        """Re-register a persisted call for approval resumption only."""
        self.restore_run(RunContext(event.run_id, event.actor))
        if event.tool_id not in self._handlers:
            raise ValueError(f"Tool is not registered with the adapter: {event.tool_id}")
        self._calls.add(_required(event.tool_call_id, "tool call ID"))

    def create_pre_tool_event(
        self, run: RunContext, tool_id: str, arguments: dict[str, Any]
    ) -> PreToolEvent:
        if run.run_id not in self._runs or run.actor != self._actor:
            raise ValueError("Run context was not created by this adapter")
        normalized_tool_id = _required(tool_id, "tool ID")
        if normalized_tool_id not in self._handlers:
            raise ValueError(f"Tool is not registered with the adapter: {normalized_tool_id}")
        normalized_arguments = _json_copy(arguments)
        if not isinstance(normalized_arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        if self._argument_normalizer is not None:
            normalized_arguments = self._argument_normalizer(
                normalized_tool_id, normalized_arguments
            )
            normalized_arguments = _json_copy(normalized_arguments)
            if not isinstance(normalized_arguments, dict):
                raise ValueError("Normalized tool arguments must be a JSON object")
        tool_call_id = _required(self._id_factory(), "generated tool call ID")
        if tool_call_id in self._calls:
            raise ValueError(f"Generated duplicate tool call ID: {tool_call_id}")
        self._calls.add(tool_call_id)
        return PreToolEvent(
            schema_version="1.0",
            event_type="pre_tool",
            run_id=run.run_id,
            tool_call_id=tool_call_id,
            tool_id=normalized_tool_id,
            arguments=normalized_arguments,
            requested_at=self._clock(),
            actor=self._actor,
        )

    def execute(self, event: PreToolEvent, timeout_seconds: int | None = None) -> PostToolEvent:
        if timeout_seconds is not None:
            raise ValueError("Reference adapter cannot enforce hard tool timeouts")
        started_at = self._clock()
        handler = self._handlers[event.tool_id]
        try:
            execution_arguments = _json_copy(event.arguments)
            if self._argument_normalizer is not None:
                current_arguments = self._argument_normalizer(event.tool_id, execution_arguments)
                if current_arguments != event.arguments:
                    raise ValueError("Normalized tool arguments changed before execution")
                execution_arguments = current_arguments
            value = handler(execution_arguments)
            result = value if isinstance(value, ToolOutput) else ToolOutput(output=value)
            status = "succeeded"
            output = _json_copy(result.output)
            error = None
            side_effects = _side_effects(result.side_effects)
        except PartialToolFailure as exc:
            status = "partial"
            output = _json_copy(exc.output)
            error = _required(str(exc), "partial failure message")
            side_effects = _side_effects(exc.side_effects)
        except Exception as exc:  # noqa: BLE001 - adapters normalize tool failures
            status = "failed"
            output = None
            error = str(exc) or exc.__class__.__name__
            side_effects = ()
        return PostToolEvent(
            schema_version="1.0",
            event_type="post_tool",
            run_id=event.run_id,
            tool_call_id=event.tool_call_id,
            tool_id=event.tool_id,
            arguments=_json_copy(event.arguments),
            requested_at=event.requested_at,
            actor=event.actor,
            started_at=started_at,
            completed_at=self._clock(),
            status=status,
            output_trust="unclassified",
            output=output,
            error=error,
            side_effects=side_effects,
        )


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("Runtime values must be JSON serializable") from exc


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _side_effects(values: tuple[SideEffect, ...]) -> tuple[SideEffect, ...]:
    normalized: list[SideEffect] = []
    for value in values:
        if not isinstance(value, SideEffect):
            raise ValueError("Side effects must use the SideEffect contract")
        normalized.append(
            SideEffect(
                kind=_required(value.kind, "side-effect kind"),
                target=_required(value.target, "side-effect target"),
                description=_required(value.description, "side-effect description"),
                reversible=value.reversible,
            )
        )
    return tuple(normalized)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
