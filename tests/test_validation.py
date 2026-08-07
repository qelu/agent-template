import tempfile
import unittest
from pathlib import Path

from scripts.validate_repository import repository_text_files


class ValidationTests(unittest.TestCase):
    def test_repository_text_files_excludes_tool_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_file = root / "config" / "persona.yaml"
            source_file.parent.mkdir()
            source_file.write_text('name: "Example"\n', encoding="utf-8")

            dependency_file = root / ".venv" / "lib" / "dependency.py"
            dependency_file.parent.mkdir(parents=True)
            dependency_token = "__" + "DEPENDENCY_TOKEN" + "__"
            dependency_file.write_text(f"VALUE = '{dependency_token}'\n", encoding="utf-8")

            files = {path.relative_to(root) for path in repository_text_files(root)}

            self.assertEqual(files, {Path("config/persona.yaml")})


if __name__ == "__main__":
    unittest.main()
