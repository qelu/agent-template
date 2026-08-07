"""Configuration loading with explicit, useful errors."""

from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(RuntimeError):
    """Raised when a configuration document is missing or invalid."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from *path*."""
    if not path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"Expected a YAML mapping in {path}")
    return value
