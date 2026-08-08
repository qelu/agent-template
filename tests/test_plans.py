import tempfile
import unittest
from pathlib import Path

from harness.plans import PlanApprovalError, PlanApprovalStore


class Sequence:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def __call__(self) -> str:
        return next(self._values)


class PlanApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent.parent
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.storage = Path(self.temporary.name)
        self.store = PlanApprovalStore(
            self.root,
            storage_directory=self.storage,
            id_factory=Sequence("approval-1"),
            clock=Sequence("2026-08-08T10:00:00Z", "2026-08-08T10:01:00Z"),
        )
        self.digest = "a" * 64

    def test_approval_is_exact_and_single_use(self) -> None:
        granted = self.store.grant("run-1", 1, self.digest, "human:reviewer")
        consumed = self.store.consume("run-1", 1, self.digest, granted.approval_id)
        self.assertEqual(consumed.consumed_at, "2026-08-08T10:01:00Z")
        with self.assertRaisesRegex(PlanApprovalError, "already been consumed"):
            self.store.consume("run-1", 1, self.digest, granted.approval_id)

    def test_mismatch_does_not_consume_approval(self) -> None:
        granted = self.store.grant("run-1", 1, self.digest, "human:reviewer")
        for run_id, revision, digest in (
            ("other-run", 1, self.digest),
            ("run-1", 2, self.digest),
            ("run-1", 1, "b" * 64),
        ):
            with self.subTest(run_id=run_id, revision=revision, digest=digest):
                with self.assertRaisesRegex(PlanApprovalError, "exact plan"):
                    self.store.consume(run_id, revision, digest, granted.approval_id)

    def test_competing_store_cannot_approve_same_revision(self) -> None:
        competing = PlanApprovalStore(
            self.root,
            storage_directory=self.storage,
            id_factory=Sequence("approval-2"),
            clock=Sequence("2026-08-08T10:02:00Z"),
        )
        self.store.grant("run-1", 1, self.digest, "human:first")
        with self.assertRaisesRegex(PlanApprovalError, "already exists"):
            competing.grant("run-1", 1, self.digest, "human:second")

    def test_generated_approval_ids_cannot_collide(self) -> None:
        store = PlanApprovalStore(
            self.root,
            id_factory=Sequence("same-id", "same-id"),
            clock=Sequence("2026-08-08T10:02:00Z", "2026-08-08T10:03:00Z"),
        )
        store.grant("run-1", 1, self.digest, "human:first")
        with self.assertRaisesRegex(PlanApprovalError, "ID already exists"):
            store.grant("run-2", 1, self.digest, "human:second")


if __name__ == "__main__":
    unittest.main()
