"""GUI-independent packaging/parser/privacy/integrity checks. GPLv2."""
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


PACKAGE = module("packager", "scripts/package-macos.py")
VERIFY = module("verify_package", "scripts/package/verify-package.py")


class PackagingTest(unittest.TestCase):
    def test_macho_load_parser_preserves_spaces_and_skips_install_id(self):
        text = """binary:
Load command 0
      cmd LC_ID_DYLIB
     name /old/self.dylib (offset 24)
Load command 1
      cmd LC_LOAD_DYLIB
     name /path with spaces/libexample.dylib (offset 24)
Load command 2
      cmd LC_RPATH
     path @loader_path/../Frameworks (offset 12)
Load command 3
      cmd LC_BUILD_VERSION
 platform 1
    minos 26.0
      sdk 26.5
Load command 4
      cmd LC_LOAD_WEAK_DYLIB
     name /usr/lib/libSystem.B.dylib (offset 24)
Load command 5
      cmd LC_VERSION_MIN_MACOSX
  version 14.0
"""
        dependencies, rpaths, minimum = PACKAGE.loads(text)
        self.assertEqual(dependencies, ["/path with spaces/libexample.dylib", "/usr/lib/libSystem.B.dylib"])
        self.assertEqual(rpaths, ["@loader_path/../Frameworks"])
        self.assertEqual(minimum, ["26.0", "14.0"])

    def test_library_resolution_local_rpaths_system_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            library = root / "lib with spaces/test.dylib"
            library.parent.mkdir()
            library.write_bytes(b"test")
            executable = root / "bin/editor"
            executable.parent.mkdir()
            self.assertEqual(PACKAGE.resolve_dependency("@rpath/test.dylib", executable, executable, ["@loader_path/../lib with spaces"]), library)
            self.assertIsNone(PACKAGE.resolve_dependency("/usr/lib/libSystem.B.dylib", executable, executable, []))
            with self.assertRaises(RuntimeError):
                PACKAGE.resolve_dependency("@rpath/missing.dylib", executable, executable, [])

    def test_installed_recipe_not_current_brew_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            formula = Path(directory) / "Cellar/example/1.0"
            (formula / ".brew").mkdir(parents=True)
            (formula / ".brew/example.rb").write_text('class Example < Formula\n  url "https://example.org/v1.tar.gz"\n  sha256 "old-hash"\n  bottle do\n    sha256 "bottle-hash"\n  end\nend\n')
            info = PACKAGE.recipe_metadata(formula)
            self.assertEqual(info["version"], "1.0")
            self.assertEqual(info["sourceSHA256"], "old-hash")

    def test_archive_allowlist_privacy_and_no_git_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("src/index.ts", "assets/private.ase", "opencode.json", ".runtime/log", "docs/setup.md"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test")
            snapshot = {"sourceCommit": "abc123", "sourceDirty": False,
                        "sourceFiles": {name: PACKAGE.digest(root / name) for name in ("src/index.ts", "assets/private.ase", "opencode.json", ".runtime/log", "docs/setup.md")}}
            (root / "SOURCE-SNAPSHOT.json").write_text(json.dumps(snapshot))
            names = PACKAGE.source_paths(root)
            self.assertEqual(names, ["docs/setup.md", "src/index.ts"])
            self.assertFalse(PACKAGE.source_provenance(root)["sourceDirty"])
            archive = root / "source.tar.gz"
            hashes = PACKAGE.archive_source(root, archive, names)
            with tarfile.open(archive) as tar:
                self.assertEqual(set(tar.getnames()), {"libresprite-ai-mcp/docs/setup.md", "libresprite-ai-mcp/src/index.ts", "libresprite-ai-mcp/SOURCE-SNAPSHOT.json"})
                embedded = json.load(tar.extractfile("libresprite-ai-mcp/SOURCE-SNAPSHOT.json"))
                self.assertEqual(embedded["sourceFiles"], hashes)
                self.assertTrue(all(member.mtime == 0 for member in tar.getmembers()))
            (root / "src/index.ts").write_text("changed")
            self.assertTrue(PACKAGE.source_provenance(root)["sourceDirty"])

    def test_source_refuses_symlinks_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "secret").write_text("private")
            (root / "src/link.ts").symlink_to(root / "secret")
            for name in ("src/link.ts", "src/../../secret"):
                (root / "SOURCE-SNAPSHOT.json").write_text(json.dumps({"sourceFiles": {name: "hash"}}))
                with self.assertRaises(RuntimeError):
                    PACKAGE.source_paths(root)

    def test_content_integrity_tamper_extra_missing_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "binary"
            binary.write_bytes(b"original")
            link = root / "alias"
            link.symlink_to("binary")
            (root / "checksums.json").write_text(json.dumps({"files": {"binary": PACKAGE.digest(binary)}, "symlinks": {"alias": "binary"}}))
            VERIFY.verify(root)
            (root / ".DS_Store").write_bytes(b"finder")
            VERIFY.verify(root)
            binary.write_bytes(b"tampered")
            with self.assertRaises(RuntimeError):
                VERIFY.verify(root)
            binary.write_bytes(b"original")
            (root / "extra").write_text("new")
            with self.assertRaises(RuntimeError):
                VERIFY.verify(root)
            (root / "extra").unlink()
            link.unlink()
            link.symlink_to("../outside")
            with self.assertRaises(RuntimeError):
                VERIFY.verify(root)


if __name__ == "__main__":
    unittest.main()
