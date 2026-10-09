"""Publication metadata checks, without a GUI or Git checkout requirement. GPLv2."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


class RepositoryMetadataTest(unittest.TestCase):
    def test_milestone_versions_are_consistent(self):
        version = json.loads((ROOT / "package.json").read_text())["version"]
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual(lock["version"], version)
        self.assertEqual(lock["packages"][""]["version"], version)
        server = (ROOT / "src/server.ts").read_text()
        bridge = (ROOT / "vendor/libresprite/src/app/automation/bridge.cpp").read_text()
        self.assertIn(f'version: "{version}"', server)
        self.assertIn(f'{{"bridgeVersion", "{version}"}}', bridge)
        self.assertIn(f"Source alpha — v{version}", (ROOT / "README.md").read_text())

    def test_tool_catalog_matches_native_methods_and_documentation(self):
        server = (ROOT / "src/server.ts").read_text()
        bridge = (ROOT / "vendor/libresprite/src/app/automation/bridge.cpp").read_text()
        tools = re.findall(r'registerTool\("(libresprite_[a-z_]+)"', server)
        for operations in re.findall(r'for \(const operation of \[([^]]+)\] as const\) server.registerTool\(`libresprite_\$\{operation\}`', server):
            tools.extend("libresprite_" + operation for operation in re.findall(r'"([a-z_]+)"', operations))
        self.assertEqual(len(tools), len(set(tools)))
        block = re.search(r'static const std::vector<std::string> methods = \{([^}]+)\}', bridge).group(1)
        methods = set(re.findall(r'"([a-z_]+)"', block))
        expected = ({tool[len("libresprite_"):] for tool in tools} - {"launch", "connect"}) | {"status"}
        self.assertEqual(methods, expected)
        docs = (ROOT / "docs/live-bridge.md").read_text()
        self.assertIn(f"**{len(tools)} tools**", docs)
        for tool in tools:
            with self.subTest(tool=tool):
                self.assertIn(tool, docs)

    def test_full_gpl_text_matches_preserved_upstream_copy(self):
        self.assertEqual((ROOT / "LICENSE").read_bytes(), (ROOT / "vendor/libresprite/LICENSE.txt").read_bytes())
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["license"], "GPL-2.0-only")

    def test_credits_link_to_existing_license_and_provenance_files(self):
        credits = (ROOT / "CREDITS.md").read_text()
        links = re.findall(r"\]\(([^)]+)\)", credits)
        relative = [link.split("#", 1)[0] for link in links if not link.startswith(("https://", "http://", "#"))]
        self.assertGreater(len(relative), 10)
        for link in relative:
            with self.subTest(link=link):
                self.assertTrue((ROOT / link).is_file(), link)

    def test_client_examples_are_portable_and_use_documented_shapes(self):
        standard = json.loads((ROOT / "examples/mcp/stdio.json").read_text())
        opencode = json.loads((ROOT / "examples/mcp/opencode.json").read_text())
        path = "/absolute/path/to/libresprite-ai-mcp/dist/index.js"
        self.assertEqual(standard["mcpServers"]["libresprite"], {"command": "node", "args": [path]})
        self.assertEqual(opencode["$schema"], "https://opencode.ai/config.json")
        self.assertEqual(opencode["mcp"]["servers"]["libresprite"], {"type": "local", "command": ["node", path]})
        self.assertNotIn("libresprite", opencode["mcp"])
        for filename in ("stdio.json", "opencode.json"):
            text = (ROOT / "examples/mcp" / filename).read_text()
            self.assertNotIn("/Users/", text)
            self.assertNotIn("/home/", text)


if __name__ == "__main__":
    unittest.main()
