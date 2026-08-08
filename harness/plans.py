"""Exact, host-created approvals for versioned implementation plans."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


class PlanApprovalError(RuntimeError):
    """Raised when a plan approval is missing, mismatched, duplicated, or reused."""


@dataclass(frozen=True)
class PlanApprovalRecord:
    schema_version: str
    approval_id: str
    run_id: str
    plan_revision: int
    plan_digest: str
    granted_at: str
    granted_by: str
    single_use: bool
    consumed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlanApprovalStore:
    """Persist single-use approvals bound to one exact run and plan revision."""

    def __init__(
        self,
        root: Path,
        *,
        storage_directory: Path | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        try:
            self._schema = json.loads(
                (root / "config" / "schemas" / "plan-approval.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            Draft202012Validator.check_schema(self._schema)
        except (OSError, ValueError, TypeError, SchemaError) as exc:
            raise PlanApprovalError(f"Invalid plan-approval schema: {exc}") from exc
        self._directory = (
            storage_directory / "plan-approvals" if storage_directory is not None else None
        )
        self._id_factory = id_factory or (lambda: secrets.token_urlsafe(24))
        self._clock = clock or _utc_now
        self._records: dict[str, PlanApprovalRecord] = {}
        self._by_plan: dict[tuple[str, int], str] = {}
        self._refresh()

    def grant(
        self, run_id: str, plan_revision: int, plan_digest: str, granted_by: str
    ) -> PlanApprovalRecord:
        with self._lock():
            self._refresh()
            key = (_required(run_id, "run ID"), plan_revision)
            if key in self._by_plan:
                raise PlanApprovalError(
                    f"Plan approval already exists for run {run_id} revision {plan_revision}"
                )
            approval_id = _required(self._id_factory(), "generated approval ID")
            if approval_id in self._records:
                raise PlanApprovalError("Generated plan approval ID already exists")
            record = PlanApprovalRecord(
                schema_version="1.0",
                approval_id=approval_id,
                run_id=key[0],
                plan_revision=plan_revision,
                plan_digest=_digest(plan_digest),
                granted_at=self._clock(),
                granted_by=_required(granted_by, "approver identity"),
                single_use=True,
                consumed_at=None,
            )
            self._validate(record)
            self._persist(record)
            self._records[approval_id] = record
            self._by_plan[key] = approval_id
            return record

    def consume(
        self,
        run_id: str,
        plan_revision: int,
        plan_digest: str,
        approval_id: str,
    ) -> PlanApprovalRecord:
        with self._lock():
            self._refresh()
            try:
                record = self._records[approval_id]
            except KeyError as exc:
                raise PlanApprovalError("Plan approval does not exist") from exc
            if record.consumed_at is not None:
                raise PlanApprovalError("Plan approval has already been consumed")
            expected = (run_id, plan_revision, _digest(plan_digest))
            actual = (record.run_id, record.plan_revision, record.plan_digest)
            if actual != expected:
                raise PlanApprovalError("Plan approval does not match the exact plan")
            consumed = replace(record, consumed_at=self._clock())
            self._validate(consumed)
            self._persist(consumed)
            self._records[approval_id] = consumed
            return consumed

    def _refresh(self) -> None:
        if self._directory is None:
            return
        self._records = {}
        self._by_plan = {}
        if not self._directory.exists():
            return
        try:
            for path in sorted(self._directory.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = PlanApprovalRecord(**payload)
                self._validate(record)
                key = (record.run_id, record.plan_revision)
                if record.approval_id in self._records or key in self._by_plan:
                    raise PlanApprovalError("Duplicate persisted plan approval")
                self._records[record.approval_id] = record
                self._by_plan[key] = record.approval_id
        except (OSError, ValueError, TypeError) as exc:
            raise PlanApprovalError(f"Invalid persisted plan approval: {exc}") from exc

    def _validate(self, record: PlanApprovalRecord) -> None:
        errors = sorted(
            Draft202012Validator(self._schema, format_checker=FormatChecker()).iter_errors(
                record.to_dict()
            ),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            raise PlanApprovalError(
                "Invalid plan approval: " + "; ".join(error.message for error in errors)
            )
        granted = _timestamp(record.granted_at)
        if record.consumed_at is not None and _timestamp(record.consumed_at) < granted:
            raise PlanApprovalError("Plan approval consumption predates its grant")

    @contextmanager
    def _lock(self) -> Iterator[None]:
        if self._directory is None:
            yield
            return
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._directory, 0o700)
        descriptor = os.open(self._directory / ".lock", os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PlanApprovalError("Plan approval state is locked") from exc
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _persist(self, record: PlanApprovalRecord) -> None:
        if self._directory is None:
            return
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._directory, 0o700)
        filename = hashlib.sha256(record.approval_id.encode("utf-8")).hexdigest()
        destination = self._directory / f"{filename}.json"
        serialized = (
            json.dumps(
                record.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._directory,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                os.chmod(temporary_name, 0o600)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            directory_descriptor = os.open(self._directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError as exc:
            raise PlanApprovalError(f"Cannot persist plan approval: {exc}") from exc
        finally:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink()
                except FileNotFoundError:
                    pass


def plan_digest(run_id: str, revision: int, summary: str, actions: list[dict[str, Any]]) -> str:
    canonical_actions = [
        {
            "tool_id": action["tool_id"],
            "arguments_digest": action["arguments_digest"],
        }
        for action in actions
    ]
    payload = {
        "run_id": run_id,
        "revision": revision,
        "summary": summary,
        "actions": canonical_actions,
    }
    canonical = _canonical(payload, "Plan manifest")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def arguments_digest(arguments: dict[str, Any]) -> str:
    canonical = _canonical(arguments, "Plan arguments")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical(value: Any, field: str) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PlanApprovalError(f"{field} must be canonical JSON") from exc


def _digest(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise PlanApprovalError("Plan digest must be a SHA-256 hexadecimal digest")
    return normalized


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise PlanApprovalError(f"{field} must not be empty")
    return normalized


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanApprovalError("Plan approval timestamp must use RFC 3339") from exc
    if parsed.tzinfo is None:
        raise PlanApprovalError("Plan approval timestamp must include a UTC offset")
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
