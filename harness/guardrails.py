"""Trusted tool classification and pre-execution guardrails."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from harness.approvals import ApprovalError, ApprovalStore
from harness.policy import PolicyError, authorization_requirement
from harness.runtime import PreToolEvent

ACTION_ORDER = {
    "read_only": 0,
    "reversible_local_change": 1,
    "destructive_change": 2,
    "external_side_effect": 3,
    "permission_expansion": 4,
}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ACTION_RISK = {
    "read_only": "low",
    "reversible_local_change": "medium",
    "destructive_change": "high",
    "external_side_effect": "high",
    "permission_expansion": "critical",
}
FILESYSTEM_ACTION = {
    "none": "read_only",
    "read": "read_only",
    "write": "reversible_local_change",
    "destructive": "destructive_change",
}
RESERVED_ARGUMENT_KEYS = {
    "action_class",
    "actor",
    "approval",
    "approval_id",
    "explicit_approval",
    "requested_at",
    "risk_level",
    "run_id",
    "tool_call_id",
}
GLOB_CHARACTERS = frozenset("*?[]{}")
MISSING = object()


class GuardrailOutcome(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    PAUSE = "pause"


@dataclass(frozen=True)
class GuardrailDecision:
    outcome: GuardrailOutcome
    reason: str
    action_class: str | None
    risk_level: str | None
    requires_approval: bool
    untrusted_output: bool


@dataclass(frozen=True)
class ToolClassification:
    action_class: str
    risk_level: str
    requires_approval: bool
    untrusted_output: bool


class TrustedGuardrails:
    """Evaluate adapter-owned calls against trusted configuration and approvals."""

    def __init__(
        self,
        root: Path,
        tool_policies: dict[str, dict[str, Any]],
        policy: dict[str, Any],
        approvals: ApprovalStore,
    ) -> None:
        self._root = root.resolve()
        self._tools = tool_policies
        self._policy = policy
        self._approvals = approvals

    def evaluate(
        self, event: PreToolEvent, approval_id: str | None = None
    ) -> GuardrailDecision:
        tool = self._tools.get(event.tool_id)
        if tool is None:
            return _blocked(f"Tool is not in the trusted registry: {event.tool_id}")
        reserved = sorted(_find_reserved_keys(event.arguments))
        if reserved:
            return _blocked(
                f"Tool arguments contain reserved trust fields: {', '.join(reserved)}"
            )
        try:
            classification = self._classify(tool, event.arguments)
            self._validate_filesystem(tool, event.arguments)
            self._validate_shell(tool, event.arguments)
            sensitive = _find_sensitive_keys(
                event.arguments,
                set(self._policy.get("audit", {}).get("redact_keys", [])),
            )
            if tool["network"]["access"] == "outbound":
                self._validate_network(tool, event.arguments)
                if sensitive and tool["private_data_egress"] == "deny":
                    joined = ", ".join(sorted(sensitive))
                    raise PolicyError(f"Private-data egress is denied for keys: {joined}")
                if sensitive:
                    classification = ToolClassification(
                        action_class=classification.action_class,
                        risk_level=_maximum(RISK_ORDER, classification.risk_level, "critical"),
                        requires_approval=True,
                        untrusted_output=classification.untrusted_output,
                    )
        except (PolicyError, ValueError) as exc:
            return _blocked(str(exc))

        if approval_id is not None and not classification.requires_approval:
            return _blocked("Approval was supplied for a call that does not require it")
        if classification.requires_approval:
            if approval_id is None:
                return GuardrailDecision(
                    GuardrailOutcome.PAUSE,
                    "Exact approval is required",
                    classification.action_class,
                    classification.risk_level,
                    True,
                    classification.untrusted_output,
                )
            try:
                self._approvals.consume(event, approval_id)
            except ApprovalError as exc:
                return _blocked(str(exc), classification)

        return GuardrailDecision(
            GuardrailOutcome.ALLOW,
            "Trusted guardrail checks passed",
            classification.action_class,
            classification.risk_level,
            classification.requires_approval,
            classification.untrusted_output,
        )

    def normalize_arguments(
        self, tool_id: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Canonicalize execution arguments before the adapter creates trusted events."""
        try:
            normalized = json.loads(json.dumps(arguments, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise PolicyError("Tool arguments must contain strict JSON values") from exc
        tool = self._tools.get(tool_id)
        if tool is None:
            return normalized
        for field in tool["filesystem"]["path_arguments"]:
            value = _field_value(normalized, field)
            if isinstance(value, str) and value.strip() and not value.strip().startswith("~"):
                candidate = Path(value.strip())
                if not candidate.is_absolute():
                    candidate = self._root / candidate
                _set_field(normalized, field, str(candidate.resolve(strict=False)))
        for field in tool["network"]["host_arguments"]:
            value = _field_value(normalized, field)
            if isinstance(value, str) and value.strip():
                try:
                    _set_field(normalized, field, _normalize_host(value))
                except PolicyError:
                    pass
        return normalized

    def _classify(
        self, tool: dict[str, Any], arguments: dict[str, Any]
    ) -> ToolClassification:
        action_class = _maximum(
            ACTION_ORDER,
            tool["action_class"],
            FILESYSTEM_ACTION[tool["filesystem"]["access"]],
        )
        if tool["network"]["access"] == "outbound":
            action_class = _maximum(
                ACTION_ORDER, action_class, "external_side_effect"
            )
        if tool["shell"]["access"] == "execute":
            action_class = _maximum(
                ACTION_ORDER, action_class, "permission_expansion"
            )
        risk_level = tool["risk_level"]
        approval = tool["approval"] == "always"
        for rule in tool["argument_rules"]:
            value = _field_value(arguments, rule["field"])
            if value is not MISSING and value == rule["equals"]:
                action_class = _maximum(
                    ACTION_ORDER, action_class, rule["action_class"]
                )
                risk_level = _maximum(
                    RISK_ORDER, risk_level, rule["risk_level"]
                )
                approval = approval or rule["approval"] == "always"
        risk_level = _maximum(RISK_ORDER, risk_level, ACTION_RISK[action_class])
        requirement = authorization_requirement(self._policy, action_class)
        approval = approval or requirement == "explicit_approval"
        return ToolClassification(
            action_class=action_class,
            risk_level=risk_level,
            requires_approval=approval,
            untrusted_output=bool(tool["untrusted_output"]),
        )

    def _validate_filesystem(
        self, tool: dict[str, Any], arguments: dict[str, Any]
    ) -> None:
        filesystem = tool["filesystem"]
        if filesystem["access"] == "none":
            return
        root_key = "read_roots" if filesystem["access"] == "read" else "write_roots"
        allowed = _configured_roots(
            self._root, self._policy.get("scope", {}).get(root_key, [])
        )
        denied = _configured_roots(
            self._root, self._policy.get("scope", {}).get("denied_roots", [])
        )
        if not allowed:
            raise PolicyError(f"Filesystem access has no configured {root_key}")
        for field in filesystem["path_arguments"]:
            value = _field_value(arguments, field)
            if not isinstance(value, str) or not value.strip():
                raise PolicyError(f"Path argument must be a non-empty string: {field}")
            raw = value.strip()
            if raw.startswith("~"):
                raise PolicyError(f"Home-relative paths are not allowed: {field}")
            if filesystem["require_exact_targets"]:
                if any(character in raw for character in GLOB_CHARACTERS):
                    raise PolicyError(f"Destructive target must not contain patterns: {field}")
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = self._root / candidate
            target = candidate.resolve(strict=False)
            if not any(_contains(root, target) for root in allowed):
                raise PolicyError(f"Path escapes configured allowed roots: {field}")
            if any(_contains(root, target) for root in denied):
                raise PolicyError(f"Path enters a configured denied root: {field}")
            if filesystem["require_exact_targets"] and target in allowed:
                raise PolicyError("Destructive target must not be an allowed root itself")

    @staticmethod
    def _validate_network(tool: dict[str, Any], arguments: dict[str, Any]) -> None:
        network = tool["network"]
        allowed = {_normalize_host(value) for value in network["allowed_hosts"]}
        for field in network["host_arguments"]:
            value = _field_value(arguments, field)
            if not isinstance(value, str) or not value.strip():
                raise PolicyError(f"Network host must be a non-empty string: {field}")
            host = _normalize_host(value)
            if host not in allowed:
                raise PolicyError(f"Network host is outside the trusted allowlist: {host}")

    def _validate_shell(self, tool: dict[str, Any], arguments: dict[str, Any]) -> None:
        shell = tool["shell"]
        if shell["access"] == "none":
            return
        denied_patterns = self._policy.get("safety", {}).get("deny_shell_patterns", [])
        if not isinstance(denied_patterns, list):
            raise PolicyError("Denied shell patterns must be a list")
        for field in shell["command_arguments"]:
            value = _field_value(arguments, field)
            if not isinstance(value, str) or not value.strip():
                raise PolicyError(f"Shell command must be a non-empty string: {field}")
            command = value.lower()
            for pattern in denied_patterns:
                if not isinstance(pattern, str) or not pattern:
                    raise PolicyError("Denied shell patterns must be non-empty strings")
                if pattern.lower() in command:
                    raise PolicyError(f"Shell command matches denied pattern: {pattern}")


def _blocked(
    reason: str, classification: ToolClassification | None = None
) -> GuardrailDecision:
    return GuardrailDecision(
        GuardrailOutcome.BLOCK,
        reason,
        classification.action_class if classification else None,
        classification.risk_level if classification else None,
        classification.requires_approval if classification else False,
        classification.untrusted_output if classification else False,
    )


def _maximum(order: dict[str, int], left: str, right: str) -> str:
    try:
        return left if order[left] >= order[right] else right
    except KeyError as exc:
        raise PolicyError(f"Unknown trusted classification: {exc.args[0]}") from exc


def _field_value(arguments: dict[str, Any], field: str) -> Any:
    value: Any = arguments
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def _set_field(arguments: dict[str, Any], field: str, replacement: Any) -> None:
    target: Any = arguments
    parts = field.split(".")
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            return
        target = target[part]
    if isinstance(target, dict) and parts[-1] in target:
        target[parts[-1]] = replacement


def _configured_roots(root: Path, values: Any) -> tuple[Path, ...]:
    if not isinstance(values, list):
        raise PolicyError("Configured filesystem roots must be a list")
    resolved: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise PolicyError("Configured filesystem roots must be non-empty strings")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved.append(candidate.resolve(strict=False))
    return tuple(resolved)


def _contains(root: Path, target: Path) -> bool:
    return target == root or root in target.parents


def _normalize_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if not host or any(character in host for character in "/:@"):
        raise PolicyError(f"Network host must be a hostname without scheme or port: {value}")
    labels = host.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise PolicyError(f"Network host is malformed: {value}")
    return host


def _find_reserved_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in RESERVED_ARGUMENT_KEYS:
                found.add(str(key))
            found.update(_find_reserved_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_find_reserved_keys(nested))
    return found


def _find_sensitive_keys(value: Any, sensitive_keys: set[str]) -> set[str]:
    normalized = {str(key).lower() for key in sensitive_keys}
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in normalized:
                found.add(str(key))
            found.update(_find_sensitive_keys(nested, normalized))
    elif isinstance(value, list):
        for nested in value:
            found.update(_find_sensitive_keys(nested, normalized))
    return found
