"""Shared deterministic policy evaluation for host-native hook bridges."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


ACTIONS = {"read", "write", "delete", "external_side_effect", "unknown"}
DECISIONS = {"allow", "ask", "deny"}
TOP_LEVEL_KEYS = {"version", "actions", "scope", "shell", "audit"}
SCOPE_KEYS = {"allowed_read_paths", "allowed_write_paths", "denied_paths"}
SHELL_KEYS = {"denied_patterns"}
AUDIT_KEYS = {"enabled"}

READ_TOOLS = {
    "cat",
    "find_by_name",
    "glob",
    "grep",
    "grep_search",
    "list_dir",
    "list_directory",
    "list_files",
    "read",
    "read_file",
    "read_url_content",
    "search_web",
    "view_file",
    "view_image",
    "webfetch",
    "websearch",
}
WRITE_TOOLS = {
    "apply_patch",
    "create_file",
    "edit",
    "edit_file",
    "multiedit",
    "notebookedit",
    "replace_file_content",
    "replace_file_contents",
    "write",
    "write_file",
}
SHELL_TOOLS = {"bash", "exec", "exec_command", "run_command", "shell", "terminal"}
EXTERNAL_TOOLS = {"send_message", "publish", "deploy", "create_pull_request"}
PATH_KEY_MARKERS = (
    "path",
    "file",
    "target",
    "directory",
    "cwd",
    "root",
    "source",
    "destination",
)
DELETE_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:rm\b|rmdir\b|unlink\b|shred\b|"
    r"git\s+rm\b|find\b[^\n;&|]*\s-delete\b|remove-item\b|"
    r"del\s+[/\-a-z]*\s*[^;&|]+|erase\b)",
    re.IGNORECASE,
)
DELETE_API = re.compile(
    r"(?:os\.(?:remove|unlink)\s*\(|shutil\.rmtree\s*\(|"
    r"pathlib[^\n]*(?:unlink|rmdir)\s*\(|fs\.(?:rm|unlink|rmdir)\s*\(|"
    r"File\.(?:delete|deleteIfExists)\s*\()",
    re.IGNORECASE,
)
EXTERNAL_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:git\s+push\b|gh\s+pr\s+create\b|"
    r"(?:curl|wget)\b[^\n]*(?:--request|-X)\s*(?:POST|PUT|PATCH|DELETE)\b)",
    re.IGNORECASE,
)
WRITE_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:mkdir|touch|cp|mv|chmod|chown|tee|"
    r"git\s+(?:add|commit|merge|rebase|checkout|switch|restore)|"
    r"(?:npm|pnpm|yarn|pip|uv)\s+(?:install|add|remove|sync))\b|(?:^|[^<])>{1,2}",
    re.IGNORECASE,
)
READ_COMMANDS = {
    "cat",
    "command",
    "cut",
    "file",
    "find",
    "git",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "sed",
    "stat",
    "tail",
    "wc",
    "which",
}
READ_ONLY_GIT_SUBCOMMANDS = {"branch", "diff", "log", "rev-parse", "show", "status"}


@dataclass(frozen=True)
class HookEvent:
    host: str
    event: str
    run_id: str
    turn_id: str | None
    tool_name: str | None
    tool_input: dict[str, Any]
    prompt: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    outcome: str
    reason: str


def load_policy(root: Path) -> dict[str, Any]:
    """Load and strictly validate the policy used by the runtime hooks."""
    path = root / "config" / "policies.yaml"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON-compatible YAML policy: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("policy must be an object")
    _exact_keys(payload, TOP_LEVEL_KEYS, "policy")
    if payload["version"] != "1.0":
        raise ValueError("policy.version must be '1.0'")

    actions = _mapping(payload["actions"], "policy.actions")
    _exact_keys(actions, ACTIONS, "policy.actions")
    for action, decision in actions.items():
        if decision not in DECISIONS:
            raise ValueError(f"policy.actions.{action} must be allow, ask, or deny")
    if actions["delete"] != "deny":
        raise ValueError("policy.actions.delete must be deny")

    scope = _mapping(payload["scope"], "policy.scope")
    _exact_keys(scope, SCOPE_KEYS, "policy.scope")
    for key in SCOPE_KEYS:
        _string_list(scope[key], f"policy.scope.{key}", require_nonempty=key != "denied_paths")

    shell = _mapping(payload["shell"], "policy.shell")
    _exact_keys(shell, SHELL_KEYS, "policy.shell")
    _string_list(shell["denied_patterns"], "policy.shell.denied_patterns")

    audit = _mapping(payload["audit"], "policy.audit")
    _exact_keys(audit, AUDIT_KEYS, "policy.audit")
    if not isinstance(audit["enabled"], bool):
        raise ValueError("policy.audit.enabled must be a boolean")
    return payload


def evaluate_policy(event: HookEvent, policy: dict[str, Any], root: Path) -> PolicyDecision:
    command = _command(event.tool_input)
    configured_denials = policy["shell"]["denied_patterns"]
    if command and any(pattern.lower() in command.lower() for pattern in configured_denials):
        return PolicyDecision("delete", "deny", "Blocked by a configured shell denial.")

    action = classify_action(event.tool_name, event.tool_input)
    if action == "delete":
        return PolicyDecision(action, "deny", "Deletion is prohibited by project policy.")

    paths = _path_values(event.tool_input)
    paths.extend(_patch_paths(event.tool_input))
    if command:
        paths.extend(_command_paths(command))
    denied_reference = _denied_command_reference(command, policy["scope"]["denied_paths"])
    if denied_reference:
        return PolicyDecision(action, "deny", "Access to a denied path is prohibited.")
    path_reason = _path_denial(action, paths, policy["scope"], root)
    if path_reason:
        return PolicyDecision(action, "deny", path_reason)

    outcome = str(policy["actions"][action])
    reasons = {
        "allow": "Allowed by the portable project policy.",
        "ask": "Requires confirmation through the host's native permission flow.",
        "deny": "Blocked by the portable project policy.",
    }
    return PolicyDecision(action, outcome, reasons[outcome])


def classify_action(tool_name: str | None, tool_input: dict[str, Any]) -> str:
    name = _normalized_tool_name(tool_name)
    if _contains_delete_directive(tool_input):
        return "delete"
    if any(marker in name for marker in ("delete", "remove", "unlink", "trash")):
        return "delete"
    if name in READ_TOOLS:
        return "read"
    if name in WRITE_TOOLS or any(marker in name for marker in ("edit", "write", "patch")):
        return "write"
    if name in EXTERNAL_TOOLS:
        return "external_side_effect"
    command = _command(tool_input)
    if name in SHELL_TOOLS or command is not None:
        return _classify_command(command or "")
    return "unknown"


def plan_context(run_id: str) -> str:
    return (
        f"Harness run ID: {run_id}. "
        "Approvals are scoped to the exact plan or action explicitly presented. "
        "A new state-changing request requires a fresh plan when the planning rules apply; "
        "approval of an earlier plan never authorizes later requests. Native tool approvals "
        "remain separate from plan approval."
    )


def audit_event(
    root: Path,
    event: HookEvent,
    decision: PolicyDecision,
    policy: dict[str, Any],
) -> None:
    if not policy["audit"]["enabled"]:
        return
    directory = root / ".agent-harness" / "audit"
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": event.host,
        "run_id": event.run_id,
        "turn_id": event.turn_id,
        "event": event.event,
        "tool_name": event.tool_name,
        "action": decision.action,
        "input_digest": _digest(event.tool_input),
        "prompt_digest": _digest(event.prompt) if event.prompt is not None else None,
        "outcome": decision.outcome,
    }
    path = directory / f"{_safe_run_id(event.run_id)}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def read_payload() -> dict[str, Any]:
    import sys

    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    return payload


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def _classify_command(command: str) -> str:
    if DELETE_COMMAND.search(command) or DELETE_API.search(command):
        return "delete"
    if EXTERNAL_COMMAND.search(command):
        return "external_side_effect"
    if WRITE_COMMAND.search(command):
        return "write"
    try:
        parts = shlex.split(command)
    except ValueError:
        return "unknown"
    if not parts:
        return "unknown"
    executable = Path(parts[0]).name.lower()
    if executable not in READ_COMMANDS:
        return "unknown"
    if executable == "git" and (
        len(parts) < 2 or parts[1].lower() not in READ_ONLY_GIT_SUBCOMMANDS
    ):
        return "unknown"
    if executable == "sed" and any(value.startswith("-i") for value in parts[1:]):
        return "write"
    if executable == "find" and "-delete" in parts:
        return "delete"
    return "read"


def _path_denial(action: str, values: list[str], scope: dict[str, Any], root: Path) -> str | None:
    if action not in {"read", "write"}:
        return None
    allowed_key = "allowed_read_paths" if action == "read" else "allowed_write_paths"
    for value in values:
        candidate = _filesystem_path(value, root)
        if candidate is None:
            continue
        relative = _relative(candidate, root)
        denial_target = relative if relative is not None else candidate.as_posix()
        if _matches_any(denial_target, scope["denied_paths"]):
            return "Access to a denied path is prohibited."
        allowed = [_filesystem_path(item, root) for item in scope[allowed_key]]
        if not any(parent is not None and _is_within(candidate, parent) for parent in allowed):
            return f"{action.title()} path is outside policy scope."
    return None


def _filesystem_path(value: str, root: Path) -> Path | None:
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != "file":
        return None
    raw = unquote(parsed.path) if parsed.scheme == "file" else value
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _relative(path: Path, root: Path) -> str | None:
    try:
        value = path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    return value or "."


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _matches_any(relative: str, patterns: list[str]) -> bool:
    parts = Path(relative).parts
    for pattern in patterns:
        normalized = pattern.removeprefix("./")
        if fnmatch.fnmatch(relative, normalized) or fnmatch.fnmatch(
            Path(relative).name, normalized
        ):
            return True
        base = normalized.removesuffix("/**")
        if base in parts:
            return True
    return False


def _denied_command_reference(command: str | None, patterns: list[str]) -> bool:
    if not command:
        return False
    for pattern in patterns:
        marker = pattern.removeprefix("./").removesuffix("/**").rstrip("*")
        if marker and re.search(
            rf"(?:^|[/\\\s'\"~]){re.escape(marker)}(?:$|[/\\\s'\".*])", command
        ):
            return True
    return False


def _command(tool_input: dict[str, Any]) -> str | None:
    for key in ("command", "CommandLine"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def _path_values(value: object, key: str = "") -> list[str]:
    if isinstance(value, str):
        return [value] if any(marker in key.lower() for marker in PATH_KEY_MARKERS) else []
    if isinstance(value, dict):
        result: list[str] = []
        for child_key, child in value.items():
            result.extend(_path_values(child, str(child_key)))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_path_values(child, key))
        return result
    return []


def _command_paths(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError:
        return []
    values: list[str] = []
    for value in parts[1:]:
        candidate = value.split("=", 1)[-1] if value.startswith("of=") else value
        if candidate.startswith(("/", "./", "../", "~/", "file://")):
            values.append(candidate)
    return values


def _contains_delete_directive(value: object) -> bool:
    if isinstance(value, str):
        return "*** Delete File:" in value
    if isinstance(value, dict):
        return any(_contains_delete_directive(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_delete_directive(child) for child in value)
    return False


def _patch_paths(value: object) -> list[str]:
    if isinstance(value, str):
        return re.findall(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$", value, re.MULTILINE)
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(_patch_paths(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_patch_paths(child))
        return result
    return []


def _normalized_tool_name(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ValueError(f"{label} has invalid fields: {'; '.join(details)}")


def _string_list(value: object, label: str, *, require_nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if require_nonempty and not value:
        raise ValueError(f"{label} must not be empty")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicates")
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_run_id(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return candidate[:120] or "unknown"
