"""Trusted, exact, single-use approvals for normalized tool calls."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import fcntl
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from harness.runtime import PreToolEvent


class ApprovalError(RuntimeError):
    """Raised when an approval is forged, mismatched, duplicated, or reused."""


@dataclass(frozen=True)
class ApprovalRecord:
    schema_version: str
    approval_id: str
    run_id: str
    tool_call_id: str
    tool_id: str
    arguments_digest: str
    granted_at: str
    granted_by: str
    single_use: bool
    consumed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApprovalStore:
    """Create approvals only from trusted events and consume each approval once."""

    def __init__(
        self,
        root: Path,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
        storage_directory: Path | None = None,
    ) -> None:
        try:
            self._schema = json.loads(
                (root / "config" / "schemas" / "approval.schema.json").read_text(encoding="utf-8")
            )
            Draft202012Validator.check_schema(self._schema)
        except (OSError, ValueError, TypeError, SchemaError) as exc:
            raise ApprovalError(f"Invalid trusted approval schema: {exc}") from exc
        self._id_factory = id_factory or (lambda: secrets.token_urlsafe(24))
        self._clock = clock or _utc_now
        self._storage_directory = storage_directory
        self._records: dict[str, ApprovalRecord] = {}
        self._by_call: dict[tuple[str, str], str] = {}
        self._load_persistent_records()

    def grant(self, event: PreToolEvent, granted_by: str) -> ApprovalRecord:
        """Create a record from an adapter-owned event, never caller-supplied metadata."""
        with self._persistent_lock():
            self._refresh_persistent_records()
            return self._grant(event, granted_by)

    def _grant(self, event: PreToolEvent, granted_by: str) -> ApprovalRecord:
        call_key = (event.run_id, event.tool_call_id)
        if call_key in self._by_call:
            raise ApprovalError(f"Approval already exists for call: {event.tool_call_id}")
        approval_id = _required(self._id_factory(), "generated approval ID")
        if approval_id in self._records:
            raise ApprovalError(f"Generated duplicate approval ID: {approval_id}")
        record = ApprovalRecord(
            schema_version="1.0",
            approval_id=approval_id,
            run_id=event.run_id,
            tool_call_id=event.tool_call_id,
            tool_id=event.tool_id,
            arguments_digest=arguments_digest(event.arguments),
            granted_at=self._clock(),
            granted_by=_required(granted_by, "approver identity"),
            single_use=True,
            consumed_at=None,
        )
        self._validate(record)
        self._persist(record)
        self._records[approval_id] = record
        self._by_call[call_key] = approval_id
        return record

    def consume(self, event: PreToolEvent, approval_id: str) -> ApprovalRecord:
        """Consume only an unused approval bound to every trusted call field."""
        with self._persistent_lock():
            self._refresh_persistent_records()
            return self._consume(event, approval_id)

    def _consume(self, event: PreToolEvent, approval_id: str) -> ApprovalRecord:
        try:
            record = self._records[approval_id]
        except KeyError as exc:
            raise ApprovalError("Approval does not exist in the trusted store") from exc
        if record.consumed_at is not None:
            raise ApprovalError(f"Approval has already been consumed: {approval_id}")
        expected = (
            event.run_id,
            event.tool_call_id,
            event.tool_id,
            arguments_digest(event.arguments),
        )
        actual = (
            record.run_id,
            record.tool_call_id,
            record.tool_id,
            record.arguments_digest,
        )
        if actual != expected:
            raise ApprovalError("Approval does not match the exact trusted tool call")
        consumed = replace(record, consumed_at=self._clock())
        self._validate(consumed)
        self._persist(consumed)
        self._records[approval_id] = consumed
        return consumed

    def get(self, approval_id: str) -> ApprovalRecord:
        self._refresh_persistent_records()
        try:
            return self._records[approval_id]
        except KeyError as exc:
            raise ApprovalError("Approval does not exist in the trusted store") from exc

    def _validate(self, record: ApprovalRecord) -> None:
        errors = sorted(
            Draft202012Validator(self._schema, format_checker=FormatChecker()).iter_errors(
                record.to_dict()
            ),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            details = "; ".join(error.message for error in errors)
            raise ApprovalError(f"Invalid trusted approval record: {details}")
        granted_at = _validate_timestamp(record.granted_at, "granted_at")
        if record.consumed_at is not None:
            consumed_at = _validate_timestamp(record.consumed_at, "consumed_at")
            if consumed_at < granted_at:
                raise ApprovalError("consumed_at must not precede granted_at")

    def _load_persistent_records(self) -> None:
        if self._storage_directory is None:
            return
        directory = self._storage_directory / "approvals"
        if not directory.exists():
            return
        try:
            paths = sorted(directory.glob("*.json"))
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = ApprovalRecord(**payload)
                self._validate(record)
                if record.approval_id in self._records:
                    raise ApprovalError(f"Duplicate persisted approval: {record.approval_id}")
                call_key = (record.run_id, record.tool_call_id)
                if call_key in self._by_call:
                    raise ApprovalError(
                        f"Multiple persisted approvals for call: {record.tool_call_id}"
                    )
                self._records[record.approval_id] = record
                self._by_call[call_key] = record.approval_id
        except (OSError, ValueError, TypeError) as exc:
            raise ApprovalError(f"Invalid persisted approval state: {exc}") from exc

    def _refresh_persistent_records(self) -> None:
        if self._storage_directory is None:
            return
        self._records = {}
        self._by_call = {}
        self._load_persistent_records()

    @contextmanager
    def _persistent_lock(self) -> Iterator[None]:
        if self._storage_directory is None:
            yield
            return
        directory = self._storage_directory / "approvals"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        descriptor = os.open(directory / ".lock", os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ApprovalError("Approval state is locked by another writer") from exc
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _persist(self, record: ApprovalRecord) -> None:
        if self._storage_directory is None:
            return
        directory = self._storage_directory / "approvals"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        filename = hashlib.sha256(record.approval_id.encode("utf-8")).hexdigest()
        destination = directory / f"{filename}.json"
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
                dir=directory,
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
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise ApprovalError(f"Cannot persist approval state: {exc}") from exc
        finally:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink()
                except FileNotFoundError:
                    pass


def arguments_digest(arguments: dict[str, Any]) -> str:
    """Hash canonical JSON arguments for exact approval binding."""
    try:
        canonical = json.dumps(
            arguments,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ApprovalError("Approval arguments must be strict JSON values") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ApprovalError(f"{field} must not be empty")
    return normalized


def _validate_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalError(f"{field} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ApprovalError(f"{field} must include a UTC offset")
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
