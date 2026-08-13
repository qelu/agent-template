#!/usr/bin/env python3
"""Validate one generated host-native agent harness."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.guardrails.core import load_policy  # noqa: E402

HOST_FILES = {
    "codex": ("AGENTS.md", ".codex/config.toml", ".codex/hooks.json"),
    "claude-code": ("CLAUDE.md", ".claude/settings.json"),
    "antigravity": ("AGENTS.md", "GEMINI.md", ".agents/hooks.json"),
    "portable": ("AGENTS.md",),
}
SKILL_ROOTS = {
    "codex": ".agents/skills",
    "claude-code": ".claude/skills",
    "antigravity": ".agents/skills",
    "portable": ".agents/skills",
}
PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
CAPABILITY_FIELDS = {"id", "type", "status", "path", "description", "when"}
CAPABILITY_STATUSES = {"active", "experimental", "disabled"}


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a mapping")
    return payload


def _validate_json(path: Path, errors: list[str]) -> None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Invalid JSON in {path.relative_to(ROOT)}: {exc}")


def _validate_host_guardrails(host: str, errors: list[str]) -> None:
    try:
        if host == "codex":
            config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
            if config.get("approval_policy") != "on-request":
                errors.append("Codex approval_policy must be on-request")
            if config.get("sandbox_mode") != "read-only":
                errors.append("Codex sandbox_mode must be read-only")
            hooks = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))
            if not {"UserPromptSubmit", "PreToolUse"}.issubset(hooks.get("hooks", {})):
                errors.append("Codex guardrail hooks are incomplete")
        elif host == "claude-code":
            settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
            permissions = settings.get("permissions", {})
            if permissions.get("defaultMode") != "default":
                errors.append("Claude Code permission mode must default to default")
            if permissions.get("disableBypassPermissionsMode") != "disable":
                errors.append("Claude Code bypass-permissions mode must be disabled")
            if not {"UserPromptSubmit", "PreToolUse"}.issubset(settings.get("hooks", {})):
                errors.append("Claude Code guardrail hooks are incomplete")
        elif host == "antigravity":
            hooks = json.loads((ROOT / ".agents/hooks.json").read_text(encoding="utf-8"))
            guardrails = hooks.get("agent-harness-guardrails", {})
            if not {"PreInvocation", "PreToolUse"}.issubset(guardrails):
                errors.append("Antigravity guardrail hooks are incomplete")
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"Invalid {host} guardrail configuration: {exc}")


def main() -> int:
    errors: list[str] = []
    receipt_path = ROOT / ".agent-harness" / "installation.yaml"
    required = (
        "agent/AGENT.md",
        "config/persona.yaml",
        "config/policies.yaml",
        "config/capabilities.yaml",
        "scripts/guardrails/core.py",
        "scripts/guardrails/codex.py",
        "scripts/guardrails/claude_code.py",
        "scripts/guardrails/antigravity.py",
    )
    for relative in required:
        if not (ROOT / relative).is_file():
            errors.append(f"Missing required file: {relative}")

    try:
        load_policy(ROOT)
    except (OSError, ValueError) as exc:
        errors.append(f"Invalid portable policy: {exc}")

    try:
        receipt = _load_yaml(receipt_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(f"Invalid installation receipt: {exc}")
        receipt = {}
    template = receipt.get("template")
    if not isinstance(template, dict) or not all(
        isinstance(template.get(field), str) and template.get(field)
        for field in ("repository", "revision")
    ):
        errors.append("Installation receipt requires template repository and revision")
    skill_imports = receipt.get("skill_imports")
    if not isinstance(skill_imports, list):
        errors.append("Installation receipt skill_imports must be a list")
    else:
        for item in skill_imports:
            if not isinstance(item, dict) or set(item) != {
                "skill",
                "imported_at",
                "source",
                "audit_verdict",
            }:
                errors.append("Installation receipt contains an invalid skill import entry")
                continue
            if item.get("audit_verdict") not in {"pass", "pass-with-warnings"}:
                errors.append("Imported skill receipt has an invalid audit verdict")
            if not isinstance(item.get("source"), dict):
                errors.append("Imported skill receipt source must be a mapping")
    host = str(receipt.get("host", ""))
    if host not in HOST_FILES:
        errors.append(f"Unsupported receipt host: {host or '<missing>'}")
    else:
        for relative in HOST_FILES[host]:
            if not (ROOT / relative).is_file():
                errors.append(f"Missing {host} project file: {relative}")
        _validate_host_guardrails(host, errors)

    for path in ROOT.rglob("*.json"):
        if ".venv" not in path.parts and ".agent-harness" not in path.parts:
            _validate_json(path, errors)

    try:
        capabilities = _load_yaml(ROOT / "config" / "capabilities.yaml").get("capabilities", [])
        if not isinstance(capabilities, list):
            raise ValueError("config/capabilities.yaml capabilities must be a list")
        skill_root = ROOT / SKILL_ROOTS.get(host, ".agents/skills")
        for capability in capabilities:
            if not isinstance(capability, dict):
                errors.append("Capability entries must be mappings")
                continue
            if set(capability) != CAPABILITY_FIELDS:
                errors.append(
                    "Capability entry has invalid fields: "
                    + str(sorted(set(capability) ^ CAPABILITY_FIELDS))
                )
                continue
            if capability["status"] not in CAPABILITY_STATUSES:
                errors.append(f"Invalid capability status: {capability['status']}")
            if not all(
                isinstance(capability[field], str) and capability[field].strip()
                for field in CAPABILITY_FIELDS
            ):
                errors.append(f"Capability {capability.get('id')} has empty or invalid fields")
            if capability.get("type") == "skill":
                skill = skill_root / str(capability.get("id", "")) / "SKILL.md"
                if not skill.is_file():
                    errors.append(f"Missing selected skill: {skill.relative_to(ROOT)}")
            capability_path = ROOT / str(capability.get("path", ""))
            if not capability_path.exists():
                errors.append(
                    f"Missing selected capability artifact: {capability_path.relative_to(ROOT)}"
                )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(str(exc))

    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".git", ".venv"} for part in path.parts):
            continue
        if path.suffix not in {".md", ".yaml", ".yml", ".json", ".toml", ".py"}:
            continue
        try:
            if PLACEHOLDER.search(path.read_text(encoding="utf-8")):
                errors.append(f"Unresolved placeholder: {path.relative_to(ROOT)}")
        except UnicodeDecodeError:
            pass

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Host-native harness validation passed for {host}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
