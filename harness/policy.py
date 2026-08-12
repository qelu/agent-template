"""Repository-facing access to the policy parser used by runtime hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.guardrails.core import load_policy as _load_runtime_policy


class PolicyError(ValueError):
    """Raised when the portable project policy is invalid."""


def load_policy(root: Path) -> dict[str, Any]:
    """Load policy through the same strict parser used by every host hook."""
    try:
        return _load_runtime_policy(root)
    except ValueError as exc:
        raise PolicyError(f"Invalid portable policy: {exc}") from exc
