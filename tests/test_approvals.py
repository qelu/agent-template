import unittest
import tempfile
from dataclasses import replace
from pathlib import Path

from harness.approvals import ApprovalError, ApprovalStore, arguments_digest
from harness.runtime import PreToolEvent


class Sequence:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def __call__(self) -> str:
        return next(self._values)


class ApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent.parent
        self.store = ApprovalStore(
            self.root,
            id_factory=Sequence("approval-1"),
            clock=Sequence("2026-08-07T12:00:00Z", "2026-08-07T12:01:00Z"),
        )
        self.event = PreToolEvent(
            schema_version="1.0",
            event_type="pre_tool",
            run_id="run-1",
            tool_call_id="call-1",
            tool_id="files.write",
            arguments={"path": "notes.txt", "content": "hello"},
            requested_at="2026-08-07T11:59:00Z",
            actor="reference-runtime",
        )

    def test_approval_is_bound_to_exact_call_and_arguments(self) -> None:
        record = self.store.grant(self.event, "human:reviewer")
        self.assertEqual(record.run_id, self.event.run_id)
        self.assertEqual(record.tool_call_id, self.event.tool_call_id)
        self.assertEqual(record.tool_id, self.event.tool_id)
        self.assertEqual(record.arguments_digest, arguments_digest(self.event.arguments))
        self.assertIsNone(record.consumed_at)

        consumed = self.store.consume(self.event, record.approval_id)
        self.assertEqual(consumed.consumed_at, "2026-08-07T12:01:00Z")

    def test_changed_call_fields_do_not_consume_approval(self) -> None:
        record = self.store.grant(self.event, "human:reviewer")
        changes = (
            {"run_id": "other-run"},
            {"tool_call_id": "other-call"},
            {"tool_id": "files.delete"},
            {"arguments": {"path": "other.txt", "content": "hello"}},
        )
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaisesRegex(ApprovalError, "does not match"):
                    self.store.consume(replace(self.event, **change), record.approval_id)
        self.assertIsNone(self.store.get(record.approval_id).consumed_at)

    def test_forged_and_reused_approvals_fail_closed(self) -> None:
        with self.assertRaisesRegex(ApprovalError, "does not exist"):
            self.store.consume(self.event, "model-authored-approval")
        record = self.store.grant(self.event, "human:reviewer")
        self.store.consume(self.event, record.approval_id)
        with self.assertRaisesRegex(ApprovalError, "already been consumed"):
            self.store.consume(self.event, record.approval_id)

    def test_only_one_approval_can_be_granted_per_call(self) -> None:
        self.store.grant(self.event, "human:reviewer")
        with self.assertRaisesRegex(ApprovalError, "already exists"):
            self.store.grant(self.event, "human:second-reviewer")

    def test_persistent_stores_cannot_grant_competing_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary)
            first = ApprovalStore(
                self.root,
                storage_directory=storage,
                id_factory=Sequence("approval-1"),
                clock=Sequence("2026-08-07T12:00:00Z"),
            )
            second = ApprovalStore(
                self.root,
                storage_directory=storage,
                id_factory=Sequence("approval-2"),
                clock=Sequence("2026-08-07T12:01:00Z"),
            )
            first.grant(self.event, "human:first")
            with self.assertRaisesRegex(ApprovalError, "already exists"):
                second.grant(self.event, "human:second")


if __name__ == "__main__":
    unittest.main()
