#!/usr/bin/env python3
"""Statically audit a skill directory without executing candidate content."""

from __future__ import annotations

import argparse
import ast
import json
import re
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


FRONTMATTER = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK = re.compile(r"!?\[[^]]*]\(([^)]+)\)")
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic-secret", re.compile(r"(?i)(?:api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{8,}")),
)
DANGEROUS_PATTERNS = (
    ("error", "destructive-delete", re.compile(r"\brm\s+-[A-Za-z]*r[A-Za-z]*f\b")),
    ("warning", "recursive-delete", re.compile(r"shutil\.rmtree\s*\(")),
    ("error", "privilege-escalation", re.compile(r"\bsudo\b|os\.setuid\s*\(")),
    (
        "error",
        "download-and-execute",
        re.compile(r"(?:curl|wget)[^\n|]*\|\s*(?:sh|bash|zsh)\b"),
    ),
    ("error", "dynamic-execution", re.compile(r"\beval\s*\(|\bexec\s*\(|shell\s*=\s*True")),
)
NETWORK_PATTERNS = re.compile(
    r"\b(?:requests\.(?:get|post|put|delete)|urllib\.request|httpx\.|fetch\s*\(|curl\b|wget\b)"
)
ALLOWED_THIRD_PARTY_IMPORTS = {"yaml"}
TEXT_SUFFIXES = {"", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".py", ".sh", ".js", ".ts"}
SUSPICIOUS_NAMES = {".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.yaml"}
MAX_FILES = 2000
MAX_TOTAL_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    path: str | None = None


def _finding(
    findings: list[Finding], severity: str, code: str, message: str, path: Path | None = None
) -> None:
    findings.append(Finding(severity, code, message, path.as_posix() if path else None))


