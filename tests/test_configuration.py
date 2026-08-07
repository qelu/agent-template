import tempfile
import unittest
from pathlib import Path

from harness.configuration import ConfigurationError, load_yaml


class ConfigurationTests(unittest.TestCase):
    def test_loads_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text("enabled: true\n", encoding="utf-8")
            self.assertEqual(load_yaml(path), {"enabled": True})

    def test_rejects_non_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text("- item\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_yaml(path)


if __name__ == "__main__":
    unittest.main()
