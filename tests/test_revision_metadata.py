"""Native revision bookkeeping regression. GPL-2.0-only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class RevisionMetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".runtime").mkdir(exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(prefix="revision-unit-", dir=ROOT / ".runtime")
        path = Path(cls.directory.name)
        source = path / "revision.cpp"
        source.write_text('''#include "app/automation/revision_metadata.h"
#include <iostream>
int main() {
  nlohmann::json original; std::cin >> original;
  std::cout << nlohmann::json{{"normalized", app::automation::revisionMetadata(original)}, {"original", original}}.dump();
}''')
        cls.executable = path / "revision-test"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++17", "-O2", "-I", str(ROOT / "vendor/libresprite/src"), str(source), "-o", str(cls.executable)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def metadata(self):
        return {"layers": [{"version": 0, "layerId": 2, "visible": True, "cels": [{"frame": 0, "imageVersion": 0, "imageId": 3, "opacity": 255, "x": 0, "links": 0}]}], "frames": [{"frame": 0, "durationMs": 100}], "selection": {"visible": False}}

    def normalize(self, metadata):
        result = json.loads(subprocess.run([str(self.executable)], input=json.dumps(metadata), check=True, capture_output=True, text=True).stdout)
        self.assertEqual(result["original"], metadata, "Fingerprinting must not mutate native state.")
        return result["normalized"]

    def test_initial_recovery_versions_are_equivalent(self):
        before = self.metadata()
        recovered = copy.deepcopy(before)
        recovered["layers"][0]["version"] = 1
        recovered["layers"][0]["cels"][0]["imageVersion"] = 1
        self.assertEqual(self.normalize(before), self.normalize(recovered))

    def test_higher_versions_still_detect_changes(self):
        before = self.metadata()
        for layer_version, image_version in ((2, 0), (0, 2), (100, 100)):
            changed = copy.deepcopy(before)
            changed["layers"][0]["version"] = layer_version
            changed["layers"][0]["cels"][0]["imageVersion"] = image_version
            self.assertNotEqual(self.normalize(before), self.normalize(changed))

    def test_actual_first_edit_properties_are_not_hidden(self):
        before = self.metadata()
        for key, value in (("opacity", 100), ("x", 12), ("imageId", 4), ("links", 1), ("celId", 5), ("celDataId", 6), ("userData", {"text": "first edit", "color": 0})):
            changed = copy.deepcopy(before)
            changed["layers"][0]["cels"][0]["imageVersion"] = 1
            changed["layers"][0]["cels"][0][key] = value
            self.assertNotEqual(self.normalize(before), self.normalize(changed))
        for key, value in (("continuous", True), ("movable", False), ("userData", {"text": "first layer edit", "color": 1234})):
            changed = copy.deepcopy(before)
            changed["layers"][0]["version"] = 1
            changed["layers"][0][key] = value
            self.assertNotEqual(self.normalize(before), self.normalize(changed))
        changed = copy.deepcopy(before)
        changed["frames"][0]["durationMs"] = 120
        self.assertNotEqual(self.normalize(before), self.normalize(changed))

    def test_groups_and_empty_cels_are_supported(self):
        metadata = {"layers": [{"layerId": 1, "version": 0}, {"layerId": 2, "version": 1, "cels": []}]}
        result = self.normalize(metadata)
        self.assertEqual([layer["version"] for layer in result["layers"]], [1, 1])

    def test_gui_refusal_comparison_matches_native_canonicalization(self):
        spec = importlib.util.spec_from_file_location("animation_cases", ROOT / "scripts/bridge_animation_cases.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        for layer_version, image_version in ((0, 0), (1, 1), (2, 0), (0, 2), (100, 100)):
            state = self.metadata()
            state["layers"][0]["version"] = layer_version
            state["layers"][0]["cels"][0]["imageVersion"] = image_version
            raw = copy.deepcopy(state)
            self.assertEqual(helper.canonical_inspection(state), self.normalize(state))
            self.assertEqual(state, raw)
