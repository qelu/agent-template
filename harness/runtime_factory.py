"""Build the configured runtime without leaking provider choices into the core boundary."""

from collections.abc import Mapping
from pathlib import Path

from harness.deployment import DeploymentError, load_deployment
from harness.reference_adapter import ReferenceRuntimeAdapter, ToolHandler
from harness.runtime import RuntimeBoundary


def configured_runtime(
    root: Path,
    *,
    actor: str,
    handlers: Mapping[str, ToolHandler],
) -> RuntimeBoundary:
    """Instantiate the adapter selected by the validated deployment profile."""
    adapter_name = load_deployment(root)["runtime"]["adapter"]
    if adapter_name == "none":
        return RuntimeBoundary(None, schema_root=root)
    if adapter_name == "reference":
        adapter = ReferenceRuntimeAdapter(actor=actor, handlers=handlers)
        return RuntimeBoundary(adapter, schema_root=root)
    raise DeploymentError(f"Runtime adapter is not implemented: {adapter_name}")
