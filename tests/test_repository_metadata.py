"""Publication metadata checks, without a GUI or Git checkout requirement. GPLv2."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


class RepositoryMetadataTest(unittest.TestCase):
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
