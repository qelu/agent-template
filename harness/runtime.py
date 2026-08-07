"""Provider-neutral runtime boundary and trusted tool-call event contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


class RuntimeBoundaryError(RuntimeError):
    """Raised when a tool call violates the runtime boundary contract."""


class ControlState(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    actor: str


@dataclass(frozen=True)
class SideEffect:
    kind: str
    target: str
    description: str
    reversible: bool | None


@dataclass(frozen=True)
class PreToolEvent:
    schema_version: str
    event_type: str
    run_id: str
    tool_call_id: str
    tool_id: str
    arguments: dict[str, Any]
    requested_at: str
    actor: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), allow_nan=False))


@dataclass(frozen=True)
class PostToolEvent:
    schema_version: str
    event_type: str
    run_id: str
    tool_call_id: str
    tool_id: str
    arguments: dict[str, Any]
    requested_at: str
    actor: str
    started_at: str
    completed_at: str
    status: str
    output_trust: str
    output: Any
    error: str | None
    side_effects: tuple[SideEffect, ...]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), allow_nan=False))


@dataclass(frozen=True)
class ToolCallControl:
    event: PreToolEvent
    state: ControlState
    reason: str | None = None


class RuntimeAdapter(Protocol):
    """Adapter-owned source of trusted run, call, actor, and timing fields."""

    name: str

    def start_run(self) -> RunContext: ...

    def create_pre_tool_event(
        self, run: RunContext, tool_id: str, arguments: dict[str, Any]
    ) -> PreToolEvent: ...

    def execute(self, event: PreToolEvent) -> PostToolEvent: ...


class RuntimeBoundary:
    """Control tool execution without trusting model-authored event metadata."""

    def __init__(self, adapter: RuntimeAdapter | None, schema_root: Path | None = None) -> None:
        self._adapter = adapter
        self._schema_root = schema_root or Path(__file__).resolve().parent.parent
        self._paused: dict[str, PreToolEvent] = {}
        self._closed: set[str] = set()
        self._prepared: dict[str, str] = {}

    @property
    def hooks_enabled(self) -> bool:
        return self._adapter is not None

    def start_run(self) -> RunContext:
        return self._require_adapter().start_run()

    def prepare_tool_call(
        self, run: RunContext, tool_id: str, arguments: dict[str, Any]
    ) -> ToolCallControl:
        event = self._require_adapter().create_pre_tool_event(run, tool_id, arguments)
        validate_runtime_event(self._schema_root, event)
        call_id = event.tool_call_id
        if call_id in self._prepared or call_id in self._closed:
            raise RuntimeBoundaryError(f"Adapter produced duplicate tool call ID: {call_id}")
        self._prepared[call_id] = _snapshot(event)
        return ToolCallControl(event=event, state=ControlState.READY)

    def block(self, control: ToolCallControl, reason: str) -> ToolCallControl:
        self._require_ready(control)
        normalized_reason = _required(reason, "reason")
        self._closed.add(control.event.tool_call_id)
        return ToolCallControl(
            event=control.event, state=ControlState.BLOCKED, reason=normalized_reason
        )

    def pause_for_approval(
        self, control: ToolCallControl, reason: str
    ) -> ToolCallControl:
        self._require_ready(control)
        normalized_reason = _required(reason, "reason")
        call_id = control.event.tool_call_id
        if call_id in self._paused or call_id in self._closed:
            raise RuntimeBoundaryError(f"Tool call is already paused or consumed: {call_id}")
        self._paused[call_id] = control.event
        return ToolCallControl(
            event=control.event,
            state=ControlState.AWAITING_APPROVAL,
            reason=normalized_reason,
        )

    def resume(self, tool_call_id: str) -> ToolCallControl:
        try:
            event = self._paused.pop(tool_call_id)
        except KeyError as exc:
            raise RuntimeBoundaryError(f"Tool call is not awaiting approval: {tool_call_id}") from exc
        return ToolCallControl(event=event, state=ControlState.READY)

    def execute(self, control: ToolCallControl) -> PostToolEvent:
        self._require_ready(control)
        call_id = control.event.tool_call_id
        if call_id in self._paused:
            raise RuntimeBoundaryError(f"Tool call is awaiting approval: {call_id}")
        if call_id in self._closed:
            raise RuntimeBoundaryError(f"Tool call is already closed: {call_id}")
        self._closed.add(call_id)
        result = self._require_adapter().execute(control.event)
        if not isinstance(result, PostToolEvent):
            raise RuntimeBoundaryError("Runtime adapter returned an invalid post-tool event")
        validate_runtime_event(self._schema_root, result)
        _validate_correlation(control.event, result)
        return result

    def validate_event(self, event: PreToolEvent | PostToolEvent) -> None:
        """Validate a derived event against this boundary's configured schemas."""
        validate_runtime_event(self._schema_root, event)

    def _require_adapter(self) -> RuntimeAdapter:
        if self._adapter is None:
            raise RuntimeBoundaryError("Runtime hooks require a configured adapter")
        return self._adapter

    def _require_ready(self, control: ToolCallControl) -> None:
        if control.state != ControlState.READY:
            raise RuntimeBoundaryError(
                f"Tool call is not executable from state: {control.state.value}"
            )
        call_id = control.event.tool_call_id
        expected = self._prepared.get(call_id)
        if expected is None:
            raise RuntimeBoundaryError(f"Tool call was not prepared by this boundary: {call_id}")
        if expected != _snapshot(control.event):
            raise RuntimeBoundaryError(f"Trusted tool-call fields changed after preparation: {call_id}")