def _text(path: Path, findings: list[Finding], relative: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _finding(
            findings,
            "warning",
            "binary-file",
            "File is not UTF-8 text and requires manual review.",
            relative,
        )
    except OSError as exc:
        _finding(findings, "error", "unreadable-file", str(exc), relative)
    return None


def audit_skill(root: Path) -> dict[str, Any]:
    root = root.resolve()
    findings: list[Finding] = []
    if not root.is_dir():
        _finding(findings, "error", "not-directory", "Candidate must be a skill directory.")
        return _result(root, None, findings)

    paths = list(root.rglob("*"))
    files = [path for path in paths if path.is_file()]
    if len(files) > MAX_FILES:
        _finding(
            findings,
            "error",
            "too-many-files",
            f"Skill contains {len(files)} files; limit is {MAX_FILES}.",
        )
    total_bytes = sum(path.stat().st_size for path in files if not path.is_symlink())
    if total_bytes > MAX_TOTAL_BYTES:
        _finding(
            findings,
            "error",
            "skill-too-large",
            f"Skill is {total_bytes} bytes; limit is {MAX_TOTAL_BYTES}.",
        )

    for path in paths:
        relative = path.relative_to(root)
        if path.is_symlink():
            _finding(
                findings,
                "error",
                "symlink",
                "Symlinks are not allowed in imported skills.",
                relative,
            )
        if path.name in SUSPICIOUS_NAMES or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            _finding(
                findings,
                "error",
                "sensitive-file",
                "Sensitive credential-like file is not allowed.",
                relative,
            )

    skill_md = root / "SKILL.md"
    metadata: dict[str, Any] | None = None
    if not skill_md.is_file():
        _finding(findings, "error", "missing-skill-md", "SKILL.md is required.")
    else:
        content = _text(skill_md, findings, Path("SKILL.md"))
        match = FRONTMATTER.match(content or "")
        if not match:
            _finding(
                findings,
                "error",
                "invalid-frontmatter",
                "SKILL.md must begin with YAML frontmatter.",
                Path("SKILL.md"),
            )
        else:
            try:
                loaded = yaml.safe_load(match.group(1))
                metadata = loaded if isinstance(loaded, dict) else None
            except yaml.YAMLError as exc:
                _finding(findings, "error", "invalid-frontmatter", str(exc), Path("SKILL.md"))
            if metadata is not None:
                if set(metadata) != {"name", "description"}:
                    _finding(
                        findings,
                        "error",
                        "frontmatter-fields",
                        "Frontmatter must contain only name and description.",
                        Path("SKILL.md"),
                    )
                name = metadata.get("name")
                description = metadata.get("description")
                if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
                    _finding(
                        findings,
                        "error",
                        "invalid-name",
                        "Skill name must use lowercase hyphen-case.",
                        Path("SKILL.md"),
                    )
                elif root.name != name:
                    _finding(
                        findings,
                        "error",
                        "folder-name-mismatch",
                        f"Folder name must be {name!r}.",
                        Path("SKILL.md"),
                    )
                if not isinstance(description, str) or len(description.strip()) < 20:
                    _finding(
                        findings,
                        "error",
                        "weak-description",
                        "Description must clearly state what the skill does and when to use it.",
                        Path("SKILL.md"),
                    )

    openai = root / "agents" / "openai.yaml"
    if openai.exists():
        try:
            payload = yaml.safe_load(openai.read_text(encoding="utf-8"))
            interface = payload.get("interface") if isinstance(payload, dict) else None
            prompt = interface.get("default_prompt") if isinstance(interface, dict) else None
            name = metadata.get("name") if metadata else None
            if not isinstance(prompt, str) or (name and f"${name}" not in prompt):
                _finding(
                    findings,
                    "warning",
                    "ui-prompt",
                    "Default prompt should explicitly mention $skill-name.",
                    Path("agents/openai.yaml"),
                )
        except (OSError, yaml.YAMLError) as exc:
            _finding(findings, "error", "invalid-openai-yaml", str(exc), Path("agents/openai.yaml"))

    for path in files:
        if path.is_symlink():
            continue
        relative = path.relative_to(root)
        mode = path.stat().st_mode
        if (
            stat.S_ISREG(mode)
            and mode & stat.S_IXUSR
            and path.suffix.lower() not in {".py", ".sh", ".js", ".ts"}
        ):
            _finding(
                findings,
                "warning",
                "unexpected-executable",
                "Executable non-script file requires manual review.",
                relative,
            )
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2 * 1024 * 1024:
            continue
        content = _text(path, findings, relative)
        if content is None:
            continue
        for code, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                _finding(
                    findings,
                    "error",
                    code,
                    "Possible secret or credential material detected.",
                    relative,
                )
        if relative.parts and relative.parts[0] == "scripts":
            for severity, code, pattern in DANGEROUS_PATTERNS:
                if pattern.search(content):
                    message = (
                        "Potentially dangerous executable behavior requires rejection or redesign."
                        if severity == "error"
                        else "Recursive deletion requires manual scope and rollback review."
                    )
                    _finding(findings, severity, code, message, relative)
            if NETWORK_PATTERNS.search(content):
                _finding(
                    findings,
                    "warning",
                    "network-operation",
                    "Script performs network operations; verify that the skill declares and constrains them.",
                    relative,
                )
            if path.suffix.lower() == ".py":
                try:
                    tree = ast.parse(content)
                except SyntaxError as exc:
                    _finding(findings, "error", "invalid-python", str(exc), relative)
                else:
                    imports: set[str] = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                            imports.add(node.module.split(".", 1)[0])
                    local_modules = {
                        item.stem for item in path.parent.glob("*.py") if item.name != "__init__.py"
                    }
                    undeclared = sorted(
                        imports
                        - sys.stdlib_module_names
                        - ALLOWED_THIRD_PARTY_IMPORTS
                        - local_modules
                    )
                    if undeclared:
                        _finding(
                            findings,
                            "warning",
                            "third-party-dependency",
                            "Third-party Python imports require dependency review: "
                            + ", ".join(undeclared),
                            relative,
                        )
        if path.suffix.lower() == ".md":
            for target in MARKDOWN_LINK.findall(content):
                target = target.strip().split("#", 1)[0]
                if not target or "://" in target or target.startswith(("mailto:", "#")):
                    continue
                resolved = (path.parent / target).resolve()
                if resolved != root and root not in resolved.parents:
                    _finding(
                        findings,
                        "error",
                        "escaping-reference",
                        f"Reference escapes the skill: {target}",
                        relative,
                    )
                elif not resolved.exists():
                    _finding(
                        findings,
                        "error",
                        "broken-reference",
                        f"Referenced file does not exist: {target}",
                        relative,
                    )

    return _result(root, metadata, findings)


def _result(root: Path, metadata: dict[str, Any] | None, findings: list[Finding]) -> dict[str, Any]:
    errors = sum(item.severity == "error" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    verdict = "reject" if errors else "pass-with-warnings" if warnings else "pass"
    risk = "high" if errors else "medium" if warnings else "low"
    return {
        "skill": metadata.get("name") if metadata else root.name,
        "verdict": verdict,
        "risk": risk,
        "summary": {"errors": errors, "warnings": warnings},
        "findings": [asdict(item) for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit_skill(args.skill)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Verdict: {result['verdict']}")
        print(f"Risk: {result['risk']}")
        print("Findings:")
        if not result["findings"]:
            print("  - none")
        for item in result["findings"]:
            location = f" ({item['path']})" if item["path"] else ""
            print(f"  - [{item['severity']}] {item['code']}{location}: {item['message']}")
    return 2 if result["verdict"] == "reject" else 0


if __name__ == "__main__":
    raise SystemExit(main())
