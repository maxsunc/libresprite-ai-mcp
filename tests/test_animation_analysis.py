"""Native, GUI-independent visual animation measurements. GPL-2.0-only."""
import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class AnimationAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".runtime").mkdir(exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(prefix="analysis-unit-", dir=ROOT / ".runtime")
        root = Path(cls.directory.name)
        # doc/color.h only needs inline stdint arithmetic. Supply an empty config
        # rather than requiring a configured GUI/native build in helper CI.
        (root / "base").mkdir()
        (root / "base/config.h").write_text("// No platform configuration needed by doc/color.h.\n")
        source = root / "analysis.cpp"
        source.write_text('''#include "app/automation/animation_analysis.h"
#include <iostream>
int main() {
  nlohmann::json input; std::cin >> input;
  if (input.contains("exposures")) {
    std::vector<std::pair<int, int>> exposures;
    for (const auto& item : input["exposures"]) exposures.push_back({item[0], item[1]});
    try { std::cout << app::automation::animationTiming(exposures).dump(); }
    catch (const std::invalid_argument& error) { std::cout << nlohmann::json{{"error", error.what()}}.dump(); }
    return 0;
  }
  app::automation::FrameDifference difference;
  nlohmann::json pixels = nlohmann::json::array();
  int width = input["width"], height = input["height"];
  for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
    size_t i = y * width + x;
    pixels.push_back(difference.add(x, y, input["before"][i], input["after"][i]));
  }
  std::cout << nlohmann::json{{"difference", difference.json()}, {"pixels", pixels}}.dump();
}''')
        cls.executable = root / "analysis-test"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++17", "-O2", "-I", str(root), "-I", str(ROOT / "vendor/libresprite/src"), str(source), "-o", str(cls.executable)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def analyze(self, before, after, width, height=1):
        result = subprocess.run([str(self.executable)], input=json.dumps({"width": width, "height": height, "before": before, "after": after}), check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_added_removed_modified_alpha_and_unchanged(self):
        result = self.analyze([0, 0xff000001, 0xff000002, 0x80000003, 0xff000004], [0xff000001, 0, 0xff000003, 0x40000003, 0xff000004], 5)
        diff = result["difference"]
        self.assertEqual([diff[key] for key in ("addedPixels", "removedPixels", "modifiedPixels", "changedPixels", "unchangedPixels", "totalPixels")], [1, 1, 2, 4, 1, 5])
        self.assertEqual(diff["changedFraction"], 0.8)
        self.assertEqual(diff["bounds"], {"x": 0, "y": 0, "width": 4, "height": 1})
        self.assertEqual(result["pixels"], [0xff5ac828, 0xff4646f0, 0xff28c8ff, 0xff28c8ff, 0])

    def test_transparent_payload_is_not_a_visual_change(self):
        result = self.analyze([0x00010203, 0], [0x00040506, 0x00ffffff], 2)
        self.assertEqual(result["pixels"], [0, 0])
        self.assertEqual(result["difference"]["changedPixels"], 0)
        for key in ("before", "after"):
            self.assertEqual(result["difference"][key], {"visiblePixels": 0, "bounds": None, "centroid": None})
        self.assertIsNone(result["difference"]["bounds"])

    def test_sparse_bounds_centroid_and_semitransparent_alpha(self):
        before = [0] * 12
        before[1], before[11] = 0x01000001, 0xff000002
        diff = self.analyze(before, before, 4, 3)["difference"]
        self.assertEqual(diff["before"], {"visiblePixels": 2, "bounds": {"x": 1, "y": 0, "width": 3, "height": 3}, "centroid": {"x": 2, "y": 1}})
        self.assertEqual(diff["before"], diff["after"])
        self.assertEqual(diff["unchangedPixels"], 12)

    def test_randomized_counts_match_independent_reference(self):
        rng = random.Random(20261009)
        for _ in range(12):
            width, height = 7, 5
            before = [rng.choice([0, 0x00ffffff, 0xff000001, 0x80000002]) for _ in range(width * height)]
            after = [rng.choice([0, 0x00abcdef, 0xff000001, 0x40000002]) for _ in before]
            counts = {"addedPixels": 0, "removedPixels": 0, "modifiedPixels": 0}
            changed = []
            for i, (a, b) in enumerate(zip(before, after)):
                if (not a >> 24 and not b >> 24) or a == b:
                    continue
                changed.append((i % width, i // width))
                counts["addedPixels" if not a >> 24 else "removedPixels" if not b >> 24 else "modifiedPixels"] += 1
            diff = self.analyze(before, after, width, height)["difference"]
            for key, value in counts.items():
                self.assertEqual(diff[key], value)
            self.assertEqual(diff["changedPixels"], len(changed))
            self.assertEqual(diff["bounds"], {"x": min(x for x, y in changed), "y": min(y for x, y in changed), "width": max(x for x, y in changed) - min(x for x, y in changed) + 1, "height": max(y for x, y in changed) - min(y for x, y in changed) + 1})

    def timing(self, exposures):
        result = subprocess.run([str(self.executable)], input=json.dumps({"exposures": exposures}), check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_ordered_repeated_exposures_and_exact_timeline(self):
        result = self.timing([[2, 90], [0, 20], [1, 60], [0, 20]])
        self.assertEqual([step["frame"] for step in result["steps"]], [2, 0, 1, 0])
        self.assertEqual([step["startMs"] for step in result["steps"]], [0, 90, 110, 170])
        self.assertEqual([step["endMs"] for step in result["steps"]], [90, 110, 170, 190])
        self.assertEqual(result["summary"]["totalDurationMs"], 190)
        self.assertEqual(result["summary"]["minDurationMs"], 20)
        self.assertEqual(result["summary"]["maxDurationMs"], 90)
        self.assertAlmostEqual(result["summary"]["effectiveFps"], 4000 / 190)
        self.assertFalse(result["summary"]["uniformDurations"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["gif"]["encodedTotalDurationMs"], 190)

    def test_gif_quantization_and_unexportable_short_delays(self):
        result = self.timing([[0, 91], [1, 119]])
        self.assertEqual(result["gif"], {"exportable": True, "delayQuantumMs": 10, "encodedTotalDurationMs": 200, "totalShorteningMs": 10})
        self.assertEqual([item["code"] for item in result["warnings"]], ["GIF_DELAY_QUANTIZED"] * 2)
        result = self.timing([[0, 1], [1, 9], [2, 10], [3, 65535]])
        self.assertFalse(result["gif"]["exportable"])
        self.assertIsNone(result["gif"]["encodedTotalDurationMs"])
        self.assertIsNone(result["gif"]["totalShorteningMs"])
        self.assertEqual([item["code"] for item in result["warnings"]], ["GIF_DELAY_TOO_SHORT", "GIF_DELAY_TOO_SHORT", "GIF_DELAY_QUANTIZED"])
        self.assertEqual([step["gifDurationMs"] for step in result["steps"]], [0, 0, 10, 65530])

    def test_single_uniform_and_maximum_playback_timing(self):
        result = self.timing([[0, 100]])
        self.assertTrue(result["summary"]["uniformDurations"])
        self.assertEqual(result["summary"]["effectiveFps"], 10)
        result = self.timing([[255, 65535]] * 510)
        self.assertEqual(result["summary"]["totalDurationMs"], 65535 * 510)
        self.assertEqual(result["steps"][-1]["endMs"], 65535 * 510)

    def test_timing_input_bounds(self):
        for exposures in ([], [[0, 100]] * 511, [[0, 0]], [[0, 65536]], [[-1, 100]], [[256, 100]]):
            with self.subTest(exposures=exposures[:2]):
                self.assertIn("error", self.timing(exposures))
