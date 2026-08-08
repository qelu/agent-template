#!/usr/bin/env python3
"""Run enforced capability lifecycle transitions in the canonical registry."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.registry import CapabilityError, CapabilityLifecycle, load_capabilities  # noqa: E402


def test_capability(manager: CapabilityLifecycle, capability_id: str, actor: str) -> None:
    capability = next(
        (item for item in load_capabilities(ROOT) if item["id"] == capability_id), None
    )
    if capability is None:
        raise CapabilityError(f"Unknown capability: {capability_id}")
    suite = capability["evaluation_suite"]
    if suite is None:
        raise CapabilityError("Declare evaluation_suite before testing")
    suite_path = ROOT / suite
    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(suite_path.parent),
            "-p",
            suite_path.name,
            "-v",
        ],
        cwd=ROOT,
        check=True,
    )
    manager.record_passing_evaluation(capability_id, actor)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["test", "deprecate", "disable", "restore", "bump", "remove"],
    )
    parser.add_argument("capability_id")
    parser.add_argument("--actor", default="human:operator")
    parser.add_argument("--reason")
    parser.add_argument("--version")
    args = parser.parse_args()
    manager = CapabilityLifecycle(ROOT)
    try:
        if args.action == "test":
            test_capability(manager, args.capability_id, args.actor)
        elif args.action == "deprecate":
            manager.deprecate(args.capability_id, args.actor)
        elif args.action == "disable":
            if not args.reason:
                parser.error("disable requires --reason")
            manager.disable(args.capability_id, args.actor, args.reason)
        elif args.action == "restore":
            manager.restore(args.capability_id, args.actor)
        elif args.action == "bump":
            if not args.version:
                parser.error("bump requires --version")
            manager.bump_version(args.capability_id, args.version, args.actor)
        else:
            manager.remove(args.capability_id)
    except (CapabilityError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Capability {args.capability_id}: {args.action} completed")


if __name__ == "__main__":
    main()
