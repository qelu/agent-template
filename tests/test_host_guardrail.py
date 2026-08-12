import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


POLICY = {
    "version": "1.0",
    "actions": {
        "read": "allow",
        "write": "ask",
        "delete": "deny",
        "external_side_effect": "ask",
        "unknown": "ask",
    },
    "scope": {
        "allowed_read_paths": ["."],
        "allowed_write_paths": ["."],
        "denied_paths": [".env", ".env.*", ".ssh", ".ssh/**", "secrets", "secrets/**"],
    },
    "shell": {"denied_patterns": ["rm -rf /", "mkfs"]},
    "audit": {"enabled": True},
}


class HostGuardrailTests(unittest.TestCase):
    @property
    def scripts(self) -> Path:
        return Path(__file__).resolve().parent.parent / "scripts" / "guardrails"

    def root(self, temporary: str, policy: dict[str, object] | None = None) -> Path:
        root = Path(temporary)
        (root / "config").mkdir()
        (root / "config" / "policies.yaml").write_text(json.dumps(policy or POLICY))
        return root

    def invoke(
        self, root: Path, host: str, tool_name: str, tool_input: dict[str, object]
    ) -> subprocess.CompletedProcess[str]:
        if host == "antigravity":
            payload = {
                "toolCall": {"name": tool_name, "args": tool_input},
                "conversationId": f"{host}-run",
            }
            event = ["--event", "PreToolUse"]
        else:
            payload = {
                "session_id": f"{host}-run",
                "hook_event_name": "PreToolUse",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }
            event = []
        return subprocess.run(
            [sys.executable, str(self.scripts / f"{host}.py"), "--root", str(root), *event],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def decision(self, result: subprocess.CompletedProcess[str], host: str) -> str:
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        if host == "antigravity":
            return str(payload["decision"])
        return str(payload["hookSpecificOutput"]["permissionDecision"])

    def test_claude_and_antigravity_apply_allow_ask_deny_directly(self) -> None:
        for host, read_tool, write_tool, command_key in (
            ("claude_code", "Read", "Write", "command"),
            ("antigravity", "view_file", "write_file", "CommandLine"),
        ):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temporary:
                root = self.root(temporary)
                read = self.invoke(root, host, read_tool, {"file_path": str(root / "a.py")})
                write = self.invoke(root, host, write_tool, {"file_path": str(root / "a.py")})
                delete = self.invoke(root, host, "run_command", {command_key: "rm a.py"})
                self.assertEqual(self.decision(read, host), "allow")
                self.assertEqual(self.decision(write, host), "ask")
                self.assertEqual(self.decision(delete, host), "deny")

    def test_codex_blocks_denials_and_defers_ask_to_native_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            deletion = self.invoke(root, "codex", "apply_patch", {"patch": "*** Delete File: a.py"})
            self.assertEqual(self.decision(deletion, "codex"), "deny")

            write = self.invoke(root, "codex", "apply_patch", {"patch": "*** Update File: a.py"})
            self.assertEqual(write.returncode, 0, write.stderr)
            self.assertEqual(write.stdout, "")

            outside = self.invoke(
                root, "codex", "apply_patch", {"patch": "*** Update File: ../outside.py"}
            )
            self.assertEqual(self.decision(outside, "codex"), "deny")

    def test_scope_is_enforced_for_read_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            outside = str(root.parent / "outside.txt")
            for host, tool in (("claude_code", "Read"), ("antigravity", "view_file")):
                with self.subTest(host=host):
                    result = self.invoke(root, host, tool, {"file_path": outside})
                    self.assertEqual(self.decision(result, host), "deny")

            denied = self.invoke(root, "claude_code", "Read", {"file_path": str(root / ".env")})
            self.assertEqual(self.decision(denied, "claude_code"), "deny")

    def test_shell_reads_are_scoped_and_unknown_commands_ask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            outside = self.invoke(root, "claude_code", "Bash", {"command": "cat /etc/passwd"})
            unknown = self.invoke(root, "claude_code", "Bash", {"command": "custom-tool"})
            self.assertEqual(self.decision(outside, "claude_code"), "deny")
            self.assertEqual(self.decision(unknown, "claude_code"), "ask")

    def test_common_delete_apis_are_denied_but_documentation_content_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            api = self.invoke(
                root,
                "claude_code",
                "Bash",
                {"command": "python -c 'import os; os.remove(\"a.txt\")'"},
            )
            documentation = self.invoke(
                root,
                "claude_code",
                "Write",
                {"file_path": str(root / "guide.md"), "content": "Run rm a.txt to delete it."},
            )
            self.assertEqual(self.decision(api, "claude_code"), "deny")
            self.assertEqual(self.decision(documentation, "claude_code"), "ask")

    def test_external_side_effects_ask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            for host, key in (("claude_code", "command"), ("antigravity", "CommandLine")):
                result = self.invoke(root, host, "run_command", {key: "git push origin main"})
                self.assertEqual(self.decision(result, host), "ask")

    def test_malformed_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            (root / "config" / "policies.yaml").write_text("not-json")
            result = self.invoke(root, "antigravity", "run_command", {"CommandLine": "pwd"})
            self.assertEqual(json.loads(result.stdout)["decision"], "deny")
            self.assertIn("failed closed", result.stderr)

    def test_prompt_context_and_audit_are_run_scoped_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            payload = {
                "session_id": "thread-123",
                "hook_event_name": "UserPromptSubmit",
                "prompt": "secret prompt",
            }
            result = subprocess.run(
                [sys.executable, str(self.scripts / "codex.py"), "--root", str(root)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
            )
            self.assertIn(
                "thread-123", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            )
            audit = (root / ".agent-harness" / "audit" / "thread-123.jsonl").read_text()
            self.assertNotIn("secret prompt", audit)


if __name__ == "__main__":
    unittest.main()
