"""Native GUI-independent sparse region correction regressions. GPL-2.0-only."""
import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class AnimationCorrectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".runtime").mkdir(exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(prefix="correction-unit-", dir=ROOT / ".runtime")
        root = Path(cls.directory.name)
        source = root / "correction.cpp"
        source.write_text('''#include "app/automation/animation_correction.h"
#include "nlohmann/json.hpp"
#include <iostream>
#include <vector>
int main() {
  nlohmann::json input; std::cin >> input;
  int w = input["width"], h = input["height"]; std::string bits = input["bits"];
  bool valid = app::automation::validCorrectionMask(w, h, bits);
  if (!input.contains("pixels")) { std::cout << nlohmann::json{{"valid", valid}}; return 0; }
  if (!valid) return 1;
  auto original = input["pixels"].get<std::vector<uint32_t>>(), pixels = original;
  int canvasWidth = input["canvasWidth"], x = input["x"], y = input["y"];
  auto read = [&](int xx, int yy) { return original.at(yy * canvasWidth + xx); };
  auto write = [&](int xx, int yy, uint32_t value) { pixels.at(yy * canvasWidth + xx) = value; };
  app::automation::translateCorrectionRegion(x, y, w, h, bits, input["dx"], input["dy"], input["copy"], input["clear"], read, write);
  std::cout << nlohmann::json{{"pixels", pixels}, {"original", original}};
}''')
        cls.executable = root / "correction-test"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++17", "-O2", "-I", str(ROOT / "vendor/libresprite/src"), "-I", str(ROOT / "vendor"), str(source), "-o", str(cls.executable)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def request(self, **params):
        result = subprocess.run([str(self.executable)], input=json.dumps(params), check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def translate(self, pixels, width, x, y, mask_width, mask_height, bits, dx, dy=0, copy=False, clear=0):
        result = self.request(pixels=pixels, canvasWidth=width, x=x, y=y, width=mask_width, height=mask_height, bits=bits, dx=dx, dy=dy, copy=copy, clear=clear)
        self.assertEqual(result["original"], pixels)
        return result["pixels"]

    def test_overlapping_move_and_copy_read_original_pixels(self):
        self.assertEqual(self.translate([10, 20, 30, 40, 50], 5, 1, 0, 2, 1, "11", 1), [10, 0, 20, 30, 50])
        self.assertEqual(self.translate([10, 20, 30, 40, 50], 5, 1, 0, 2, 1, "11", 1, copy=True), [10, 20, 20, 30, 50])
        self.assertEqual(self.translate([10, 20, 30, 40, 50], 5, 2, 0, 2, 1, "11", -1), [10, 30, 40, 0, 50])

    def test_sparse_holes_and_transparent_destination_replacement(self):
        self.assertEqual(self.translate([1, 0, 3, 4, 5, 6], 6, 1, 0, 3, 1, "101", 1, copy=True), [1, 0, 0, 4, 4, 6])
        self.assertEqual(self.translate([1, 7, 3, 4, 5, 6], 6, 1, 0, 3, 1, "101", 1, clear=7), [1, 7, 7, 7, 4, 6])

    def test_zero_translation_and_raw_color_values(self):
        original = [0xff030201, 0x80402010, 0x00010203, 0x1234, 7, 255]
        for copy in (True, False):
            self.assertEqual(self.translate(original, 3, 0, 0, 3, 2, "101011", 0, copy=copy), original)
        self.assertEqual(self.translate(original, 3, 0, 0, 3, 1, "111", 0, dy=1, copy=True)[3:], original[:3])

    def test_mask_validation_and_size_limits(self):
        for w, h, bits in ((0, 1, "1"), (1, 0, "1"), (1025, 1, "1"), (1, 1, ""), (1, 1, "0"), (1, 1, "x"), (2, 2, "111"), (1024, 257, "1" * (1024 * 257))):
            self.assertFalse(self.request(width=w, height=h, bits=bits)["valid"])
        self.assertTrue(self.request(width=1024, height=256, bits="1" + "0" * 262143)["valid"])

    def test_randomized_sparse_regions_match_independent_reference(self):
        rng = random.Random(20261009)
        for _ in range(24):
            original = [rng.choice([0, 7, 0xff000001, 0x80000200]) for _ in range(30)]
            bits = "1" + "".join(rng.choice("01") for _ in range(5))
            dx, dy, copy = rng.choice([-1, 0, 1, 2]), rng.choice([-1, 0, 1, 2]), rng.choice([True, False])
            expected = original[:]
            selected = [(1 + i % 3, 1 + i // 3) for i, bit in enumerate(bits) if bit == "1"]
            if not copy:
                for x, y in selected:
                    expected[y * 6 + x] = 0
            for x, y in selected:
                expected[(y + dy) * 6 + x + dx] = original[y * 6 + x]
            self.assertEqual(self.translate(original, 6, 1, 1, 3, 2, bits, dx, dy, copy), expected)
