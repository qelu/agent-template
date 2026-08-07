#!/usr/bin/env python3
"""Create a minimal agent instance from this reusable template."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

TEXT_SUFFIXES = {"", ".md", ".yaml", ".yml", ".json", ".toml", ".py", ".txt", ".example"}
PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
ROOT_FILES = (".env.example", ".gitignore", "README.md", "pyproject.toml")
ROOT_DIRECTORIES = ("agent", "config", "harness", "scripts", "skills", "templates", "tests")


def prompt(value: str | None, label: str) -> str:
    if value:
        return value.strip()
    if not sys.stdin.isatty():
        raise SystemExit(f"Missing --{label.lower().replace(' ', '-')} in non-interactive mode")
    answer = input(f"{label}: ").strip()
    if not answer:
        raise SystemExit(f"{label} is required")
    return answer


def slug(value: str) -> str:
    candidate = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not candidate:
        raise SystemExit("Agent ID must contain at least one letter or digit")
    return candidate


def copy_minimal_template(source: Path, destination: Path) -> None:
    destination.mkdir()
    for filename in ROOT_FILES:
        shutil.copy2(source / filename, destination / filename)
    for dirname in ROOT_DIRECTORIES:
        shutil.copytree(
            source / dirname,
            destination / dirname,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "__pycache__",
                ".ruff_cache",
                ".pytest_cache",
                ".mypy_cache",
                ".coverage",
                "*.pyc",
            ),
        )
    decisions = destination / "knowledge" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / ".gitkeep").write_text("", encoding="utf-8")


def replace_placeholders(root: Path, values: dict[str, str]) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = content
        for token, value in values.items():
            updated = updated.replace(token, value)
        if updated != content:
            path.write_text(updated, encoding="utf-8")


def unresolved_placeholders(root: Path) -> list[str]:
    unresolved: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if PLACEHOLDER.search(content):
            unresolved.append(str(path.relative_to(root)))
    return unresolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--name")
    parser.add_argument("--id", dest="agent_id")
    parser.add_argument("--goal")
    parser.add_argument("--role")
    parser.add_argument("--tone")
    parser.add_argument("--language", default="en-US")
    args = parser.parse_args()

    name = prompt(args.name, "Name")
    agent_id = slug(args.agent_id or name)
    goal = prompt(args.goal, "Goal")
    role = prompt(args.role, "Role")
    tone = prompt(args.tone, "Tone")
    destination = args.destination.expanduser().resolve()
    source = Path(__file__).resolve().parent.parent

    if destination.exists():
        raise SystemExit(f"Destination already exists; refusing to overwrite: {destination}")
    if source == destination or source in destination.parents:
        raise SystemExit("Destination must be outside the template directory")

    copy_minimal_template(source, destination)
    replace_placeholders(
        destination,
        {
            "__AGENT_NAME__": name,
            "__AGENT_ID__": agent_id,
            "__AGENT_GOAL__": goal,
            "__AGENT_ROLE__": role,
            "__AGENT_TONE__": tone,
            "__AGENT_LANGUAGE__": args.language,
        },
    )

    unresolved = unresolved_placeholders(destination)
    if unresolved:
        raise SystemExit(f"Initialization left unresolved placeholders: {', '.join(unresolved)}")
    print(f"Created minimal agent '{name}' at {destination}")
    print(f"Next: cd {destination} && python3 scripts/validate_repository.py")


if __name__ == "__main__":
    main()
