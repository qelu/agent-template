"""Build the configured runtime without leaking provider choices into the core boundary."""

from collections.abc import Mapping
from pathlib import Path

from harness.approvals import ApprovalStore
from harness.deployment import DeploymentError, load_deployment
from harness.guarded_runtime import GuardedRuntime
from harness.guardrails import TrustedGuardrails
from harness.policy import load_policy
from harness.reference_adapter import ReferenceRuntimeAdapter, ToolHandler
from harness.runtime import RuntimeBoundary
from harness.tool_policy import load_tool_policies


def configured_runtime(
    root: Path,
    *,
    actor: str,
    handlers: Mapping[str, ToolHandler],
) -> GuardedRuntime:
    """Instantiate the adapter selected by the validated deployment profile."""
    adapter_name = load_deployment(root)["runtime"]["adapter"]
    approvals = ApprovalStore(root)
    guardrails = TrustedGuardrails(
        root=root,
        tool_policies=load_tool_policies(root),
        policy=load_policy(root),
        approvals=approvals,
    )
    if adapter_name == "none":
        boundary = RuntimeBoundary(None, schema_root=root)
    elif adapter_name == "reference":
        adapter = ReferenceRuntimeAdapter(
            actor=actor,
            handlers=handlers,
            argument_normalizer=guardrails.normalize_arguments,
        )
        boundary = RuntimeBoundary(adapter, schema_root=root)
    else:
        raise DeploymentError(f"Runtime adapter is not implemented: {adapter_name}")
    return GuardedRuntime(boundary, guardrails, approvals)
