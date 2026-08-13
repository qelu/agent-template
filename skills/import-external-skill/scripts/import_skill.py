#!/usr/bin/env python3
"""Audit and atomically import one new skill into a generated harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import yaml


HOST_SKILL_ROOTS = {
    "portable": Path(".agents/skills"),
    "codex": Path(".agents/skills"),
    "claude-code": Path(".claude/skills"),
    "antigravity": Path(".agents/skills"),
}
FULL_COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
SKILL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 2000


class ImportFailure(ValueError):
    """Raised when an import cannot be performed safely."""


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ImportFailure(f"{path} must contain a mapping")
    return payload


def _write_yaml_atomic(path: Path, payload: dict[str, Any]) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            yaml.safe_dump(payload, stream, sort_keys=False)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            raise ImportFailure(f"Archive contains more than {MAX_ARCHIVE_FILES} entries")
        if sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES:
            raise ImportFailure(f"Archive expands beyond {MAX_ARCHIVE_BYTES} bytes")
        root = destination.resolve()
        for member in members:
            name = member.filename
            if "\x00" in name:
                raise ImportFailure("Archive contains a NUL path")
            target = (destination / name).resolve()
            if target != root and root not in target.parents:
                raise ImportFailure(f"Archive path escapes destination: {name}")
            mode = member.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                raise ImportFailure(f"Archive contains a symlink: {name}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def _download(url: str, expected: str, destination: Path) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ImportFailure("--sha256 must be a 64-character hexadecimal digest")
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(url, headers={"User-Agent": "agent-harness-skill-importer"})
    with urllib.request.urlopen(request, timeout=30) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise ImportFailure(f"Download exceeds {MAX_ARCHIVE_BYTES} bytes")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected.lower():
        raise ImportFailure(f"SHA-256 mismatch: expected {expected.lower()}, got {actual}")
    return actual


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ImportFailure(f"Required command is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ImportFailure(f"Command failed: {' '.join(command)}: {detail}") from exc


def _clone_pinned(url: str, reference: str, destination: Path) -> str:
    if FULL_COMMIT.fullmatch(reference):
        _run(["git", "init", "-q", str(destination)])
        _run(["git", "remote", "add", "origin", url], cwd=destination)
        _run(["git", "fetch", "-q", "--depth", "1", "origin", reference], cwd=destination)
        _run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=destination)
    elif reference.startswith("tag:") and len(reference) > 4:
        tag = reference[4:]
        _run(["git", "clone", "-q", "--depth", "1", "--branch", tag, url, str(destination)])
    else:
        raise ImportFailure(
            "Git sources require a full 40-character commit or tag:<name>; branches are rejected"
        )
    return _run(["git", "rev-parse", "HEAD"], cwd=destination).stdout.strip()


@contextmanager
def prepared_source(args: argparse.Namespace) -> Iterator[tuple[Path, dict[str, str]]]:
    with tempfile.TemporaryDirectory(prefix="skill-import-") as temporary:
        staging = Path(temporary)
        if args.git_url:
            repository = staging / "repository"
            commit = _clone_pinned(args.git_url, args.git_ref, repository)
            yield repository, {"kind": "git", "location": args.git_url, "revision": commit}
            return
        source = args.source
        if source.startswith("http://"):
            raise ImportFailure("Remote archives require HTTPS")
        if source.startswith("https://"):
            if not args.sha256:
                raise ImportFailure("Remote archives require --sha256")
            archive = staging / "skill.zip"
            digest = _download(source, args.sha256, archive)
            extracted = staging / "extracted"
            extracted.mkdir()
            _safe_extract(archive, extracted)
            yield extracted, {"kind": "archive-url", "location": source, "sha256": digest}
            return
        local = Path(source).expanduser().resolve()
        if local.is_dir():
            yield local, {"kind": "local-directory", "location": str(local)}
            return
        if local.is_file() and zipfile.is_zipfile(local):
            extracted = staging / "extracted"
            extracted.mkdir()
            _safe_extract(local, extracted)
            yield (
                extracted,
                {
                    "kind": "local-zip",
                    "location": str(local),
                    "sha256": hashlib.sha256(local.read_bytes()).hexdigest(),
                },
            )
            return
        raise ImportFailure(f"Unsupported or missing source: {local}")


def _skill_metadata(path: Path) -> dict[str, str]:
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", text, re.DOTALL)
    payload = yaml.safe_load(match.group(1)) if match else None
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        raise ImportFailure(f"Invalid SKILL.md metadata: {path}")
    return {"name": payload["name"], "description": str(payload.get("description", ""))}


def _candidates(source: Path) -> list[Path]:
    if (source / "SKILL.md").is_file():
        return [source]
    return sorted(
        {path.parent for path in source.rglob("SKILL.md") if ".git" not in path.parts},
        key=lambda path: path.as_posix(),
    )


def _choose_candidate(source: Path, requested: str | None) -> tuple[Path, dict[str, str]]:
    candidates = [(path, _skill_metadata(path)) for path in _candidates(source)]
    if requested:
        matches = [
            (path, metadata) for path, metadata in candidates if metadata["name"] == requested
        ]
        if len(matches) != 1:
            raise ImportFailure(
                f"Expected exactly one skill named {requested!r}; found {len(matches)}"
            )
        return matches[0]
    if len(candidates) != 1:
        names = ", ".join(metadata["name"] for _, metadata in candidates) or "none"
        raise ImportFailure(
            f"Source contains {len(candidates)} skills ({names}); select one with --skill"
        )
    return candidates[0]


def _auditor(root: Path, registry: dict[str, Any]) -> Path:
    for item in registry.get("capabilities", []):
        if isinstance(item, dict) and item.get("id") == "skill-auditor":
            script = root / str(item.get("path")) / "scripts" / "audit_skill.py"
            if script.is_file():
                return script
    raise ImportFailure("Required skill-auditor helper is not installed")


def import_skill(root: Path, candidate: Path, source: dict[str, str]) -> dict[str, Any]:
    root = root.resolve()
    registry_path = root / "config" / "capabilities.yaml"
    receipt_path = root / ".agent-harness" / "installation.yaml"
    registry = _load_yaml(registry_path)
    receipt = _load_yaml(receipt_path)
    metadata = _skill_metadata(candidate)
    skill_id = metadata["name"]
    if not SKILL_ID.fullmatch(skill_id):
        raise ImportFailure(f"Invalid skill ID: {skill_id}")
    host = str(receipt.get("host", ""))
    if host not in HOST_SKILL_ROOTS:
        raise ImportFailure(f"Unsupported harness host: {host}")
    skill_root = root / HOST_SKILL_ROOTS[host]
    destination = skill_root / skill_id
    existing_ids = {
        str(item.get("id")) for item in registry.get("capabilities", []) if isinstance(item, dict)
    }
    if skill_id in existing_ids or destination.exists():
        return {
            "status": "preserved",
            "skill": skill_id,
            "reason": "ID or destination already exists",
        }

    original_registry = registry_path.read_text(encoding="utf-8")
    original_receipt = receipt_path.read_text(encoding="utf-8")
    skill_root.mkdir(parents=True, exist_ok=True)
    container = Path(tempfile.mkdtemp(prefix=f".{skill_id}.import-", dir=skill_root))
    staged = container / skill_id
    try:
        shutil.copytree(candidate, staged)
        staged_metadata = _skill_metadata(staged)
        if staged_metadata["name"] != skill_id:
            raise ImportFailure("Skill identity changed while it was being staged")
        metadata = staged_metadata
        audit = subprocess.run(
            [sys.executable, str(_auditor(root, registry)), str(staged), "--json"],
            capture_output=True,
            text=True,
        )
        if not audit.stdout:
            raise ImportFailure((audit.stderr or "Skill auditor produced no result").strip())
        audit_result = json.loads(audit.stdout)
        if audit_result.get("verdict") == "reject" or audit.returncode:
            raise ImportFailure(
                f"Skill audit rejected {skill_id}: {json.dumps(audit_result['findings'])}"
            )
        registry.setdefault("capabilities", []).append(
            {
                "id": skill_id,
                "type": "skill",
                "status": "active",
                "path": destination.relative_to(root).as_posix(),
                "description": metadata["description"],
                "when": metadata["description"],
            }
        )
        imports = receipt.setdefault("skill_imports", [])
        if not isinstance(imports, list):
            raise ImportFailure("Receipt skill_imports must be a list")
        imports.append(
            {
                "skill": skill_id,
                "imported_at": datetime.now(UTC).isoformat(),
                "source": source,
                "audit_verdict": audit_result["verdict"],
            }
        )
        capabilities = receipt.setdefault("capabilities", [])
        if isinstance(capabilities, list) and skill_id not in capabilities:
            capabilities.append(skill_id)
        os.replace(staged, destination)
        container.rmdir()
        _write_yaml_atomic(registry_path, registry)
        _write_yaml_atomic(receipt_path, receipt)
        validation = _run([sys.executable, str(root / "scripts" / "validate_harness.py")], cwd=root)
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination)
        if staged.exists():
            shutil.rmtree(staged)
        if container.exists():
            shutil.rmtree(container)
        registry_path.write_text(original_registry, encoding="utf-8")
        receipt_path.write_text(original_receipt, encoding="utf-8")
        raise
    return {
        "status": "imported",
        "skill": skill_id,
        "source": source,
        "audit": audit_result,
        "validation": validation.stdout.strip(),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd())
    source = result.add_mutually_exclusive_group(required=True)
    source.add_argument("--source")
    source.add_argument("--git-url")
    result.add_argument("--git-ref")
    result.add_argument("--sha256")
    result.add_argument("--skill")
    result.add_argument("--provenance-kind", help=argparse.SUPPRESS)
    result.add_argument("--provenance-location", help=argparse.SUPPRESS)
    result.add_argument("--provenance-revision", help=argparse.SUPPRESS)
    result.add_argument("--json", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.git_url and not args.git_ref:
        print("ERROR: --git-ref is required with --git-url", file=sys.stderr)
        return 2
    try:
        with prepared_source(args) as (source, provenance):
            if args.provenance_kind:
                provenance = {
                    "kind": args.provenance_kind,
                    "location": args.provenance_location or provenance["location"],
                }
                if args.provenance_revision:
                    provenance["revision"] = args.provenance_revision
            candidate, _ = _choose_candidate(source, args.skill)
            result = import_skill(args.root, candidate, provenance)
    except (ImportFailure, OSError, ValueError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif result["status"] == "preserved":
        print(f"Preserved unchanged: {result['skill']} ({result['reason']})")
    else:
        print(f"Imported: {result['skill']}")
        print(f"Audit: {result['audit']['verdict']} ({result['audit']['risk']} risk)")
        print(result["validation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