def validate_runtime_schemas(root: Path) -> None:
    """Validate both checked-in runtime event schemas against Draft 2020-12."""
    for name in ("pre-tool-event", "post-tool-event"):
        schema_path = root / "config" / "schemas" / f"{name}.schema.json"
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except (OSError, ValueError, TypeError, SchemaError) as exc:
            raise RuntimeBoundaryError(f"Invalid runtime schema {schema_path}: {exc}") from exc


def validate_runtime_event(root: Path, event: PreToolEvent | PostToolEvent) -> None:
    """Validate a normalized event against its checked-in JSON Schema."""
    if isinstance(event, PreToolEvent):
        name = "pre-tool-event"
    elif isinstance(event, PostToolEvent):
        name = "post-tool-event"
    else:
        raise RuntimeBoundaryError("Unsupported runtime event type")
    schema_path = root / "config" / "schemas" / f"{name}.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        payload = event.to_dict()
    except (TypeError, ValueError) as exc:
        raise RuntimeBoundaryError(f"Invalid {name} event: values must be JSON serializable") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            payload
        ),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise RuntimeBoundaryError(f"Invalid {name} event: {details}")
    timestamp_fields = ["requested_at"]
    if name == "post-tool-event":
        timestamp_fields.extend(("started_at", "completed_at"))
    timestamps = {
        field: _validate_timestamp(payload[field], name, field)
        for field in timestamp_fields
    }
    if name == "post-tool-event" and not (
        timestamps["requested_at"]
        <= timestamps["started_at"]
        <= timestamps["completed_at"]
    ):
        raise RuntimeBoundaryError(
            "Invalid post-tool-event event: timestamps must be chronological"
        )


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeBoundaryError(f"{field} must not be empty")
    return normalized


def _snapshot(event: PreToolEvent) -> str:
    return json.dumps(
        event.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _validate_correlation(pre: PreToolEvent, post: PostToolEvent) -> None:
    pre_fields = {
        "run_id": pre.run_id,
        "tool_call_id": pre.tool_call_id,
        "tool_id": pre.tool_id,
        "arguments": pre.arguments,
        "requested_at": pre.requested_at,
        "actor": pre.actor,
    }
    post_fields = {
        "run_id": post.run_id,
        "tool_call_id": post.tool_call_id,
        "tool_id": post.tool_id,
        "arguments": post.arguments,
        "requested_at": post.requested_at,
        "actor": post.actor,
    }
    if _json_snapshot(pre_fields) != _json_snapshot(post_fields):
        raise RuntimeBoundaryError("Post-tool event does not match its trusted pre-tool event")


def _json_snapshot(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate_timestamp(value: str, event_name: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeBoundaryError(
            f"Invalid {event_name} event: {field} must be an RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise RuntimeBoundaryError(
            f"Invalid {event_name} event: {field} must include a UTC offset"
        )
    return parsed
