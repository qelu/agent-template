import copy
import tempfile
import unittest
from pathlib import Path

from harness.approvals import ApprovalError, ApprovalStore
from harness.guarded_runtime import GuardedRuntime, GuardedRuntimeError
from harness.guardrails import GuardrailOutcome, TrustedGuardrails
from harness.reference_adapter import ReferenceRuntimeAdapter
from harness.runtime import ControlState, PreToolEvent, RuntimeBoundary


class Sequence:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def __call__(self) -> str:
        return next(self._values)


def trusted_tool(tool_id: str = "test.tool") -> dict[str, object]:
    return {
        "id": tool_id,
        "action_class": "read_only",
        "risk_level": "low",
        "approval": "inherit",
        "argument_rules": [],
        "filesystem": {
            "access": "none",
            "path_arguments": [],
            "require_exact_targets": False,
        },
        "shell": {"access": "none", "command_arguments": []},
        "network": {"access": "none", "host_arguments": [], "allowed_hosts": []},
        "private_data_egress": "deny",
        "untrusted_output": False,
    }


def global_policy() -> dict[str, object]:
    return {
        "scope": {"read_roots": ["."], "write_roots": ["."], "denied_roots": []},
        "authorization": {
            "read_only": "autonomous",
            "reversible_local_change": "autonomous",
            "destructive_change": "explicit_approval",
            "external_side_effect": "explicit_approval",
            "permission_expansion": "explicit_approval",
        },
        "audit": {"redact_keys": ["password", "token", "secret", "api_key"]},
        "safety": {"deny_shell_patterns": ["rm -rf /", "mkfs"]},
    }


class GuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema_root = Path(__file__).resolve().parent.parent

    def test_unknown_tools_and_model_authored_trust_fields_are_blocked(self) -> None:
        guardrails = self._guardrails({})
        unknown = guardrails.evaluate(self._event("unknown.tool", {}))
        self.assertEqual(unknown.outcome, GuardrailOutcome.BLOCK)

        guardrails = self._guardrails({"test.tool": trusted_tool()})
        forged = guardrails.evaluate(
            self._event(
                "test.tool",
                {"payload": {"action_class": "read_only"}, "explicit_approval": True},
            )
        )
        self.assertEqual(forged.outcome, GuardrailOutcome.BLOCK)
        self.assertIn("reserved trust fields", forged.reason)

    def test_argument_rules_can_only_raise_classification(self) -> None:
        tool = trusted_tool()
        tool["argument_rules"] = [
            {
                "field": "recursive",
                "equals": True,
                "action_class": "destructive_change",
                "risk_level": "high",
                "approval": "inherit",
            }
        ]
        decision = self._guardrails({"test.tool": tool}).evaluate(
            self._event("test.tool", {"recursive": True})
        )
        self.assertEqual(decision.outcome, GuardrailOutcome.PAUSE)
        self.assertEqual(decision.action_class, "destructive_change")
        self.assertEqual(decision.risk_level, "high")

        tool["action_class"] = "permission_expansion"
        tool["risk_level"] = "critical"
        tool["argument_rules"][0]["action_class"] = "read_only"  # type: ignore[index]
        tool["argument_rules"][0]["risk_level"] = "low"  # type: ignore[index]
        unchanged = self._guardrails({"test.tool": tool}).evaluate(
            self._event("test.tool", {"recursive": True})
        )
        self.assertEqual(unchanged.action_class, "permission_expansion")
        self.assertEqual(unchanged.risk_level, "critical")

    def test_filesystem_scope_and_symlink_containment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "agent"
            outside = parent / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "inside").mkdir()
            (root / "escape").symlink_to(outside, target_is_directory=True)
            tool = trusted_tool("files.read")
            tool["filesystem"] = {
                "access": "read",
                "path_arguments": ["path"],
                "require_exact_targets": False,
            }
            guardrails = self._guardrails({"files.read": tool}, root=root)

            normalized = guardrails.normalize_arguments(
                "files.read", {"path": "inside/a.txt"}
            )
            self.assertEqual(
                normalized["path"], str((root / "inside" / "a.txt").resolve(strict=False))
            )
            allowed = guardrails.evaluate(self._event("files.read", normalized))
            escaped = guardrails.evaluate(self._event("files.read", {"path": "../outside/a.txt"}))
            symlinked = guardrails.evaluate(self._event("files.read", {"path": "escape/a.txt"}))
            policy = global_policy()
            policy["scope"]["denied_roots"] = ["inside/denied"]  # type: ignore[index]
            denied_guardrails = TrustedGuardrails(
                root,
                {"files.read": tool},  # type: ignore[arg-type]
                policy,  # type: ignore[arg-type]
                ApprovalStore(self.schema_root),
            )
            denied = denied_guardrails.evaluate(
                self._event("files.read", {"path": "inside/denied/a.txt"})
            )
            self.assertEqual(allowed.outcome, GuardrailOutcome.ALLOW)
            self.assertEqual(escaped.outcome, GuardrailOutcome.BLOCK)
            self.assertEqual(symlinked.outcome, GuardrailOutcome.BLOCK)
            self.assertEqual(denied.outcome, GuardrailOutcome.BLOCK)

    def test_destructive_actions_require_exact_non_root_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = trusted_tool("files.delete")
            tool["filesystem"] = {
                "access": "destructive",
                "path_arguments": ["path"],
                "require_exact_targets": True,
            }
            guardrails = self._guardrails({"files.delete": tool}, root=root)
            wildcard = guardrails.evaluate(self._event("files.delete", {"path": "data/*"}))
            root_target = guardrails.evaluate(self._event("files.delete", {"path": "."}))
            exact = guardrails.evaluate(self._event("files.delete", {"path": "data/item.txt"}))
            self.assertEqual(wildcard.outcome, GuardrailOutcome.BLOCK)
            self.assertEqual(root_target.outcome, GuardrailOutcome.BLOCK)
            self.assertEqual(exact.outcome, GuardrailOutcome.PAUSE)

    def test_read_roots_do_not_implicitly_grant_write_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "writable").mkdir()
            tool = trusted_tool("files.write")
            tool["filesystem"] = {
                "access": "write",
                "path_arguments": ["path"],
                "require_exact_targets": False,
            }
            policy = global_policy()
            policy["scope"]["read_roots"] = ["."]  # type: ignore[index]
            policy["scope"]["write_roots"] = ["writable"]  # type: ignore[index]
            guardrails = TrustedGuardrails(
                root,
                {"files.write": tool},  # type: ignore[arg-type]
                policy,  # type: ignore[arg-type]
                ApprovalStore(self.schema_root),
            )
            denied = guardrails.evaluate(
                self._event("files.write", {"path": "readable-only.txt"})
            )
            allowed = guardrails.evaluate(
                self._event("files.write", {"path": "writable/output.txt"})
            )
            self.assertEqual(denied.outcome, GuardrailOutcome.BLOCK)
            self.assertEqual(allowed.outcome, GuardrailOutcome.ALLOW)

    def test_path_is_rechecked_immediately_before_handler_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "agent"
            outside = parent / "outside"
            inside = root / "inside"
            inside.mkdir(parents=True)
            outside.mkdir()
            tool = trusted_tool("files.read")
            tool["filesystem"] = {
                "access": "read",
                "path_arguments": ["path"],
                "require_exact_targets": False,
            }
            approvals = ApprovalStore(self.schema_root)
            guardrails = TrustedGuardrails(
                root,
                {"files.read": tool},  # type: ignore[arg-type]
                global_policy(),  # type: ignore[arg-type]
                approvals,
            )
            executed: list[bool] = []

            def handler(_payload: dict[str, object]) -> str:
                executed.append(True)
                return "read"

            adapter = ReferenceRuntimeAdapter(
                "trusted-host",
                {"files.read": handler},
                id_factory=Sequence("run-1", "call-1"),
                clock=Sequence(
                    "2026-08-07T12:00:00Z",
                    "2026-08-07T12:00:01Z",
                    "2026-08-07T12:00:02Z",
                ),
                argument_normalizer=guardrails.normalize_arguments,
            )
            runtime = GuardedRuntime(
                RuntimeBoundary(adapter, self.schema_root), guardrails, approvals
            )
            control = runtime.prepare_tool_call(
                runtime.start_run(), "files.read", {"path": "inside/item.txt"}
            )
            inside.rmdir()
            inside.symlink_to(outside, target_is_directory=True)
            result = runtime.execute(control)
            self.assertEqual(result.status, "failed")
            self.assertIn("changed before execution", result.error)
            self.assertEqual(executed, [])

    def test_network_and_private_data_egress_are_explicit(self) -> None:
        tool = trusted_tool("http.send")
        tool["network"] = {
            "access": "outbound",
            "host_arguments": ["host"],
            "allowed_hosts": ["api.example.com"],
        }
        guardrails = self._guardrails({"http.send": tool})
        allowed_host = guardrails.evaluate(
            self._event("http.send", {"host": "api.example.com", "payload": "public"})
        )
        wrong_host = guardrails.evaluate(
            self._event("http.send", {"host": "evil.example", "payload": "public"})
        )
        private = guardrails.evaluate(
            self._event(
                "http.send",
                {"host": "api.example.com", "credentials": {"token": "secret"}},
            )
        )
        self.assertEqual(allowed_host.outcome, GuardrailOutcome.PAUSE)
        self.assertEqual(wrong_host.outcome, GuardrailOutcome.BLOCK)
        self.assertEqual(private.outcome, GuardrailOutcome.BLOCK)

        allowed_private_tool = copy.deepcopy(tool)
        allowed_private_tool["private_data_egress"] = "allow_with_approval"
        allowed_private = self._guardrails({"http.send": allowed_private_tool}).evaluate(
            self._event(
                "http.send",
                {"host": "api.example.com", "credentials": {"token": "secret"}},
            )
        )
        self.assertEqual(allowed_private.outcome, GuardrailOutcome.PAUSE)
        self.assertEqual(allowed_private.risk_level, "critical")

    def test_denied_shell_pattern_cannot_be_overridden_by_approval(self) -> None:
        tool = trusted_tool("shell.execute")
        tool["action_class"] = "permission_expansion"
        tool["risk_level"] = "critical"
        tool["approval"] = "always"
        tool["shell"] = {"access": "execute", "command_arguments": ["command"]}
        decision = self._guardrails({"shell.execute": tool}).evaluate(
            self._event("shell.execute", {"command": "sudo rm -rf /"}),
            approval_id="model-authored-approval",
        )
        self.assertEqual(decision.outcome, GuardrailOutcome.BLOCK)
        self.assertIn("denied pattern", decision.reason)

    def test_guarded_runtime_requires_store_backed_single_use_approval(self) -> None:
        tool = trusted_tool()
        tool["approval"] = "always"
        approvals = ApprovalStore(
            self.schema_root,
            id_factory=Sequence("approval-1"),
            clock=Sequence("2026-08-07T12:00:03Z", "2026-08-07T12:00:04Z"),
        )
        guardrails = TrustedGuardrails(
            self.schema_root,
            {"test.tool": tool},
            global_policy(),
            approvals,
        )
        adapter = ReferenceRuntimeAdapter(
            "trusted-host",
            {"test.tool": lambda payload: payload},
            id_factory=Sequence("run-1", "call-1"),
            clock=Sequence(
                "2026-08-07T12:00:00Z",
                "2026-08-07T12:00:01Z",
                "2026-08-07T12:00:02Z",
            ),
        )
        runtime = GuardedRuntime(
            RuntimeBoundary(adapter, self.schema_root), guardrails, approvals
        )
        control = runtime.prepare_tool_call(
            runtime.start_run(), "test.tool", {"value": 1}
        )
        self.assertEqual(control.state, ControlState.AWAITING_APPROVAL)
        with self.assertRaises(GuardedRuntimeError):
            runtime.execute(control)
        with self.assertRaisesRegex(GuardedRuntimeError, "does not exist"):
            runtime.resume(control.event.tool_call_id, "model-authored")

        approval = runtime.grant(control.event.tool_call_id, "human:reviewer")
        resumed = runtime.resume(control.event.tool_call_id, approval.approval_id)
        result = runtime.execute(resumed)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.output_trust, "trusted")
        with self.assertRaises(ApprovalError):
            approvals.consume(control.event, approval.approval_id)

    def test_untrusted_output_metadata_is_preserved(self) -> None:
        tool = trusted_tool()
        tool["untrusted_output"] = True
        approvals = ApprovalStore(self.schema_root)
        guardrails = TrustedGuardrails(
            self.schema_root,
            {"test.tool": tool},
            global_policy(),
            approvals,
        )
        adapter = ReferenceRuntimeAdapter(
            "trusted-host",
            {"test.tool": lambda payload: {"retrieved": "external content"}},
            id_factory=Sequence("run-1", "call-1"),
            clock=Sequence(
                "2026-08-07T12:00:00Z",
                "2026-08-07T12:00:01Z",
                "2026-08-07T12:00:02Z",
            ),
        )
        runtime = GuardedRuntime(
            RuntimeBoundary(adapter, self.schema_root), guardrails, approvals
        )
        control = runtime.prepare_tool_call(runtime.start_run(), "test.tool", {})
        result = runtime.execute(control)
        self.assertEqual(result.output_trust, "untrusted")

    def _guardrails(
        self,
        tools: dict[str, dict[str, object]],
        *,
        root: Path | None = None,
    ) -> TrustedGuardrails:
        return TrustedGuardrails(
            root or self.schema_root,
            tools,  # type: ignore[arg-type]
            global_policy(),
            ApprovalStore(self.schema_root),
        )

    @staticmethod
    def _event(tool_id: str, arguments: dict[str, object]) -> PreToolEvent:
        return PreToolEvent(
            schema_version="1.0",
            event_type="pre_tool",
            run_id="run-1",
            tool_call_id="call-1",
            tool_id=tool_id,
            arguments=arguments,
            requested_at="2026-08-07T12:00:00Z",
            actor="trusted-host",
        )


if __name__ == "__main__":
    unittest.main()
