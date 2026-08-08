"""Persistent executable lifecycle with bounded, fail-closed transitions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from harness.configuration import load_yaml
from harness.policy import load_policy
from harness.plans import PlanApprovalRecord, arguments_digest, plan_digest
from harness.runtime import PostToolEvent, PreToolEvent, RunContext
from harness.state_store import RunStateStore, StateStoreError

TERMINAL = frozenset({"completed", "failed", "cancelled", "blocked"})
LEGAL_TRANSITIONS = {
    "created": {"inspecting", "cancelled", "blocked", "failed"},
    "inspecting": {"ready", "cancelled", "blocked", "failed"},
    "ready": {
        "inspecting",
        "awaiting_approval",
        "executing",
        "validating",
        "cancelled",
        "blocked",
        "failed",
    },
    "awaiting_approval": {"executing", "cancelled", "blocked", "failed"},
    "executing": {"inspecting", "ready", "validating", "cancelled", "blocked", "failed"},
    "validating": {"ready", "completed", "cancelled", "blocked", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
    "blocked": set(),
}


class LifecycleError(RuntimeError):
    """Raised when lifecycle state, limits, or evidence are invalid."""


def load_lifecycle_config(root: Path) -> dict[str, Any]:
    """Load the versioned lifecycle configuration and keep state inside the repo."""
    try:
        payload = load_yaml(root / "config" / "lifecycle.yaml")
        schema = json.loads(
            (root / "config" / "schemas" / "lifecycle.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, TypeError, SchemaError) as exc:
        raise LifecycleError(f"Invalid lifecycle configuration schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise LifecycleError(f"Invalid lifecycle configuration: {details}")
    state_directory = (root / payload["state_directory"]).resolve()
    resolved_root = root.resolve()
    if state_directory != resolved_root and resolved_root not in state_directory.parents:
        raise LifecycleError("Lifecycle state directory must remain inside the repository")
    if Path(payload["state_directory"]).parts[0] != "runtime":
        raise LifecycleError("Lifecycle state directory must be under ignored runtime/")
    return payload


def validate_lifecycle_runtime_compatibility(lifecycle: dict[str, Any], adapter_name: str) -> None:
    """Reject timeout claims that the implemented reference adapter cannot enforce."""
    if adapter_name == "reference" and lifecycle["limits"]["tool_timeout_seconds"] is not None:
        raise LifecycleError(
            "Reference adapter cannot enforce hard tool timeouts; set tool_timeout_seconds to null"
        )


class LifecycleEngine:
    """Own legal transitions, budgets, recovery, attempts, and completion evidence."""

    def __init__(
        self,
        root: Path,
        *,
        store: RunStateStore | None = None,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._root = root.resolve()
        self.config = load_lifecycle_config(root)
        policy = load_policy(root)
        self._sensitive_keys = {str(key).lower() for key in policy["audit"]["redact_keys"]}
        state_directory = (root / self.config["state_directory"]).resolve()
        self.store = store or RunStateStore(root, state_directory)
        self._clock = clock or _utc_now
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def create(self, run: RunContext) -> dict[str, Any]:
        now = self._now()
        deadline = _format(
            _parse(now) + timedelta(seconds=self.config["limits"]["run_timeout_seconds"])
        )
        state = {
            "schema_version": "1.0",
            "run_id": _required(run.run_id, "run ID"),
            "actor": _required(run.actor, "actor"),
            "status": "created",
            "revision": 0,
            "created_at": now,
            "updated_at": now,
            "deadline_at": deadline,
            "limits": _copy(self.config["limits"]),
            "usage": {"model_turns": 0, "tool_calls": 0, "retries": 0},
            "plans": [],
            "active_plan_revision": None,
            "validation_round": 0,
            "pending_call": None,
            "attempts": [],
            "side_effects": [],
            "validation_evidence": [],
            "transitions": [{"from": None, "to": "created", "at": now, "reason": "Run created"}],
            "terminal_reason": None,
        }
        try:
            return self.store.create(state)
        except StateStoreError as exc:
            raise LifecycleError(str(exc)) from exc

    def get(self, run_id: str) -> dict[str, Any]:
        try:
            state = self.store.load(run_id)
        except StateStoreError as exc:
            raise LifecycleError(str(exc)) from exc
        self._validate_semantics(state)
        return state

    def require_status(self, run_id: str, expected: str) -> dict[str, Any]:
        """Check deadline and require one exact non-terminal lifecycle state."""
        state = self._active(run_id, allow_executing=expected == "executing")
        if state["status"] != expected:
            raise LifecycleError(f"Run requires {expected} state, found: {state['status']}")
        return state

    def inspect(self, run_id: str, reason: str = "Inspection started") -> dict[str, Any]:
        return self._transition(run_id, "inspecting", reason)

    def ready(self, run_id: str, reason: str = "Run is ready") -> dict[str, Any]:
        return self._transition(run_id, "ready", reason)

    def record_model_turn(self, run_id: str) -> dict[str, Any]:
        state = self._active(run_id)
        if state["status"] not in {"inspecting", "ready"}:
            raise LifecycleError(f"Model turns are not allowed from state: {state['status']}")
        if state["usage"]["model_turns"] >= state["limits"]["max_model_turns"]:
            return self._terminal(state, "blocked", "Model-turn limit exhausted")
        state["usage"]["model_turns"] += 1
        return self._save(state)

    def define_plan(
        self, run_id: str, summary: str, actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create a new draft revision and invalidate the previous approved plan."""
        state = self._active(run_id)
        if state["status"] not in {"inspecting", "ready"}:
            raise LifecycleError("Plans can only be defined while inspecting or ready")
        normalized_summary = _required(summary, "plan summary")
        normalized_actions: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for action in actions:
            tool_id = _required(str(action.get("tool_id", "")), "planned tool ID")
            digest = str(action.get("arguments_digest", "")).lower()
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise LifecycleError("Planned arguments digest must be SHA-256 hexadecimal")
            key = (tool_id, digest)
            if key in seen:
                raise LifecycleError("Duplicate planned tool and argument digest")
            seen.add(key)
            normalized_actions.append(
                {
                    "tool_id": tool_id,
                    "arguments_digest": digest,
                    "used": False,
                }
            )
        if not normalized_actions:
            raise LifecycleError("Implementation plans require at least one exact action")
        for existing in state["plans"]:
            if existing["status"] in {"draft", "approved"}:
                existing["status"] = "superseded"
        revision = len(state["plans"]) + 1
        now = self._now()
        digest = plan_digest(run_id, revision, normalized_summary, normalized_actions)
        state["plans"].append(
            {
                "revision": revision,
                "digest": digest,
                "summary": normalized_summary,
                "status": "draft",
                "approval_id": None,
                "created_at": now,
                "approved_at": None,
                "actions": normalized_actions,
            }
        )
        state["active_plan_revision"] = revision
        return self._save(state)

    def current_plan(self, run_id: str) -> dict[str, Any]:
        state = self.get(run_id)
        revision = state["active_plan_revision"]
        if revision is None:
            raise LifecycleError("Run has no implementation plan")
        return _copy(state["plans"][revision - 1])

    def approve_plan(self, run_id: str, approval: PlanApprovalRecord) -> dict[str, Any]:
        state = self._active(run_id)
        revision = state["active_plan_revision"]
        if revision is None:
            raise LifecycleError("Run has no implementation plan to approve")
        plan = state["plans"][revision - 1]
        if plan["status"] != "draft":
            raise LifecycleError("Only the current draft plan can be approved")
        expected = (run_id, revision, plan["digest"])
        actual = (approval.run_id, approval.plan_revision, approval.plan_digest)
        if actual != expected or approval.consumed_at is None:
            raise LifecycleError("Approval does not match the exact current plan")
        plan["status"] = "approved"
        plan["approval_id"] = approval.approval_id
        plan["approved_at"] = approval.consumed_at
        return self._save(state)

    def begin_tool_call(
        self,
        event: PreToolEvent,
        *,
        awaiting_approval: bool,
        retry: bool = False,
        requires_plan: bool = False,
    ) -> dict[str, Any]:
        sensitive = _find_sensitive_keys(event.arguments, self._sensitive_keys)
        if sensitive:
            raise LifecycleError(
                "Raw sensitive tool arguments cannot enter persistent state; "
                "use an approved secret reference"
            )
        state = self._active(event.run_id)
        if state["status"] != "ready":
            raise LifecycleError(f"Tool calls require ready state, found: {state['status']}")
        if state["usage"]["tool_calls"] >= state["limits"]["max_tool_calls"]:
            return self._terminal(state, "blocked", "Tool-call limit exhausted")
        if requires_plan:
            self._consume_planned_action(state, event)
        key = idempotency_key(event)
        matches = [attempt for attempt in state["attempts"] if attempt["idempotency_key"] == key]
        if any(
            attempt["status"] in {"started", "succeeded", "partial", "timed_out"}
            for attempt in matches
        ):
            return self._terminal(
                state,
                "blocked",
                "Duplicate or ambiguous idempotency key requires reconciliation",
            )
        if matches and not retry:
            raise LifecycleError("A failed call with this idempotency key must use retry mode")
        if retry:
            if not matches:
                raise LifecycleError("Retry requires a prior failed attempt")
            if state["usage"]["retries"] >= state["limits"]["max_retries"]:
                return self._terminal(state, "blocked", "Retry limit exhausted")
            state["usage"]["retries"] += 1
        state["usage"]["tool_calls"] += 1
        state["pending_call"] = event.to_dict()
        target = "awaiting_approval" if awaiting_approval else "executing"
        if not awaiting_approval:
            self._append_attempt(state, event, key)
        return self._transition_state(state, target, "Tool call prepared")

    def approval_resumed(self, run_id: str) -> dict[str, Any]:
        state = self._active(run_id)
        if state["status"] != "awaiting_approval" or state["pending_call"] is None:
            raise LifecycleError("Run is not awaiting a persisted approval")
        event = _pre_event(state["pending_call"])
        self._append_attempt(state, event, idempotency_key(event))
        return self._transition_state(state, "executing", "Exact approval consumed")

    def record_tool_result(self, event: PostToolEvent) -> dict[str, Any]:
        state = self._active(event.run_id, allow_executing=True)
        if state["status"] != "executing" or state["pending_call"] is None:
            raise LifecycleError("Run is not executing a persisted tool call")
        if state["pending_call"]["tool_call_id"] != event.tool_call_id:
            raise LifecycleError("Tool result does not match the persisted pending call")
        attempt = _open_attempt(state, event.tool_call_id)
        attempt["status"] = event.status
        attempt["completed_at"] = event.completed_at
        attempt["error"] = event.error
        for effect in event.side_effects:
            state["side_effects"].append(
                {
                    "tool_call_id": event.tool_call_id,
                    "kind": effect.kind,
                    "target": effect.target,
                    "description": effect.description,
                    "reversible": effect.reversible,
                }
            )
        state["pending_call"] = None
        if event.status == "partial" or (event.status == "failed" and bool(event.side_effects)):
            return self._terminal(
                state,
                "blocked",
                "Failed or partial side effects require reconciliation before another run",
            )
        return self._transition_state(
            state,
            "ready",
            "Tool call succeeded"
            if event.status == "succeeded"
            else "Tool call failed without reported side effects",
        )

    def record_tool_timeout(self, run_id: str, tool_call_id: str, error: str) -> dict[str, Any]:
        """Persist a timeout only after an enforcing adapter confirms termination."""
        state = self._active(run_id, allow_executing=True)
        if state["status"] != "executing":
            raise LifecycleError("Tool timeout requires executing state")
        attempt = _open_attempt(state, tool_call_id)
        attempt["status"] = "timed_out"
        attempt["completed_at"] = self._now()
        attempt["error"] = _required(error, "timeout error")
        return self._terminal(
            state,
            "blocked",
            "Enforced tool timeout requires a new reconciled run",
        )

    def begin_validation(self, run_id: str) -> dict[str, Any]:
        state = self._active(run_id)
        if state["status"] != "ready":
            raise LifecycleError("Validation requires ready state")
        state["validation_round"] += 1
        return self._transition_state(state, "validating", "Validation started")

    def add_validation_evidence(
        self, run_id: str, validator: str, summary: str, *, passed: bool
    ) -> dict[str, Any]:
        state = self._active(run_id)
        if state["status"] != "validating":
            raise LifecycleError("Validation evidence requires validating state")
        state["validation_evidence"].append(
            {
                "evidence_id": _required(self._id_factory(), "evidence ID"),
                "validation_round": state["validation_round"],
                "validator": _required(validator, "validator"),
                "summary": _required(summary, "evidence summary"),
                "passed": bool(passed),
                "recorded_at": self._now(),
            }
        )
        return self._save(state)

    def complete(self, run_id: str) -> dict[str, Any]:
        state = self._active(run_id)
        if state["status"] != "validating":
            raise LifecycleError("Completion requires validating state")
        evidence = [
            item
            for item in state["validation_evidence"]
            if item["validation_round"] == state["validation_round"]
        ]
        if not evidence or not all(item["passed"] for item in evidence):
            raise LifecycleError(
                "Completion requires at least one passing evidence record and no failures"
            )
        return self._terminal(state, "completed", "Validation evidence passed")

    def cancel(self, run_id: str, reason: str = "Run cancelled") -> dict[str, Any]:
        state = self._active(run_id, allow_executing=True)
        if state["status"] == "executing":
            return self._terminal(
                state,
                "blocked",
                "Cancellation arrived during execution; side effects require reconciliation",
            )
        return self._terminal(state, "cancelled", reason)

    def fail(self, run_id: str, reason: str) -> dict[str, Any]:
        state = self._active(run_id, allow_executing=True)
        if state["status"] == "executing":
            return self._terminal(
                state,
                "blocked",
                "Failure arrived during execution; side effects require reconciliation",
            )
        return self._terminal(state, "failed", reason)

    def block(self, run_id: str, reason: str) -> dict[str, Any]:
        state = self._active(run_id, allow_executing=True)
        return self._terminal(state, "blocked", reason)

    def recover(self, run_id: str) -> dict[str, Any]:
        state = self.get(run_id)
        if state["status"] == "executing":
            return self._terminal(
                state,
                "blocked",
                "Execution was interrupted; side effects are ambiguous and require reconciliation",
            )
        if state["status"] in TERMINAL:
            return state
        return self._active(run_id)

    def _active(self, run_id: str, *, allow_executing: bool = False) -> dict[str, Any]:
        state = self.get(run_id)
        if state["status"] in TERMINAL:
            raise LifecycleError(f"Run is terminal: {state['status']}")
        if state["status"] == "executing" and not allow_executing:
            raise LifecycleError("Run is already executing")
        if _parse(self._now()) >= _parse(state["deadline_at"]):
            self._terminal(state, "blocked", "Run timeout exhausted")
            raise LifecycleError("Run timeout exhausted")
        return state

    def _transition(self, run_id: str, target: str, reason: str) -> dict[str, Any]:
        return self._transition_state(self._active(run_id), target, reason)

    def _transition_state(self, state: dict[str, Any], target: str, reason: str) -> dict[str, Any]:
        source = state["status"]
        if target not in LEGAL_TRANSITIONS[source]:
            raise LifecycleError(f"Illegal lifecycle transition: {source} -> {target}")
        now = self._now()
        state["status"] = target
        state["updated_at"] = now
        state["transitions"].append(
            {
                "from": source,
                "to": target,
                "at": now,
                "reason": _required(reason, "transition reason"),
            }
        )
        return self._save(state)

    def _terminal(self, state: dict[str, Any], target: str, reason: str) -> dict[str, Any]:
        state["terminal_reason"] = _required(reason, "terminal reason")
        state["pending_call"] = None
        return self._transition_state(state, target, reason)

    def _append_attempt(self, state: dict[str, Any], event: PreToolEvent, key: str) -> None:
        previous = [attempt for attempt in state["attempts"] if attempt["idempotency_key"] == key]
        state["attempts"].append(
            {
                "attempt_id": _required(self._id_factory(), "attempt ID"),
                "tool_call_id": event.tool_call_id,
                "tool_id": event.tool_id,
                "arguments_digest": _arguments_digest(event.arguments),
                "idempotency_key": key,
                "attempt_number": len(previous) + 1,
                "status": "started",
                "started_at": self._now(),
                "completed_at": None,
                "error": None,
            }
        )

    @staticmethod
    def _consume_planned_action(state: dict[str, Any], event: PreToolEvent) -> None:
        revision = state["active_plan_revision"]
        if revision is None:
            raise LifecycleError("State-changing execution requires an approved plan")
        plan = state["plans"][revision - 1]
        if plan["status"] != "approved":
            raise LifecycleError("State-changing execution requires an approved plan")
        digest = arguments_digest(event.arguments)
        matches = [
            action
            for action in plan["actions"]
            if action["tool_id"] == event.tool_id and action["arguments_digest"] == digest
        ]
        if len(matches) != 1:
            raise LifecycleError("Tool call is outside the exact approved plan")
        action = matches[0]
        if action["used"]:
            raise LifecycleError("Exact approved plan action has already been used")
        action["used"] = True

    def _save(self, state: dict[str, Any]) -> dict[str, Any]:
        state["updated_at"] = self._now()
        try:
            return self.store.save(state, expected_revision=state["revision"])
        except StateStoreError as exc:
            raise LifecycleError(str(exc)) from exc

    def _now(self) -> str:
        return _format(_parse(self._clock()))

    @staticmethod
    def _validate_semantics(state: dict[str, Any]) -> None:
        transitions = state["transitions"]
        if transitions[0]["from"] is not None or transitions[0]["to"] != "created":
            raise LifecycleError("Persistent transition history must begin at created")
        previous = "created"
        for transition in transitions[1:]:
            if transition["from"] != previous:
                raise LifecycleError("Persistent transition history is not contiguous")
            if transition["to"] not in LEGAL_TRANSITIONS.get(previous, set()):
                raise LifecycleError("Persistent transition history contains an illegal transition")
            previous = transition["to"]
        if previous != state["status"]:
            raise LifecycleError("Persistent transition history does not match current status")
        pending = state["pending_call"]
        pending_states = {"awaiting_approval", "executing"}
        if state["status"] in pending_states and pending is None:
            raise LifecycleError("Persistent active tool state is missing its exact call")
        if state["status"] not in pending_states and pending is not None:
            raise LifecycleError("Persistent pending call is invalid for current state")
        if pending is not None and (
            pending["run_id"] != state["run_id"] or pending["actor"] != state["actor"]
        ):
            raise LifecycleError("Persistent pending call does not match its run identity")
        open_attempts = [attempt for attempt in state["attempts"] if attempt["status"] == "started"]
        if state["status"] == "executing":
            if (
                len(open_attempts) != 1
                or open_attempts[0]["tool_call_id"] != pending["tool_call_id"]
            ):
                raise LifecycleError(
                    "Persistent execution state must have one matching open attempt"
                )
        elif state["status"] not in TERMINAL and open_attempts:
            raise LifecycleError("Persistent non-executing state has an open attempt")
        attempt_call_ids = [attempt["tool_call_id"] for attempt in state["attempts"]]
        if len(attempt_call_ids) != len(set(attempt_call_ids)):
            raise LifecycleError("Persistent attempts contain duplicate tool-call IDs")
        usage = state["usage"]
        limits = state["limits"]
        if usage["model_turns"] > limits["max_model_turns"]:
            raise LifecycleError("Persistent model-turn usage exceeds its trusted limit")
        if usage["tool_calls"] > limits["max_tool_calls"]:
            raise LifecycleError("Persistent tool-call usage exceeds its trusted limit")
        if usage["retries"] > limits["max_retries"]:
            raise LifecycleError("Persistent retry usage exceeds its trusted limit")
        plans = state["plans"]
        if not plans and state["active_plan_revision"] is not None:
            raise LifecycleError("Active plan revision exists without plan history")
        if plans:
            if state["active_plan_revision"] != len(plans):
                raise LifecycleError("Active plan revision must identify the latest plan")
            for index, plan in enumerate(plans, start=1):
                if plan["revision"] != index:
                    raise LifecycleError("Plan revisions must be contiguous")
                expected_digest = plan_digest(
                    state["run_id"], index, plan["summary"], plan["actions"]
                )
                if plan["digest"] != expected_digest:
                    raise LifecycleError("Persistent plan digest does not match its manifest")
                if plan["status"] == "draft" and (
                    plan["approval_id"] is not None or plan["approved_at"] is not None
                ):
                    raise LifecycleError("Draft plan contains approval metadata")
                if plan["status"] == "approved" and (
                    plan["approval_id"] is None or plan["approved_at"] is None
                ):
                    raise LifecycleError("Approved plan lacks approval metadata")
            if plans[-1]["status"] not in {"draft", "approved"}:
                raise LifecycleError("Latest plan revision cannot be superseded")
            if any(plan["status"] != "superseded" for plan in plans[:-1]):
                raise LifecycleError("Only the latest plan revision can remain current")
        for evidence in state["validation_evidence"]:
            if evidence["validation_round"] > state["validation_round"]:
                raise LifecycleError("Validation evidence refers to a future round")
        if state["status"] == "completed":
            current_evidence = [
                item
                for item in state["validation_evidence"]
                if item["validation_round"] == state["validation_round"]
            ]
            if not current_evidence or not all(item["passed"] for item in current_evidence):
                raise LifecycleError("Completed state lacks passing current-round evidence")


