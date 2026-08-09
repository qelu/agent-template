"""Validate and manage the canonical capability lifecycle registry."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from harness.configuration import load_yaml

HOSTS = ("portable", "codex", "claude-code", "antigravity")
LEGAL_TRANSITIONS = {
    "proposed": {"tested", "disabled"},
    "tested": {"active", "disabled"},
    "active": {"deprecated", "disabled"},
    "deprecated": {"disabled"},
    "disabled": set(),
}


class CapabilityError(ValueError):
    """Raised when the capability registry violates its contract."""


def artifact_digest(path: Path) -> str:
    """Hash a capability file or tree using relative paths and file contents."""
    if not path.exists():
        raise CapabilityError(f"Capability artifact does not exist: {path}")
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    digest = hashlib.sha256()
    for file in files:
        relative = file.name if path.is_file() else file.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def file_digest(path: Path) -> str:
    if not path.is_file():
        raise CapabilityError(f"Evaluation suite does not exist: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capability_definition_digest(capability: dict[str, Any]) -> str:
    """Hash all declarative fields that affect behavior or authority."""
    fields = (
        "id",
        "type",
        "version",
        "path",
        "artifact_digest",
        "description",
        "risk_level",
        "owner",
        "requires",
        "compatibility",
        "evaluation_suite",
    )
    canonical = json.dumps(
        {field: capability[field] for field in fields},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_capabilities(root: Path) -> list[dict[str, Any]]:
    """Load, schema-validate, and semantically verify all capabilities."""
    payload = _load_registry(root)
    capabilities = payload["capabilities"]
    by_id: dict[str, dict[str, Any]] = {}
    approval_ids: set[str] = set()
    for capability in capabilities:
        capability_id = capability["id"]
        if capability_id in by_id:
            raise CapabilityError(f"Duplicate capability ID: {capability_id}")
        by_id[capability_id] = capability
        target = _contained_path(root, capability["path"])
        if artifact_digest(target) != capability["artifact_digest"]:
            raise CapabilityError(
                f"Capability {capability_id} changed without a version/lifecycle update"
            )
        if capability_definition_digest(capability) != capability["definition_digest"]:
            raise CapabilityError(
                f"Capability {capability_id} contract changed without a version/lifecycle update"
            )
        suite = capability["evaluation_suite"]
        suite_path = _contained_path(root, suite) if suite is not None else None
        if suite_path is not None and not suite_path.is_file():
            raise CapabilityError(f"Evaluation suite does not exist for {capability_id}: {suite}")
        _validate_history(capability)
        _validate_evidence(capability, suite_path)
        activation = capability["activation"]
        if activation is not None:
            approval_id = activation["approval_id"]
            if approval_id in approval_ids:
                raise CapabilityError(f"Duplicate capability approval ID: {approval_id}")
            approval_ids.add(approval_id)

    _validate_dependencies(capabilities, by_id)
    _validate_cycles(by_id)
    return capabilities


def active_capabilities(root: Path) -> list[dict[str, Any]]:
    return [item for item in load_capabilities(root) if item["status"] == "active"]


class CapabilityLifecycle:
    """Host-operated state transitions for the single canonical registry."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.root = root.resolve()
        self._clock = clock or _utc_now
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def record_passing_evaluation(self, capability_id: str, recorded_by: str) -> None:
        payload, capability = self._current(capability_id)
        if capability["status"] != "proposed":
            raise CapabilityError("Only a proposed capability can become tested")
        suite = capability["evaluation_suite"]
        if suite is None:
            raise CapabilityError("Testing requires a declared evaluation suite")
        capability["evaluation"] = {
            "suite_digest": file_digest(_contained_path(self.root, suite)),
            "artifact_digest": capability["artifact_digest"],
            "passed_at": self._now(),
            "recorded_by": _required(recorded_by, "evaluation actor"),
        }
        self._transition(capability, "tested", recorded_by, "Evaluation passed")
        self._save(payload)

    def activate(self, capability_id: str, approved_by: str) -> None:
        """Host-only activation; callers must bind this to a real human approval UI."""
        payload, capability = self._current(capability_id)
        if capability["status"] != "tested" or capability["evaluation"] is None:
            raise CapabilityError("Activation requires a tested capability")
        self._require_dependencies_active(payload, capability)
        actor = _required(approved_by, "human approver")
        capability["activation"] = {
            "approval_id": _required(self._id_factory(), "approval ID"),
            "approved_by": actor,
            "approved_at": self._now(),
            "version": capability["version"],
            "artifact_digest": capability["artifact_digest"],
            "definition_digest": capability["definition_digest"],
            "suite_digest": capability["evaluation"]["suite_digest"],
        }
        self._transition(capability, "active", actor, "Human activation approved")
        self._save(payload)

    def deprecate(self, capability_id: str, actor: str) -> None:
        payload, capability = self._current(capability_id)
        if capability["status"] != "active":
            raise CapabilityError("Only an active capability can be deprecated")
        dependents = _dependents(payload["capabilities"], capability_id, active_only=True)
        if dependents:
            raise CapabilityError(f"Active dependents block deprecation: {', '.join(dependents)}")
        self._transition(capability, "deprecated", actor, "Capability deprecated")
        self._save(payload)

    def disable(self, capability_id: str, actor: str, reason: str) -> None:
        payload, capability = self._current(capability_id)
        if capability["status"] == "disabled":
            raise CapabilityError("Capability is already disabled")
        normalized_reason = _required(reason, "disable reason")
        by_id = {item["id"]: item for item in payload["capabilities"]}

        def cascade(item: dict[str, Any]) -> None:
            for dependent_id in _dependents(payload["capabilities"], item["id"], active_only=True):
                dependent = by_id[dependent_id]
                if dependent["status"] != "disabled":
                    cascade(dependent)
            item["disabled_from"] = item["status"]
            self._transition(item, "disabled", actor, normalized_reason)

        cascade(capability)
        self._save(payload)

    def restore(self, capability_id: str, actor: str) -> None:
        payload, capability = self._current(capability_id)
        target = capability["disabled_from"]
        if capability["status"] != "disabled" or target is None:
            raise CapabilityError("Capability has no disabled state to restore")
        if target == "active":
            self._require_dependencies_active(payload, capability)
            _validate_evidence(
                capability, _contained_path(self.root, capability["evaluation_suite"])
            )
        capability["disabled_from"] = None
        self._transition(capability, target, actor, "Disabled capability restored", restore=True)
        self._save(payload)

    def bump_version(self, capability_id: str, version: str, actor: str) -> None:
        payload, capability = self._current(capability_id, verify=False)
        if _semver(version) <= _semver(capability["version"]):
            raise CapabilityError("New capability version must be greater than the current version")
        dependents = _dependents(payload["capabilities"], capability_id, active_only=True)
        if dependents:
            raise CapabilityError(
                f"Active dependents block version change: {', '.join(dependents)}"
            )
        capability["version"] = version
        capability["artifact_digest"] = artifact_digest(
            _contained_path(self.root, capability["path"])
        )
        capability["evaluation"] = None
        capability["activation"] = None
        capability["disabled_from"] = None
        capability["definition_digest"] = capability_definition_digest(capability)
        self._transition(
            capability,
            "proposed",
            actor,
            "Behavior or contract changed; evaluation reset",
            version_reset=True,
        )
        self._save(payload)

    def remove(self, capability_id: str) -> None:
        payload, capability = self._current(capability_id)
        if capability["status"] != "deprecated":
            raise CapabilityError("Removal requires deprecated status")
        dependents = _dependents(payload["capabilities"], capability_id, active_only=False)
        if dependents:
            raise CapabilityError(f"Dependents block removal: {', '.join(dependents)}")
        payload["capabilities"] = [
            item for item in payload["capabilities"] if item["id"] != capability_id
        ]
        self._save(payload)

    def _current(
        self, capability_id: str, *, verify: bool = True
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = _load_registry(self.root, semantic=verify)
        try:
            capability = next(
                item for item in payload["capabilities"] if item["id"] == capability_id
            )
        except StopIteration as exc:
            raise CapabilityError(f"Unknown capability: {capability_id}") from exc
        return payload, capability

    def _transition(
        self,
        capability: dict[str, Any],
        target: str,
        actor: str,
        reason: str,
        *,
        restore: bool = False,
        version_reset: bool = False,
    ) -> None:
        source = capability["status"]
        if not restore and not version_reset and target not in LEGAL_TRANSITIONS[source]:
            raise CapabilityError(f"Illegal capability transition: {source} -> {target}")
        capability["status"] = target
        capability["history"].append(
            {
                "from": source,
                "to": target,
                "at": self._now(),
                "actor": _required(actor, "transition actor"),
                "reason": reason,
                "version": capability["version"],
                "artifact_digest": capability["artifact_digest"],
            }
        )

    def _require_dependencies_active(
        self, payload: dict[str, Any], capability: dict[str, Any]
    ) -> None:
        by_id = {item["id"]: item for item in payload["capabilities"]}
        for requirement in capability["requires"]:
            dependency = by_id[requirement["id"]]
            if dependency["status"] != "active" or _semver(dependency["version"]) < _semver(
                requirement["minimum_version"]
            ):
                raise CapabilityError(
                    f"Dependency is not active and compatible: {requirement['id']}"
                )

    def _save(self, payload: dict[str, Any]) -> None:
        path = self.root / "config" / "capabilities.yaml"
        serialized = yaml.safe_dump(payload, sort_keys=False)
        original = path.read_text(encoding="utf-8")
        _atomic_write(path, serialized)
        try:
            load_capabilities(self.root)
        except Exception:
            _atomic_write(path, original)
            raise

    def _now(self) -> str:
        return self._clock()


def proposed_capability(
    root: Path,
    *,
    capability_id: str,
    capability_type: str,
    version: str,
    path: str,
    description: str,
    risk_level: str,
    owner: str,
    actor: str,
    evaluation_suite: str | None = None,
    hosts: list[str] | None = None,
) -> dict[str, Any]:
    digest = artifact_digest(_contained_path(root, path))
    now = _utc_now()
    capability = {
        "id": capability_id,
        "type": capability_type,
        "version": version,
        "status": "proposed",
        "path": path,
        "artifact_digest": digest,
        "definition_digest": "",
        "description": description,
        "risk_level": risk_level,
        "owner": owner,
        "requires": [],
        "compatibility": {
            "hosts": hosts or list(HOSTS),
        },
        "evaluation_suite": evaluation_suite,
        "evaluation": None,
        "activation": None,
        "disabled_from": None,
        "history": [
            {
                "from": None,
                "to": "proposed",
                "at": now,
                "actor": actor,
                "reason": "Capability proposed",
                "version": version,
                "artifact_digest": digest,
            }
        ],
    }
    capability["definition_digest"] = capability_definition_digest(capability)
    return capability


def attested_active_capability(
    root: Path,
    *,
    capability_id: str,
    capability_type: str,
    version: str,
    path: str,
    description: str,
    risk_level: str,
    owner: str,
    evaluation_suite: str,
    approved_by: str,
    approval_id: str,
    hosts: list[str] | None = None,
) -> dict[str, Any]:
    """Create an initializer-owned active record from explicit user configuration."""
    capability = proposed_capability(
        root,
        capability_id=capability_id,
        capability_type=capability_type,
        version=version,
        path=path,
        description=description,
        risk_level=risk_level,
        owner=owner,
        actor=approved_by,
        evaluation_suite=evaluation_suite,
        hosts=hosts,
    )
    now = _utc_now()
    suite_digest = file_digest(_contained_path(root, evaluation_suite))
    capability["evaluation"] = {
        "suite_digest": suite_digest,
        "artifact_digest": capability["artifact_digest"],
        "passed_at": now,
        "recorded_by": approved_by,
    }
    capability["history"].append(
        {
            "from": "proposed",
            "to": "tested",
            "at": now,
            "actor": approved_by,
            "reason": "Initializer validation recorded",
            "version": version,
            "artifact_digest": capability["artifact_digest"],
        }
    )
    capability["activation"] = {
        "approval_id": approval_id,
        "approved_by": approved_by,
        "approved_at": now,
        "version": version,
        "artifact_digest": capability["artifact_digest"],
        "definition_digest": capability["definition_digest"],
        "suite_digest": suite_digest,
    }
    capability["status"] = "active"
    capability["history"].append(
        {
            "from": "tested",
            "to": "active",
            "at": now,
            "actor": approved_by,
            "reason": "Explicit initializer selection approved activation",
            "version": version,
            "artifact_digest": capability["artifact_digest"],
        }
    )
    return capability


def _load_registry(root: Path, *, semantic: bool = False) -> dict[str, Any]:
    payload = load_yaml(root / "config" / "capabilities.yaml")
    schema = json.loads(
        (root / "config" / "schemas" / "capability.schema.json").read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(_format_schema_error(error) for error in errors)
        raise CapabilityError(f"Invalid capability registry: {details}")
    if semantic:
        load_capabilities(root)
    return payload


def _validate_history(capability: dict[str, Any]) -> None:
    history = capability["history"]
    first = history[0]
    if first["from"] is not None or first["to"] != "proposed":
        raise CapabilityError(f"{capability['id']} history must begin at proposed")
    previous = "proposed"
    previous_version = first["version"]
    previous_artifact = first["artifact_digest"]
    for transition in history[1:]:
        if transition["from"] != previous:
            raise CapabilityError(f"{capability['id']} history is not contiguous")
        target = transition["to"]
        legal = target in LEGAL_TRANSITIONS[previous]
        restored = previous == "disabled" and target != "disabled"
        reset = target == "proposed" and _semver(transition["version"]) > _semver(previous_version)
        if not (legal or restored or reset):
            raise CapabilityError(f"{capability['id']} history contains an illegal transition")
        if not reset and (
            transition["version"] != previous_version
            or transition["artifact_digest"] != previous_artifact
        ):
            raise CapabilityError(f"{capability['id']} changed without a version reset")
        previous = target
        previous_version = transition["version"]
        previous_artifact = transition["artifact_digest"]
    if previous != capability["status"]:
        raise CapabilityError(f"{capability['id']} history does not match status")
    latest = history[-1]
    if (
        latest["version"] != capability["version"]
        or latest["artifact_digest"] != capability["artifact_digest"]
    ):
        raise CapabilityError(f"{capability['id']} history does not match current artifact")
    if capability["status"] == "disabled" and capability["disabled_from"] is None:
        raise CapabilityError(f"{capability['id']} disabled state lacks its source status")
    if capability["status"] != "disabled" and capability["disabled_from"] is not None:
        raise CapabilityError(f"{capability['id']} has stale disabled-state metadata")


def _validate_evidence(capability: dict[str, Any], suite_path: Path | None) -> None:
    status = capability["status"]
    evaluation = capability["evaluation"]
    activation = capability["activation"]
    if status in {"tested", "active", "deprecated"} and (suite_path is None or evaluation is None):
        raise CapabilityError(f"{capability['id']} requires passing evaluation evidence")
    if evaluation is not None:
        if suite_path is None or evaluation["suite_digest"] != file_digest(suite_path):
            raise CapabilityError(f"{capability['id']} evaluation suite changed; retest required")
        if evaluation["artifact_digest"] != capability["artifact_digest"]:
            raise CapabilityError(f"{capability['id']} evaluation is stale")
    if status in {"active", "deprecated"}:
        if activation is None or evaluation is None:
            raise CapabilityError(f"{capability['id']} requires human activation approval")
        expected = (
            capability["version"],
            capability["artifact_digest"],
            capability["definition_digest"],
            evaluation["suite_digest"],
        )
        actual = (
            activation["version"],
            activation["artifact_digest"],
            activation["definition_digest"],
            activation["suite_digest"],
        )
        if actual != expected:
            raise CapabilityError(f"{capability['id']} activation approval is stale")


def _validate_dependencies(
    capabilities: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> None:
    for capability in capabilities:
        seen: set[str] = set()
        for requirement in capability["requires"]:
            dependency_id = requirement["id"]
            if dependency_id in seen:
                raise CapabilityError(
                    f"Duplicate dependency for {capability['id']}: {dependency_id}"
                )
            seen.add(dependency_id)
            dependency = by_id.get(dependency_id)
            if dependency is None:
                raise CapabilityError(f"Unknown dependency for {capability['id']}: {dependency_id}")
            if _semver(dependency["version"]) < _semver(requirement["minimum_version"]):
                raise CapabilityError(f"Dependency version is too old: {dependency_id}")
            if capability["status"] == "active" and dependency["status"] != "active":
                raise CapabilityError(
                    f"Active capability {capability['id']} requires inactive {dependency_id}"
                )


def _validate_cycles(by_id: dict[str, dict[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(capability_id: str) -> None:
        if capability_id in visiting:
            raise CapabilityError(f"Capability dependency cycle includes: {capability_id}")
        if capability_id in visited:
            return
        visiting.add(capability_id)
        for requirement in by_id[capability_id]["requires"]:
            visit(requirement["id"])
        visiting.remove(capability_id)
        visited.add(capability_id)

    for capability_id in by_id:
        visit(capability_id)


def _dependents(
    capabilities: list[dict[str, Any]], capability_id: str, *, active_only: bool
) -> list[str]:
    return sorted(
        capability["id"]
        for capability in capabilities
        if (not active_only or capability["status"] == "active")
        and any(item["id"] == capability_id for item in capability["requires"])
    )


def _contained_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise CapabilityError(f"Capability path escapes repository root: {relative}") from exc
    return target


def _atomic_write(path: Path, content: str) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _semver(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise CapabilityError(f"Invalid semantic version: {value}") from exc
    if len(parts) != 3:
        raise CapabilityError(f"Invalid semantic version: {value}")
    return parts  # type: ignore[return-value]


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CapabilityError(f"{field} must not be empty")
    return normalized


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
