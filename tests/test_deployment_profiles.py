import json
import tomllib
import unittest
from pathlib import Path

import yaml

from harness.deployment import load_deployment


ENTRYPOINTS = {
    "portable": None,
    "codex": "AGENTS.md",
    "claude-code": "CLAUDE.md",
    "gemini-cli": "GEMINI.md",
}
MCP_SERVERS = {
    "openai": ("openaiDeveloperDocs", "https://developers.openai.com/mcp"),
    "gemini": ("geminiDocs", "https://gemini-api-docs-mcp.dev"),
}


class DeploymentProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.profile = load_deployment(cls.root)
        cls.registry = yaml.safe_load(
            (cls.root / "config" / "capabilities.yaml").read_text(encoding="utf-8")
        )

    def test_host_entrypoint_is_thin_and_exclusive(self) -> None:
        host = self.profile["host"]
        expected = ENTRYPOINTS[host]
        for filename in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            path = self.root / filename
            self.assertEqual(path.exists(), filename == expected)
            if filename == expected:
                self.assertIn("agent/AGENT.md", path.read_text(encoding="utf-8"))

    def test_documentation_capability_matches_profile(self) -> None:
        provider = self.profile["documentation"]["provider"]
        documentation_capabilities = [
            capability
            for capability in self.registry["capabilities"]
            if capability["id"].endswith("-documentation")
            and capability["id"] != "documentation-maintenance"
        ]
        if provider == "none":
            self.assertEqual(documentation_capabilities, [])
            return

        self.assertEqual(len(documentation_capabilities), 1)
        capability = documentation_capabilities[0]
        self.assertEqual(capability["id"], f"{provider}-documentation")
        self.assertEqual(capability["status"], "active")
        self.assertTrue((self.root / capability["path"]).exists())
        if provider == "anthropic":
            self.assertEqual(self.profile["documentation"]["mode"], "skill")
            self.assertEqual(capability["type"], "skill")
            skill = self.root / capability["path"] / "SKILL.md"
            content = skill.read_text(encoding="utf-8")
            self.assertIn("https://platform.claude.com/llms.txt", content)
            self.assertIn("https://code.claude.com/docs/llms.txt", content)
        else:
            self.assertEqual(self.profile["documentation"]["mode"], "mcp")
            self.assertEqual(capability["type"], "mcp-server")
            self._assert_mcp_configuration(provider)

    def test_generated_skill_metadata_matches_host(self) -> None:
        project = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        if 'name = "agent-template-placeholder"' in project:
            self.skipTest("source template retains metadata for distribution")
        metadata = list(self.root.glob("skills/*/agents/openai.yaml"))
        if self.profile["host"] == "codex":
            skill_count = len(list(self.root.glob("skills/*/SKILL.md")))
            self.assertEqual(len(metadata), skill_count)
        else:
            self.assertEqual(metadata, [])

    def test_runtime_adapter_is_implemented(self) -> None:
        self.assertIn(self.profile["runtime"]["adapter"], {"none", "reference"})

    def _assert_mcp_configuration(self, provider: str) -> None:
        server_id, url = MCP_SERVERS[provider]
        host = self.profile["host"]
        if host == "codex":
            payload = tomllib.loads(
                (self.root / ".codex" / "config.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["mcp_servers"][server_id]["url"], url)
        elif host == "claude-code":
            payload = json.loads((self.root / ".mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["mcpServers"][server_id], {"type": "http", "url": url})
        elif host == "gemini-cli":
            payload = json.loads(
                (self.root / ".gemini" / "settings.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["mcpServers"][server_id], {"httpUrl": url})
        else:
            self.fail("MCP documentation cannot be configured for the portable host")


if __name__ == "__main__":
    unittest.main()
