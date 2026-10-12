"""GUI-independent native pixel-region helper tests. GPL-2.0-only."""
import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class PixelRegionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".runtime").mkdir(exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(prefix="pixel-unit-", dir=ROOT / ".runtime")
        root = Path(cls.directory.name)
        source = root / "pixels.cpp"
        source.write_text('''#include "app/automation/pixel_regions.h"
#include <iostream>
#include <vector>
int main() {
  nlohmann::json p; std::cin >> p;
  int w = p["width"], h = p["height"]; auto values = p["values"].get<std::vector<uint32_t>>();
  try { std::cout << nlohmann::json{{"rows", app::automation::pixelRows(w,h,p["encoding"], [&](int x,int y){return values.at(y*w+x);})}}; }
  catch (const std::invalid_argument&) { std::cout << nlohmann::json{{"invalid",true}}; }
}''')
        cls.executable = root / "pixels"
        subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++17", "-O2", "-I", str(ROOT / "vendor/libresprite/src"), str(source), "-o", str(cls.executable)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def request(self, **params):
        return json.loads(subprocess.run([str(self.executable)], input=json.dumps(params), check=True, capture_output=True, text=True).stdout)

    def test_complete_rows_unsigned_values_and_run_boundaries(self):
        values = [0, 0, 0xffffffff, 0xffffffff, 0xffffffff, 0x00030201, 7, 7]
        self.assertEqual(self.request(width=4, height=2, values=values, encoding="values")["rows"], [values[:4], values[4:]])
        self.assertEqual(self.request(width=4, height=2, values=values, encoding="runs")["rows"], [[[2, 0], [2, 0xffffffff]], [[1, 0xffffffff], [1, 0x00030201], [2, 7]]])

    def test_randomized_run_round_trips(self):
        rng = random.Random(20261011)
        for _ in range(20):
            w, h = rng.randint(1, 32), rng.randint(1, 8)
            values = [rng.choice([0, 7, 0x80010203, 0x00030201, 65535]) for _ in range(w * h)]
            rows = self.request(width=w, height=h, values=values, encoding="runs")["rows"]
            self.assertEqual([v for row in rows for n, v in row for _ in range(n)], values)
            self.assertTrue(all(sum(n for n, _ in row) == w for row in rows))

    def test_sample_and_encoding_limits(self):
        for w, h, encoding in ((0, 1, "runs"), (1025, 1, "values"), (1024, 17, "runs"), (1, 1, "bad")):
            self.assertTrue(self.request(width=w, height=h, values=[], encoding=encoding)["invalid"])
        rows = self.request(width=1024, height=16, values=[7] * 16384, encoding="runs")["rows"]
        self.assertEqual(rows, [[[1024, 7]]] * 16)
