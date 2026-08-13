#!/usr/bin/env python3
"""Import genuinely new skills from a stable tagged agent-template release."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


DEFAULT_REPOSITORY = "https://github.com/qelu/agent-template.git"
STABLE_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
HOST_SKILL_ROOTS = {
    "portable": Path(".agents/skills"),
    "codex": Path(".agents/skills"),
    "claude-code": Path(".claude/skills"),
    "antigravity": Path(".agents/skills"),
}


class TemplateImportFailure(ValueError):
    """Raised when a tagged template release cannot be imported safely."""


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TemplateImportFailure(f"Required command is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise TemplateImportFailure(f"Command failed: {' '.join(command)}: {detail}") from exc


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TemplateImportFailure(f"{path} must contain a mapping")
    return payload


def stable_tags(repository: str) -> list[str]:
    output = _run(["git", "ls-remote", "--tags", "--refs", repository]).stdout
    tags: list[tuple[tuple[int, int, int], str]] = []
    for line in output.splitlines():
        _, _, reference = line.partition("\t")
        tag = reference.removeprefix("refs/tags/")
        match = STABLE_TAG.fullmatch(tag)
        if match:
            tags.append((tuple(int(value) for value in match.groups()), tag))
    return [tag for _, tag in sorted(tags, reverse=True)]


def resolve_release(repository: str, requested: str) -> str:
    tags = stable_tags(repository)
    if requested == "latest":
        if not tags:
            raise TemplateImportFailure("Repository has no stable semantic-version tags")
        return tags[0]
    if not STABLE_TAG.fullmatch(requested):
        raise TemplateImportFailure("Release must be a stable semantic-version tag such as v1.2.3")
    if requested not in tags:
        raise TemplateImportFailure(f"Tagged release does not exist: {requested}")
    return requested


def _registered_helper(root: Path, registry: dict[str, Any], skill_id: str, script: str) -> Path:
    for item in registry.get("capabilities", []):
        if isinstance(item, dict) and item.get("id") == skill_id:
            helper = root / str(item.get("path")) / "scripts" / script
            if helper.is_file():
                return helper
    raise TemplateImportFailure(f"Required helper is not installed: {skill_id}")


def import_release(
    root: Path, repository: str | None, release: str, *, check: bool
) -> dict[str, Any]:
    root = root.resolve()
    local_registry = _load_yaml(root / "config" / "capabilities.yaml")
    receipt = _load_yaml(root / ".agent-harness" / "installation.yaml")
    template = receipt.get("template")
    recorded_repository = template.get("repository") if isinstance(template, dict) else None
    repository = repository or (
        recorded_repository if isinstance(recorded_repository, str) else DEFAULT_REPOSITORY
    )
    host = str(receipt.get("host", ""))
    if host not in HOST_SKILL_ROOTS:
        raise TemplateImportFailure(f"Unsupported harness host: {host}")
    tag = resolve_release(repository, release)
    local_ids = {
        str(item.get("id"))
        for item in local_registry.get("capabilities", [])
        if isinstance(item, dict)
    }
    skill_root = root / HOST_SKILL_ROOTS[host]
    importer = _registered_helper(root, local_registry, "import-external-skill", "import_skill.py")
    report: dict[str, Any] = {
        "repository": repository,
        "release": tag,
        "commit": "",
        "new": [],
        "imported": [],
        "preserved": [],
        "rejected": [],
    }
    with tempfile.TemporaryDirectory(prefix="template-skill-import-") as temporary:
        checkout = Path(temporary) / "template"
        _run(["git", "clone", "-q", "--depth", "1", "--branch", tag, repository, str(checkout)])
        report["commit"] = _run(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()
        upstream = _load_yaml(checkout / "config" / "capabilities.yaml")
        candidates = [
            item
            for item in upstream.get("capabilities", [])
            if isinstance(item, dict)
            and item.get("type") == "skill"
            and item.get("status") == "active"
        ]
        for item in candidates:
            skill_id = str(item.get("id"))
            destination = skill_root / skill_id
            if skill_id in local_ids or destination.exists():
                report["preserved"].append(skill_id)
                continue
            source = checkout / str(item.get("path"))
            if not (source / "SKILL.md").is_file():
                report["rejected"].append(
                    {"skill": skill_id, "reason": "upstream artifact missing"}
                )
                continue
            report["new"].append(skill_id)
            if check:
                continue
            command = [
                sys.executable,
                str(importer),
                "--root",
                str(root),
                "--source",
                str(source),
                "--skill",
                skill_id,
                "--provenance-kind",
                "agent-template-release",
                "--provenance-location",
                repository,
                "--provenance-revision",
                f"{tag}@{report['commit']}",
                "--json",
            ]
            completed = subprocess.run(command, capture_output=True, text=True)
            if completed.returncode:
                report["rejected"].append(
                    {"skill": skill_id, "reason": (completed.stderr or completed.stdout).strip()}
                )
            else:
                result = json.loads(completed.stdout)
                report["imported"].append(result["skill"])
                local_ids.add(skill_id)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd())
    result.add_argument("--repository")
    result.add_argument("--release", default="latest")
    result.add_argument("--check", action="store_true")
    result.add_argument("--json", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        report = import_release(args.root, args.repository, args.release, check=args.check)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Template release: {report['release']} ({report['commit']})")
        print("New: " + (", ".join(report["new"]) or "none"))
        print("Imported: " + (", ".join(report["imported"]) or "none"))
        print("Preserved unchanged: " + (", ".join(report["preserved"]) or "none"))
        if report["rejected"]:
            print("Rejected:")
            for item in report["rejected"]:
                print(f"  - {item['skill']}: {item['reason']}")
    return 2 if report["rejected"] and not args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
