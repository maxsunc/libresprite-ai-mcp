"""GUI-independent PE dependency closure tests. GPLv2."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("windows_packager", ROOT / "scripts/package-windows.py")
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class WindowsPackagingTest(unittest.TestCase):
    def test_pe_import_parser(self):
        self.assertEqual(PACKAGE.pe_imports(" DLL Name: KERNEL32.dll\n DLL Name: SDL2.dll\n"), ["KERNEL32.dll", "SDL2.dll"])
        for invalid in ("../bad.dll", "C:\\bad.dll", "sub/bad.dll"):
            with self.assertRaises(RuntimeError):
                PACKAGE.pe_imports("DLL Name: " + invalid)

    def test_transitive_dlls_cycles_system_and_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix, system = root / "ucrt64", root / "System32"
            (prefix / "bin").mkdir(parents=True)
            system.mkdir()
            (system / "kernel32.dll").touch()
            exe = root / "editor.exe"
            exe.touch()
            for name in ("a.dll", "b.dll"):
                (prefix / "bin" / name).touch()
            imports = {"editor.exe": ["A.dll", "kernel32.dll", "api-ms-win-test.dll"], "a.dll": ["b.dll"], "b.dll": ["a.dll"]}
            binaries = PACKAGE.dll_closure(exe, prefix, lambda p: imports[p.name], system)
            self.assertEqual({p.name for p in binaries}, {"editor.exe", "a.dll", "b.dll"})
            imports["b.dll"].append("not-installed.dll")
            with self.assertRaisesRegex(RuntimeError, "Unresolved runtime DLL"):
                PACKAGE.dll_closure(exe, prefix, lambda p: imports[p.name], system)