def idempotency_key(event: PreToolEvent) -> str:
    payload = {
        "run_id": event.run_id,
        "tool_id": event.tool_id,
        "arguments": event.arguments,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _arguments_digest(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(arguments).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LifecycleError("Lifecycle values must contain strict JSON") from exc


def _copy(value: Any) -> Any:
    return json.loads(_canonical(value))


def _parse(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise LifecycleError("Lifecycle timestamps must use RFC 3339") from exc
    if parsed.tzinfo is None:
        raise LifecycleError("Lifecycle timestamps must include a UTC offset")
    return parsed


def _format(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise LifecycleError(f"{field} must not be empty")
    return normalized


def _utc_now() -> str:
    return _format(datetime.now(timezone.utc))


def _pre_event(payload: dict[str, Any]) -> PreToolEvent:
    return PreToolEvent(
        schema_version=payload["schema_version"],
        event_type=payload["event_type"],
        run_id=payload["run_id"],
        tool_call_id=payload["tool_call_id"],
        tool_id=payload["tool_id"],
        arguments=_copy(payload["arguments"]),
        requested_at=payload["requested_at"],
        actor=payload["actor"],
    )


def _open_attempt(state: dict[str, Any], tool_call_id: str) -> dict[str, Any]:
    matches = [
        attempt
        for attempt in state["attempts"]
        if attempt["tool_call_id"] == tool_call_id and attempt["status"] == "started"
    ]
    if len(matches) != 1:
        raise LifecycleError("Persisted execution attempt is missing or ambiguous")
    return matches[0]


def _find_sensitive_keys(value: Any, sensitive_keys: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in sensitive_keys:
                found.add(str(key))
            found.update(_find_sensitive_keys(nested, sensitive_keys))
    elif isinstance(value, list):
        for nested in value:
            found.update(_find_sensitive_keys(nested, sensitive_keys))
    return found
