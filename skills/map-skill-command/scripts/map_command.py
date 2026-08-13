#!/usr/bin/env python3
"""Map a project-level command name to an installed harness skill."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml


SKILL_ROOTS = {
    "portable": Path(".agents/skills"),
    "codex": Path(".agents/skills"),
    "claude-code": Path(".claude/skills"),
    "antigravity": Path(".agents/skills"),
}
BUILT_IN_COMMANDS = {
    "add-dir",
    "clear",
    "compact",
    "config",
    "context",
    "doctor",
    "exit",
    "feedback",
    "goal",
    "help",
    "init",
    "login",
    "logout",
    "mcp",
    "model",
    "permissions",
    "plan",
    "review",
    "status",
}
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CommandError(ValueError):
    """Raised when a command mapping is invalid or unsafe."""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd(), help="generated harness root")
    result.add_argument("--command", required=True, help="slash command name, with or without /")
    result.add_argument("--skill", required=True, help="installed target skill ID")
    result.add_argument("--description", required=True, help="short purpose shown in command lists")
    return result


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CommandError(f"Cannot load {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CommandError(f"{path} must contain a mapping")
    return payload


def command_name(value: str) -> str:
    command = value.strip().removeprefix("/")
    if not NAME.fullmatch(command) or len(command) > 64:
        raise CommandError("Command must use 1-64 lowercase letters, digits, and single hyphens")
    if command in BUILT_IN_COMMANDS or command.startswith("prompts-"):
        raise CommandError(f"Refusing to shadow built-in command: /{command}")
    return command


def resolve_mapping(
    root: Path, command: str, target_id: str
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    receipt_path = root / ".agent-harness" / "installation.yaml"
    registry_path = root / "config" / "capabilities.yaml"
    receipt = load_yaml(receipt_path)
    registry = load_yaml(registry_path)
    host = str(receipt.get("host", ""))
    if host not in SKILL_ROOTS:
        raise CommandError(f"Unsupported harness host: {host or '<missing>'}")
    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(capability, dict) for capability in capabilities
    ):
        raise CommandError("config/capabilities.yaml capabilities must be a list of mappings")
    by_id = {str(capability.get("id")): capability for capability in capabilities}
    if command in by_id:
        raise CommandError(f"Capability or command already exists: {command}")
    target = by_id.get(target_id)
    if target is None or target.get("type") != "skill":
        raise CommandError(f"Target is not an installed skill: {target_id}")
    if command == target_id:
        raise CommandError("Command alias must differ from its target skill")
    skill_root = root / SKILL_ROOTS[host]
    target_path = (root / str(target.get("path", ""))).resolve()
    resolved_skill_root = skill_root.resolve()
    if target_path.parent != resolved_skill_root:
        raise CommandError(f"Target skill is outside the native skill directory: {target_path}")
    if not (target_path / "SKILL.md").is_file():
        raise CommandError(f"Target skill is missing its SKILL.md: {target_path}")
    alias_path = skill_root / command
    if alias_path.exists():
        raise CommandError(f"Command path already exists: {alias_path}")
    return registry_path, alias_path, registry, target


def write_alias(root: Path, command: str, target_id: str, description: str) -> tuple[Path, Path]:
    summary = " ".join(description.split())
    if not summary or len(summary) > 200:
        raise CommandError("Description must contain 1-200 characters")
    registry_path, alias_path, registry, target = resolve_mapping(root, command, target_id)
    alias_path.mkdir(parents=True)
    try:
        body = (
            "---\n"
            f"name: {command}\n"
            f"description: {json.dumps(summary)}\n"
            "---\n\n"
            f"# /{command}\n\n"
            f"Load and follow the installed `{target_id}` skill at `../{target_id}/SKILL.md`. "
            "Treat all text supplied with this command as the user's task arguments. Preserve "
            "the target skill's workflow, approval requirements, and validation steps. This "
            "alias grants no additional authority.\n"
        )
        (alias_path / "SKILL.md").write_text(body, encoding="utf-8")
        host = str(load_yaml(root / ".agent-harness" / "installation.yaml")["host"])
        if host in {"portable", "codex"}:
            agents = alias_path / "agents"
            agents.mkdir()
            metadata = {
                "interface": {
                    "display_name": f"/{command}",
                    "short_description": summary[:64],
                    "default_prompt": f"Use ${command} to run ${target_id} for this request.",
                }
            }
            (agents / "openai.yaml").write_text(
                yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
            )
        relative = alias_path.relative_to(root).as_posix()
        registry["capabilities"].append(
            {
                "id": command,
                "type": "skill",
                "status": "active",
                "path": relative,
                "description": summary,
                "when": f"Use when the user invokes /{command} or explicitly requests this alias.",
            }
        )
        registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    except Exception:
        shutil.rmtree(alias_path, ignore_errors=True)
        raise
    return alias_path, Path(str(target["path"]))


def main() -> int:
    args = parser().parse_args()
    root = args.root.expanduser().resolve()
    try:
        command = command_name(args.command)
        alias_path, target_path = write_alias(root, command, args.skill, args.description)
    except CommandError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(f"Created /{command}: {alias_path.relative_to(root)}")
    print(f"Target skill: {target_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
