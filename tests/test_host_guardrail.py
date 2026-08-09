import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class HostGuardrailTests(unittest.TestCase):
    @property
    def script(self) -> Path:
        return Path(__file__).resolve().parent.parent / "scripts" / "host_guardrail.py"

    def invoke(
        self, root: Path, payload: dict[str, object], host: str = "codex"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), "--host", host, "--root", str(root)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def test_prompt_context_uses_native_session_as_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.invoke(
                root,
                {
                    "session_id": "thr_123",
                    "turn_id": "turn_456",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Implement the feature.",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("thr_123", context)
            self.assertIn("earlier plan never authorizes later requests", context)
            audit = (root / ".agent-harness" / "audit" / "thr_123.jsonl").read_text()
            record = json.loads(audit)
            self.assertEqual(record["run_id"], "thr_123")
            self.assertNotIn("Implement the feature", audit)

    def test_antigravity_conversation_id_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.invoke(
                root,
                {
                    "conversationId": "agy-123",
                    "hookEventName": "PreInvocation",
                },
                host="antigravity",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = (root / ".agent-harness" / "audit" / "agy-123.jsonl").read_text()
            self.assertEqual(json.loads(audit)["host"], "antigravity")

    def test_destructive_root_command_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.invoke(
                Path(temporary),
                {
                    "session_id": "thr_123",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "sudo rm -rf /"},
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Blocked destructive command", result.stderr)

    def test_sensitive_file_access_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.invoke(
                Path(temporary),
                {
                    "session_id": "thr_123",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "read_file",
                    "tool_input": {"path": "/home/user/.ssh/id_ed25519"},
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("sensitive credential", result.stderr)


if __name__ == "__main__":
    unittest.main()
