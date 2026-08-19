#!/usr/bin/env python3
"""Launch the manage-mcp-access helper from its host-native skill directory."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SKILL_HELPERS = (
    Path(".agents/skills/manage-mcp-access/scripts/update_mcp_access.py"),
    Path(".claude/skills/manage-mcp-access/scripts/update_mcp_access.py"),
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(add_help=False)
    result.add_argument("--root", type=Path, default=Path.cwd())
    return result


def main() -> int:
    args, _ = parser().parse_known_args()
    root = args.root.expanduser().resolve()
    helpers = [root / relative for relative in SKILL_HELPERS if (root / relative).is_file()]
    if not helpers:
        locations = ", ".join(str(path) for path in SKILL_HELPERS)
        raise SystemExit(f"ERROR: manage-mcp-access helper not found under {root}: {locations}")
    if len(helpers) > 1:
        raise SystemExit(
            "ERROR: multiple manage-mcp-access helpers found; remove the skill directory "
            "that does not belong to this harness host"
        )
    return subprocess.run([sys.executable, str(helpers[0]), *sys.argv[1:]], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
