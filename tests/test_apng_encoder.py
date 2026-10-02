"""Compile/test the reusable native APNG assembler without starting the GUI."""
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMOKE = load("smoke", "smoke-test-libresprite.py")
CHECKS = load("animations", "animation_checks.py")


class ApngEncoderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".runtime").mkdir(mode=0o700, exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(prefix="apng-test-", dir=ROOT / ".runtime")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.path = Path(cls.directory.name)
        cls.executable = cls.path / "encode"
        subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-I" + str(ROOT / "vendor/libresprite/src"), str(ROOT / "tests/apng_encoder_driver.cpp"), str(ROOT / "vendor/libresprite/src/app/automation/apng.cpp"), "-lz", "-o", str(cls.executable)], check=True, capture_output=True, timeout=30)

    def fixture(self, name="fixture.png", width=2, height=1, split=False):
        path = self.path / name
        rgba = bytes((30, 70, 90, 128)) * width * height
        rows = b"".join(b"\0" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
        compressed = zlib.compress(rows)
        idat = SMOKE.chunk(b"IDAT", compressed)
        if split:
            middle = len(compressed) // 2
            idat = SMOKE.chunk(b"IDAT", compressed[:middle]) + SMOKE.chunk(b"IDAT", compressed[middle:])
        path.write_bytes(SMOKE.SIGNATURE + SMOKE.chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + idat + SMOKE.chunk(b"IEND", b""))
        return path

    def encode(self, frames, count=None, loop=True):
        output = self.path / "output.apng"
        output.unlink(missing_ok=True)
        args = [str(self.executable), str(output), str(count if count is not None else len(frames)), str(int(loop))]
        for path, duration in frames:
            args.extend((str(path), str(duration)))
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return result, output

    def test_native_multichunk_frames_exact_pixels_delays_and_loop(self):
        first = self.fixture(split=True)
        second = self.fixture("second.png")
        result, output = self.encode([(first, 1), (second, 65535), (first, 157)])
        self.assertEqual(result.returncode, 0, result.stderr)
        decoded = CHECKS.read_apng(output, SMOKE)
        self.assertEqual(decoded["durations"], [1, 65535, 157])
        self.assertEqual(decoded["plays"], 0)
        self.assertEqual(decoded["frames"], [SMOKE.read_png(first), SMOKE.read_png(second), SMOKE.read_png(first)])
        result, output = self.encode([(first, 100)], loop=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(CHECKS.read_apng(output, SMOKE)["plays"], 1)

    def test_refuses_mismatched_truncated_corrupt_and_non_rgba_frames(self):
        first = self.fixture()
        different = self.fixture("different.png", width=1)
        result, output = self.encode([(first, 100), (different, 100)])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        valid = first.read_bytes()
        mutations = [valid[:20], valid[:-12], b"not png", valid + b"trailing"]
        corrupt = bytearray(valid)
        corrupt[16] ^= 1
        mutations.append(bytes(corrupt))
        header = struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0)
        mutations.append(SMOKE.SIGNATURE + SMOKE.chunk(b"IHDR", header) + valid[33:])
        for data in mutations:
            with self.subTest(data=data[:20]):
                first.write_bytes(data)
                result, output = self.encode([(first, 100)])
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

    def test_frame_count_duration_and_canvas_bounds(self):
        first = self.fixture()
        for count, durations in ((0, [100]), (511, [100]), (2, [100]), (1, [100, 100]), (1, [0]), (1, [65536])):
            with self.subTest(count=count, durations=durations):
                result, output = self.encode([(first, duration) for duration in durations], count=count)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())
        wide = self.fixture("wide.png", width=1048577, height=1)
        result, output = self.encode([(wide, 100)])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_encoded_byte_limit_refuses_before_output_publication(self):
        # Valid incompressible-equivalent RGBA data at the legal pixel ceiling;
        # stored deflate blocks force the encoded 8-frame file over 32 MiB.
        path = self.path / "stored.png"
        header = struct.pack(">IIBBBBB", 1024, 1024, 8, 6, 0, 0, 0)
        rows = (b"\0" + bytes((30, 70, 90, 255)) * 1024) * 1024
        path.write_bytes(SMOKE.SIGNATURE + SMOKE.chunk(b"IHDR", header) + SMOKE.chunk(b"IDAT", zlib.compress(rows, level=0)) + SMOKE.chunk(b"IEND", b""))
        result, output = self.encode([(path, 100)] * 8)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("32 MiB", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
