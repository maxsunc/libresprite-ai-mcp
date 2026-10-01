import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("native_smoke", ROOT / "scripts/smoke-test-libresprite.py")
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class PngHelpersTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.png"

    def write_png(self, width, height, color_type, rows, extra=b""):
        header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
        self.path.write_bytes(
            SMOKE.SIGNATURE
            + SMOKE.chunk(b"IHDR", header)
            + extra
            + SMOKE.chunk(b"IDAT", zlib.compress(rows))
            + SMOKE.chunk(b"IEND", b"")
        )

    def test_generated_fixture_round_trip(self):
        expected = SMOKE.write_fixture(self.path)
        self.assertEqual(SMOKE.read_png(self.path), expected)
        self.assertEqual(expected[:2], (16, 16))
        self.assertIn(bytes((0, 0, 0, 0)), expected[2])

    def test_all_rgba_scanline_filters(self):
        width = 2
        rows = [bytes((10, 20, 30, 255, 40, 50, 60, 128)), bytes((15, 10, 35, 200, 20, 80, 55, 255))]
        for method in range(5):
            with self.subTest(filter=method):
                encoded = bytearray()
                previous = bytes(width * 4)
                for row in rows:
                    encoded.append(method)
                    for x, value in enumerate(row):
                        left = row[x - 4] if x >= 4 else 0
                        above = previous[x]
                        diagonal = previous[x - 4] if x >= 4 else 0
                        if method == 0:
                            predictor = 0
                        elif method == 1:
                            predictor = left
                        elif method == 2:
                            predictor = above
                        elif method == 3:
                            predictor = (left + above) // 2
                        else:
                            p = left + above - diagonal
                            choices = (left, above, diagonal)
                            predictor = min(choices, key=lambda candidate: abs(p - candidate))
                        encoded.append((value - predictor) & 255)
                    previous = row
                self.write_png(width, 2, 6, bytes(encoded))
                self.assertEqual(SMOKE.read_png(self.path), (width, 2, b"".join(rows)))

    def test_rgb_adds_opaque_alpha(self):
        self.write_png(2, 1, 2, b"\0\x01\x02\x03\x04\x05\x06")
        self.assertEqual(SMOKE.read_png(self.path)[2], bytes((1, 2, 3, 255, 4, 5, 6, 255)))

    def test_palette_transparency(self):
        extra = SMOKE.chunk(b"PLTE", bytes((0, 0, 0, 100, 150, 200))) + SMOKE.chunk(b"tRNS", bytes((0, 255)))
        self.write_png(2, 1, 3, bytes((0, 0, 1)), extra)
        self.assertEqual(SMOKE.read_png(self.path)[2], bytes((0, 0, 0, 0, 100, 150, 200, 255)))

    def test_bad_checksum_is_rejected(self):
        SMOKE.write_fixture(self.path)
        data = bytearray(self.path.read_bytes())
        data[16] ^= 1
        self.path.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            SMOKE.read_png(self.path)

    def test_unknown_filter_is_rejected(self):
        self.write_png(1, 1, 6, bytes((5, 1, 2, 3, 4)))
        with self.assertRaisesRegex(RuntimeError, "Unknown PNG filter"):
            SMOKE.read_png(self.path)


class SourceImportTest(unittest.TestCase):
    def test_reimport_refuses_to_overwrite_existing_source(self):
        manifest = ROOT / "vendor/libresprite.upstream.json"
        before = manifest.read_bytes()
        result = subprocess.run(
            ["python3", str(ROOT / "scripts/vendor-libresprite.py")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite", result.stderr)
        self.assertEqual(manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
