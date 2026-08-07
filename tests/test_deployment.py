import json
import tempfile
import unittest
from pathlib import Path

from harness.deployment import (
    DeploymentError,
    load_deployment,
    validate_runtime_activation,
)


class DeploymentTests(unittest.TestCase):
    def test_repository_profile_is_valid(self) -> None:
        root = Path(__file__).resolve().parent.parent
        profile = load_deployment(root)
        expected_mode = {
            "none": "none",
            "openai": "mcp",
            "anthropic": "skill",
            "gemini": "mcp",
        }[profile["documentation"]["provider"]]
        self.assertEqual(profile["documentation"]["mode"], expected_mode)
        self.assertIn(profile["runtime"]["adapter"], {"none", "reference"})

    def test_rejects_incompatible_documentation_mode(self) -> None:
        self._assert_invalid_profile(
            """version: "1.0"
host: codex
documentation:
  provider: openai
  mode: skill
runtime:
  adapter: none
"""
        )

    def test_rejects_mcp_with_portable_host(self) -> None:
        self._assert_invalid_profile(
            """version: "1.0"
host: portable
documentation:
  provider: gemini
  mode: mcp
runtime:
  adapter: none
"""
        )

    def test_rejects_unimplemented_provider_runtime_adapter(self) -> None:
        self._assert_invalid_profile(
            """version: "1.0"
host: codex
documentation:
  provider: openai
  mode: mcp
runtime:
  adapter: openai-agents
"""
        )

    def test_active_hooks_require_runtime_adapter(self) -> None:
        profile = {
            "runtime": {"adapter": "none"},
        }
        capabilities = [
            {"id": "pre-tool-policy", "type": "hook", "status": "active"}
        ]
        with self.assertRaisesRegex(DeploymentError, "require an adapter"):
            validate_runtime_activation(profile, capabilities)

    def test_reference_adapter_allows_active_hooks(self) -> None:
        profile = {
            "runtime": {"adapter": "reference"},
        }
        capabilities = [
            {"id": "pre-tool-policy", "type": "hook", "status": "active"}
        ]
        validate_runtime_activation(profile, capabilities)

    def _assert_invalid_profile(self, content: str) -> None:
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary)
            schema_directory = candidate / "config" / "schemas"
            schema_directory.mkdir(parents=True)
            schema = json.loads(
                (root / "config" / "schemas" / "deployment.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            (schema_directory / "deployment.schema.json").write_text(
                json.dumps(schema), encoding="utf-8"
            )
            (candidate / "config" / "deployment.yaml").write_text(
                content,
                encoding="utf-8",
            )
            with self.assertRaises(DeploymentError):
                load_deployment(candidate)


if __name__ == "__main__":
    unittest.main()
