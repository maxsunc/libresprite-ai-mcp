#!/usr/bin/env python3
"""Import a pinned, complete upstream snapshot without nested Git repositories."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache/upstream/libresprite"
DESTINATION = ROOT / "vendor/libresprite"
MANIFEST = ROOT / "vendor/libresprite.upstream.json"
REPOSITORY = "https://github.com/LibreSprite/LibreSprite.git"
REF = "v1.2"
COMMIT = "5cb089be32f56b4ae559ae51f0c5666049f41bca"
# Upstream accidentally tracks a generated, compiler-specific precompiled header.
EXCLUDED_PATHS = {"src/config.h.gch"}


def git(directory, *arguments):
    return subprocess.check_output(["git", "-C", str(directory), *arguments])


def repositories():
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", REF, "--depth", "1",
             "--recurse-submodules", REPOSITORY, str(CACHE)],
            check=True,
        )
    if git(CACHE, "rev-parse", "HEAD").decode().strip() != COMMIT:
        raise RuntimeError("Cached upstream checkout does not match the pinned commit.")

    result = [(Path(), CACHE, COMMIT, REPOSITORY)]
    for line in git(CACHE, "submodule", "status", "--recursive").decode().splitlines():
        if not line.startswith(" "):
            raise RuntimeError("Missing or mismatched dependency submodule: " + line)
        revision, path = line[1:].split()[:2]
        directory = CACHE / path
        url = git(directory, "remote", "get-url", "origin").decode().strip()
        result.append((Path(path), directory, revision, url))

    for _, directory, _, _ in result:
        if git(directory, "status", "--porcelain", "--untracked-files=no").strip():
            raise RuntimeError("Upstream checkout has modifications: " + str(directory))
    return result


def source_files(checkouts):
    result = []
    for prefix, directory, _, _ in checkouts:
        for entry in git(directory, "ls-files", "--stage", "-z").split(b"\0"):
            if not entry:
                continue
            metadata, filename = entry.split(b"\t", 1)
            mode, _, stage = metadata.decode().split()
            if stage != "0":
                raise RuntimeError("Unmerged upstream file: " + os.fsdecode(filename))
            if mode == "160000":
                continue
            path = Path(os.fsdecode(filename))
            relative = prefix / path
            if relative.as_posix() not in EXCLUDED_PATHS:
                result.append((relative, directory / path))
    return result


def verify(files):
    differences = []
    expected = set()
    for relative, source in files:
        expected.add(relative)
        destination = DESTINATION / relative
        if source.is_symlink():
            matches = destination.is_symlink() and os.readlink(source) == os.readlink(destination)
        else:
            matches = (
                destination.is_file()
                and not destination.is_symlink()
                and source.read_bytes().replace(b"\r\n", b"\n") == destination.read_bytes().replace(b"\r\n", b"\n")
                and bool(source.stat().st_mode & 0o111) == bool(destination.stat().st_mode & 0o111)
            )
        if not matches:
            differences.append(str(relative))
    if DESTINATION.exists():
        for path in DESTINATION.rglob("*"):
            if (path.is_file() or path.is_symlink()) and path.relative_to(DESTINATION) not in expected:
                differences.append("Unexpected file: " + str(path.relative_to(DESTINATION)))
    if differences:
        raise RuntimeError("Snapshot differs from upstream:\n" + "\n".join(differences))
    print("Verified {} imported files against {} ({}), allowing Git CRLF/LF normalization.".format(len(files), REF, COMMIT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Compare the snapshot to upstream; do not overwrite it.")
    arguments = parser.parse_args()
    if not arguments.verify and (DESTINATION.exists() or MANIFEST.exists()):
        raise RuntimeError("An import already exists. Refusing to overwrite source or local changes.")
    checkouts = repositories()
    files = source_files(checkouts)
    if arguments.verify:
        verify(files)
        return
    DESTINATION.mkdir(parents=True)
    for relative, source in files:
        destination = DESTINATION / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)

    manifest = {
        "repository": REPOSITORY,
        "ref": REF,
        "commit": COMMIT,
        "import_method": "Tracked source files with dependency submodules materialized as ordinary files",
        "excluded_paths": sorted(EXCLUDED_PATHS),
        "file_count": len(files),
        "submodules": [
            {"path": str(prefix), "commit": revision, "repository": url}
            for prefix, _, revision, url in checkouts[1:]
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    verify(files)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
