import tempfile
import unittest
from pathlib import Path

import yaml

from harness.integrations import IntegrationError, active_integrations, load_integrations


class IntegrationCatalogTests(unittest.TestCase):
    def write_catalog(self, root: Path, integrations: list[object]) -> None:
        config = root / "config"
        config.mkdir()
        (config / "integrations.yaml").write_text(
            yaml.safe_dump({"version": "1.0", "integrations": integrations}),
            encoding="utf-8",
        )

    def integration(self, **overrides: object) -> dict[str, object]:
        result: dict[str, object] = {
            "id": "jira-cloud",
            "status": "active",
            "kind": "remote-mcp",
            "provider": "Atlassian",
            "description": "Access Jira Cloud through the official service.",
            "official_source": "https://support.atlassian.com/",
            "auth": "oauth",
            "hosts": ["codex", "claude-code", "antigravity"],
            "default_approval": "writes",
            "required": False,
            "data_classes": ["issues", "projects"],
            "write_capable": True,
            "endpoint": "https://mcp.atlassian.com/v1/mcp/authv2",
        }
        result.update(overrides)
        return result

    def test_valid_catalog_loads_and_filters_active_integrations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(
                root,
                [self.integration(), self.integration(id="future", status="experimental")],
            )
            self.assertEqual(len(load_integrations(root)), 2)
            self.assertEqual([item["id"] for item in active_integrations(root)], ["jira-cloud"])

    def test_remote_mcp_requires_https(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, [self.integration(endpoint="http://example.com/mcp")])
            with self.assertRaisesRegex(IntegrationError, "HTTPS endpoint"):
                load_integrations(root)

    def test_duplicate_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, [self.integration(), self.integration()])
            with self.assertRaisesRegex(IntegrationError, "Duplicate integration ID"):
                load_integrations(root)

    def test_non_mcp_integration_must_not_define_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(
                root,
                [self.integration(kind="official-cli", auth="provider-cli", endpoint="nope")],
            )
            with self.assertRaisesRegex(IntegrationError, "must set endpoint to null"):
                load_integrations(root)

    def test_optional_integration_cannot_be_required_at_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, [self.integration(required=True)])
            with self.assertRaisesRegex(IntegrationError, "cannot be required"):
                load_integrations(root)

    def test_official_source_requires_https(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, [self.integration(official_source="http://example.com")])
            with self.assertRaisesRegex(IntegrationError, "official_source must use HTTPS"):
                load_integrations(root)


if __name__ == "__main__":
    unittest.main()
