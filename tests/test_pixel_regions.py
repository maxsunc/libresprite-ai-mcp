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
  int w = p["width"], h = p["height"];
  try {
    if (p.contains("bits")) std::cout << nlohmann::json{{"bits", app::automation::componentMask(w,h,p["bits"],p["seedX"],p["seedY"],p["connectivity"])}};
    else { auto values = p["values"].get<std::vector<uint32_t>>(); std::cout << nlohmann::json{{"rows", app::automation::pixelRows(w,h,p["encoding"], [&](int x,int y){return values.at(y*w+x);})}}; }
  }
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

    def test_components_empty_seeds_diagonals_holes_and_bounds(self):
        params = dict(width=3, height=3, bits="100010001", seedX=0, seedY=0)
        self.assertEqual(self.request(**params, connectivity=4)["bits"], "100000000")
        self.assertEqual(self.request(**params, connectivity=8)["bits"], params["bits"])
        self.assertEqual(self.request(**{**params, "seedX": 1}, connectivity=8)["bits"], "0" * 9)
        self.assertEqual(self.request(width=3, height=3, bits="111101111", seedX=0, seedY=0, connectivity=4)["bits"], "111101111")
        for changes in ({"bits": "bad"}, {"seedX": 3}, {"seedY": -1}, {"connectivity": 6}, {"width": 1024, "height": 257, "bits": "1" * (1024 * 257)}):
            self.assertTrue(self.request(**{**params, "connectivity": 4, **changes})["invalid"])
        self.assertEqual(self.request(width=512, height=512, bits="1" * 262144, seedX=0, seedY=0, connectivity=4)["bits"], "1" * 262144)

    def test_randomized_components_match_independent_reference(self):
        rng = random.Random(21102026)
        for _ in range(20):
            w, h = 8, 7; bits = "".join(rng.choice("01") for _ in range(w * h))
            x, y, connectivity = rng.randrange(w), rng.randrange(h), rng.choice([4, 8])
            selected, pending = set(), [(x, y)]
            while pending:
                point = pending.pop(); xx, yy = point
                if point in selected or not (0 <= xx < w and 0 <= yy < h) or bits[yy * w + xx] != "1":
                    continue
                selected.add(point)
                pending.extend((xx + dx, yy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and (connectivity == 8 or not (dx and dy)))
            expected = "".join("1" if (i % w, i // w) in selected else "0" for i in range(w * h))
            self.assertEqual(self.request(width=w, height=h, bits=bits, seedX=x, seedY=y, connectivity=connectivity)["bits"], expected)
