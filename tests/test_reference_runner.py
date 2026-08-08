import tempfile
import unittest
from pathlib import Path

from scripts.run_reference import run_reference_demo


class ReferenceRunnerTests(unittest.TestCase):
    def test_complete_reference_run_is_isolated_persisted_and_validated(self) -> None:
        source = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "reference-demo"
            summary = run_reference_demo(
                source,
                workspace,
                message="Conformance starts with one complete path.",
                assume_yes=True,
            )

            self.assertEqual(summary["status"], "completed")
            output = workspace / "output" / "welcome.txt"
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "Conformance starts with one complete path.\n",
            )
            run_files = list((workspace / "runtime" / "state" / "runs").glob("*.json"))
            self.assertEqual(len(run_files), 1)
            self.assertEqual(
                (source / "config" / "tools.yaml").read_text(encoding="utf-8"),
                'version: "1.0"\ntools: []\n',
            )

    def test_existing_workspace_is_never_overwritten(self) -> None:
        source = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "existing"
            workspace.mkdir()
            marker = workspace / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                run_reference_demo(source, workspace, assume_yes=True)

            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
