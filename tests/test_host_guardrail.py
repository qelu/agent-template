import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


POLICY = {
    "safety": {"deny_shell_patterns": ["rm -rf /", "mkfs"]},
    "secrets": {"denied_path_markers": [".env", ".ssh", "credentials", "secrets"]},
    "audit": {"enabled": True},
}


class HostGuardrailTests(unittest.TestCase):
    @property
    def scripts(self) -> Path:
        return Path(__file__).resolve().parent.parent / "scripts" / "guardrails"

    def root(self, temporary: str, policy: dict[str, object] | None = None) -> Path:
        root = Path(temporary)
        directory = root / "config"
        directory.mkdir()
        (directory / "policies.yaml").write_text(json.dumps(policy or POLICY))
        return root

    def invoke(
        self,
        root: Path,
        host: str,
        payload: dict[str, object],
        event: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(self.scripts / f"{host}.py"), "--root", str(root)]
        if event:
            command.extend(("--event", event))
        return subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True)

    def test_codex_prompt_context_and_structured_denial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            prompt = self.invoke(
                root,
                "codex",
                {
                    "session_id": "thr_123",
                    "turn_id": "turn_456",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Implement the feature.",
                },
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)
            context = json.loads(prompt.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("thr_123", context)

            denial = self.invoke(
                root,
                "codex",
                {
                    "session_id": "thr_123",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "sudo rm -fr /*"},
                },
            )
            decision = json.loads(denial.stdout)["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "deny")
            self.assertNotIn("Implement the feature", self._audit(root, "thr_123"))

    def test_claude_code_denies_sensitive_shell_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            result = self.invoke(
                root,
                "claude_code",
                {
                    "session_id": "claude-123",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "cat ~/.ssh/id_ed25519"},
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(output["permissionDecision"], "deny")
            self.assertIn("sensitive credential", output["permissionDecisionReason"])

    def test_antigravity_uses_official_tool_call_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            result = self.invoke(
                root,
                "antigravity",
                {
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "sudo rm -rf /", "Cwd": "/workspace"},
                    },
                    "stepIdx": 19,
                    "conversationId": "agy-123",
                    "workspacePaths": ["/workspace"],
                    "modelName": "gemini",
                },
                "PreToolUse",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["decision"], "deny")
            record = json.loads(self._audit(root, "agy-123"))
            self.assertEqual(record["tool_name"], "run_command")
            self.assertEqual(record["event"], "PreToolUse")

    def test_antigravity_preserves_native_permission_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            command = self.invoke(
                root,
                "antigravity",
                {
                    "toolCall": {"name": "run_command", "args": {"CommandLine": "npm test"}},
                    "conversationId": "agy-ask",
                },
                "PreToolUse",
            )
            self.assertEqual(json.loads(command.stdout)["decision"], "ask")

            local_read = self.invoke(
                root,
                "antigravity",
                {
                    "toolCall": {"name": "view_file", "args": {"AbsolutePath": "/workspace/a.py"}},
                    "conversationId": "agy-read",
                },
                "PreToolUse",
            )
            self.assertEqual(json.loads(local_read.stdout)["decision"], "allow")

    def test_antigravity_pre_invocation_injects_ephemeral_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            result = self.invoke(
                root,
                "antigravity",
                {"invocationNum": 3, "initialNumSteps": 10, "conversationId": "agy-context"},
                "PreInvocation",
            )
            output = json.loads(result.stdout)
            self.assertIn("agy-context", output["injectSteps"][0]["ephemeralMessage"])

    def test_portable_policy_controls_shell_denials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy = {**POLICY, "safety": {"deny_shell_patterns": ["terraform destroy"]}}
            root = self.root(temporary, policy)
            result = self.invoke(
                root,
                "codex",
                {
                    "session_id": "policy-123",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "terraform destroy -auto-approve"},
                },
            )
            self.assertEqual(
                json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_antigravity_policy_failure_returns_native_denial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            (root / "config" / "policies.yaml").write_text("not-json")
            result = self.invoke(
                root,
                "antigravity",
                {"toolCall": {"name": "run_command", "args": {}}, "conversationId": "agy-bad"},
                "PreToolUse",
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["decision"], "deny")
            self.assertIn("failed closed", result.stderr)

    @staticmethod
    def _audit(root: Path, run_id: str) -> str:
        return (root / ".agent-harness" / "audit" / f"{run_id}.jsonl").read_text()


if __name__ == "__main__":
    unittest.main()
