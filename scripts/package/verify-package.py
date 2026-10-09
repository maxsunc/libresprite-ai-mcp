#!/usr/bin/env python3
"""Verify package content hashes, missing/extra files, and symlinks. GPLv2."""
import hashlib
import json
import os
from pathlib import Path
import sys


def verify(root):
    root = root.resolve()
    manifest = json.loads((root / "checksums.json").read_text())
    expected = set(manifest["files"]) | set(manifest["symlinks"]) | {"checksums.json"}
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    # Finder metadata is not package content; it may appear after extraction.
    actual = {p for p in actual if Path(p).name != ".DS_Store" and not Path(p).name.startswith("._")}
    if actual != expected:
        raise RuntimeError(f"Missing: {sorted(expected - actual)}; unexpected: {sorted(actual - expected)}")
    for name, checksum in manifest["files"].items():
        path = root / name
        if root not in path.resolve().parents or path.is_symlink():
            raise RuntimeError(f"Unsafe package file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise RuntimeError(f"Content checksum mismatch: {name}")
    for name, target in manifest["symlinks"].items():
        path = root / name
        if not path.is_symlink() or os.readlink(path) != target or root not in path.resolve().parents or not path.is_file():
            raise RuntimeError(f"Invalid package symlink: {name}")
    print(f"PASS: {len(manifest['files'])} package files and {len(manifest['symlinks'])} internal symlinks. Hashes are integrity checks, not proof of publisher identity.")


if __name__ == "__main__":
    try:
        verify(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
