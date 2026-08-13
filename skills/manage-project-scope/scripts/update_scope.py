#!/usr/bin/env python3
"""Safely add one project directory to a generated harness policy scope."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ScopeError(ValueError):
    """Raised when a scope update would be invalid or dangerously broad."""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd(), help="generated harness root")
    result.add_argument("--path", type=Path, required=True, help="existing project directory")
    result.add_argument(
        "--access",
        choices=("read", "read-write"),
        required=True,
        help="portable policy access to grant",
    )
    return result


def load_policy(root: Path) -> tuple[Path, dict[str, Any]]:
    policy_path = root / "config" / "policies.yaml"
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScopeError(f"Cannot load {policy_path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("scope"), dict):
        raise ScopeError("Policy must contain a scope object")
    scope = payload["scope"]
    expected = {"allowed_read_paths", "allowed_write_paths", "denied_paths"}
    if set(scope) != expected:
        raise ScopeError("Policy scope has missing or unknown fields")
    for key in expected:
        if not isinstance(scope[key], list) or not all(
            isinstance(value, str) and value for value in scope[key]
        ):
            raise ScopeError(f"Policy scope.{key} must be a list of non-empty strings")
    return policy_path, payload


def resolve_project(root: Path, requested: Path) -> Path:
    project = requested.expanduser()
    if not project.is_absolute():
        project = root / project
    project = project.resolve()
    if not project.is_dir():
        raise ScopeError(f"Project folder does not exist or is not a directory: {project}")
    home = Path.home().resolve()
    if project == Path(project.anchor) or project == home or project in root.parents:
        raise ScopeError(f"Refusing dangerously broad project scope: {project}")
    if project == root:
        raise ScopeError("The harness root is already covered by the default '.' scope")
    return project


def is_covered(candidate: Path, configured: list[str], root: Path) -> bool:
    for value in configured:
        parent = Path(value).expanduser()
        if not parent.is_absolute():
            parent = root / parent
        parent = parent.resolve()
        if candidate == parent or parent in candidate.parents:
            return True
    return False


def add_project_scope(root: Path, project: Path, access: str) -> tuple[dict[str, Any], list[str]]:
    policy_path, payload = load_policy(root)
    scope = payload["scope"]
    denied_names = {
        pattern.removeprefix("./").removesuffix("/**").rstrip("*")
        for pattern in scope["denied_paths"]
    }
    if any(name and name in project.parts for name in denied_names):
        raise ScopeError(f"Project folder intersects a denied path: {project}")
    changed: list[str] = []
    additions = ["allowed_read_paths"]
    if access == "read-write":
        additions.append("allowed_write_paths")
    for key in additions:
        if not is_covered(project, scope[key], root):
            scope[key].append(str(project))
            changed.append(key)

    if changed:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".policies-", suffix=".json", dir=policy_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.write("\n")
            temporary.chmod(policy_path.stat().st_mode)
            os.replace(temporary, policy_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return payload, changed


def main() -> int:
    args = parser().parse_args()
    root = args.root.expanduser().resolve()
    try:
        project = resolve_project(root, args.path)
        payload, changed = add_project_scope(root, project, args.access)
    except ScopeError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    status = "Updated" if changed else "Already covered"
    print(f"{status}: {project}")
    print("Read scope:", ", ".join(payload["scope"]["allowed_read_paths"]))
    print("Write scope:", ", ".join(payload["scope"]["allowed_write_paths"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
