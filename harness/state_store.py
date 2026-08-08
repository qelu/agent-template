"""Atomic, schema-validated persistence for executable run state."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


class StateStoreError(RuntimeError):
    """Raised for invalid, conflicting, or unavailable persistent state."""


class RunStateStore:
    """Persist one versioned JSON snapshot per run using atomic replacement."""

    def __init__(self, root: Path, state_directory: Path) -> None:
        self._root = root.resolve()
        self._directory = state_directory.resolve()
        if self._directory != self._root and self._root not in self._directory.parents:
            raise StateStoreError("Lifecycle state directory must remain inside the repository")
        try:
            self._schema = json.loads(
                (root / "config" / "schemas" / "run-state.schema.json").read_text(encoding="utf-8")
            )
            Draft202012Validator.check_schema(self._schema)
        except (OSError, ValueError, TypeError, SchemaError) as exc:
            raise StateStoreError(f"Invalid run-state schema: {exc}") from exc

    @property
    def directory(self) -> Path:
        return self._directory

    def create(self, state: dict[str, Any]) -> dict[str, Any]:
        self._validate(state)
        path = self._path(str(state["run_id"]))
        with self._lock(path):
            if path.exists():
                raise StateStoreError(f"Run state already exists: {state['run_id']}")
            self._atomic_write(path, state)
        return _copy(state)

    def load(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise StateStoreError(f"Run state does not exist: {run_id}") from exc
        except (OSError, ValueError, TypeError) as exc:
            raise StateStoreError(f"Cannot load run state {run_id}: {exc}") from exc
        if not isinstance(payload, dict):
            raise StateStoreError(f"Run state must be an object: {run_id}")
        self._validate(payload)
        if payload["run_id"] != run_id:
            raise StateStoreError("Run-state filename does not match its trusted run ID")
        return _copy(payload)

    def save(self, state: dict[str, Any], *, expected_revision: int) -> dict[str, Any]:
        run_id = str(state.get("run_id", ""))
        path = self._path(run_id)
        with self._lock(path):
            current = self.load(run_id)
            if current["revision"] != expected_revision:
                raise StateStoreError(
                    f"Run-state revision conflict for {run_id}: "
                    f"expected {expected_revision}, found {current['revision']}"
                )
            candidate = _copy(state)
            candidate["revision"] = expected_revision + 1
            self._validate(candidate)
            self._atomic_write(path, candidate)
        return _copy(candidate)

    def _validate(self, state: dict[str, Any]) -> None:
        errors = sorted(
            Draft202012Validator(self._schema, format_checker=FormatChecker()).iter_errors(state),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            details = "; ".join(error.message for error in errors)
            raise StateStoreError(f"Invalid persistent run state: {details}")

    def _path(self, run_id: str) -> Path:
        normalized = run_id.strip()
        if not normalized:
            raise StateStoreError("Run ID must not be empty")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self._directory / "runs" / f"{digest}.json"

    @contextmanager
    def _lock(self, path: Path) -> Iterator[None]:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._directory, 0o700)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        lock = path.with_suffix(".lock")
        descriptor = os.open(lock, os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StateStoreError(
                    f"Run state is locked by another writer: {path.name}"
                ) from exc
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @staticmethod
    def _atomic_write(path: Path, state: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        serialized = (
            json.dumps(
                state,
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
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                os.chmod(temporary_name, 0o600)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink()
                except FileNotFoundError:
                    pass


def _copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise StateStoreError("Run state must contain strict JSON values") from exc
