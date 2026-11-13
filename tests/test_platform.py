"""Native OS boundaries: atomic files, Windows pipe ACL/exclusivity/reconnect. GPLv2."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class PlatformTest(unittest.TestCase):
    def test_native_platform_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="ls platform ") as directory:
            root = Path(directory)
            executable = root / ("platform.exe" if os.name == "nt" else "platform")
            command = [*shlex.split(os.environ.get("CXX", "c++")), "-std=c++20", "-I", str(ROOT / "vendor/libresprite/src"), str(ROOT / "tests/platform_driver.cpp"), "-o", str(executable)]
            if os.name == "nt":
                command += ["-D_WIN32_WINNT=0x0A00", "-ladvapi32"]
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
            subprocess.run([str(executable), str(root)], check=True, capture_output=True, text=True, timeout=15)
