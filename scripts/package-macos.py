#!/usr/bin/env python3
"""Build a relocatable Apple Silicon review package. GPL-2.0-only.

Never installs an app, changes client configuration, replaces output, or stops
an editor. Homebrew is a build-time input only. Not a notarized public release.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
IDENTIFIER = "io.github.maxsunc.libresprite-ai-mcp"
APP_NAME = "LibreSprite AI.app"
SYSTEM = ("/usr/lib/", "/System/Library/")
LICENSE_POLICIES = {
    "aom": "BSD-2-Clause", "brotli": "MIT", "dav1d": "BSD-2-Clause",
    "freetype": "GPL-2.0-only (upstream dual-license option)", "giflib": "MIT",
    "highway": "BSD-3-Clause (upstream dual-license option); retained component notices",
    "jpeg-turbo": "IJG AND Zlib AND BSD-3-Clause", "jpeg-xl": "BSD-3-Clause",
    "libarchive": "BSD-2-Clause; retained component notices", "libavif": "BSD-2-Clause",
    "libb2": "CC0-1.0", "libpng": "libpng-2.0", "libtiff": "libtiff",
    "libvmaf": "BSD-2-Clause-Patent", "little-cms2": "MIT", "lz4": "BSD-2-Clause (library only)",
    "pixman": "MIT", "sdl2-compat": "Zlib", "sdl2_image": "Zlib",
    "sdl3": "Zlib", "tinyxml2": "Zlib", "webp": "BSD-3-Clause",
    "xz": "0BSD (liblzma only, no xz command-line tools)",
    "zstd": "BSD-3-Clause (upstream dual-license option); retained component notices",
}


def run(*args, **kwargs):
    return subprocess.check_output(list(map(str, args)), text=True, **kwargs)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def loads(text):
    """Parse otool load commands, keeping spaces in paths."""
    dependencies, rpaths, minimum = [], [], []
    for block in re.split(r"Load command \d+\n", text)[1:]:
        command = re.search(r"^\s*cmd (\S+)", block, re.M)
        if not command:
            continue
        kind = command[1]
        if kind in ("LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB", "LC_LOAD_UPWARD_DYLIB"):
            dependencies.append(re.search(r"^\s*name (.+?) \(offset", block, re.M)[1])
        elif kind == "LC_RPATH":
            rpaths.append(re.search(r"^\s*path (.+?) \(offset", block, re.M)[1])
        elif kind in ("LC_BUILD_VERSION", "LC_VERSION_MIN_MACOSX"):
            match = re.search(r"^\s*(?:minos|version) (\d+(?:\.\d+)*)", block, re.M)
            if match:
                minimum.append(match[1])
    return dependencies, rpaths, minimum


def expand(value, source, executable):
    return value.replace("@loader_path", str(source.parent)).replace("@executable_path", str(executable.parent))


def resolve_dependency(value, source, executable, rpaths):
    if value.startswith(SYSTEM):
        return None
    if value.startswith("@rpath/"):
        candidates = [Path(expand(p, source, executable)) / value[7:] for p in rpaths]
    else:
        candidates = [Path(expand(value, source, executable))]
    for candidate in candidates:
        if candidate.is_absolute() and candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(f"Cannot resolve {value} from {source}; no dependencies are silently skipped.")


def graph(executable, runtime_libraries):
    pending = [executable, *runtime_libraries]
    result = {}
    executable_rpaths = loads(run("otool", "-l", executable))[1]
    while pending:
        source = pending.pop().resolve()
        if source in result:
            continue
        if run("lipo", "-archs", source).strip() != "arm64":
            raise RuntimeError(f"Expected arm64-only Mach-O: {source}")
        dependencies, rpaths, minimum = loads(run("otool", "-l", source))
        edges = {value: resolve_dependency(value, source, executable, rpaths + executable_rpaths) for value in dependencies}
        result[source] = {"edges": edges, "rpaths": rpaths, "minimum": minimum}
        pending.extend(target for target in edges.values() if target is not None)
    return result


def formula_directory(source):
    parts = source.parts
    if "Cellar" not in parts:
        raise RuntimeError(f"Unrecognized dependency provenance: {source}. This packager requires Homebrew-built libraries.")
    index = parts.index("Cellar")
    return Path(*parts[:index + 3])


def recipe_metadata(directory):
    name = directory.parent.name
    recipe = directory / ".brew" / f"{name}.rb"
    text = recipe.read_text()
    # The installed recipe, NOT today's brew API (which may describe a newer version).
    stable = text.split("  bottle do", 1)[0].split("  head ", 1)[0]
    def field(key):
        match = re.search(rf'^  {key} "([^"]+)"', stable, re.M)
        return match[1] if match else None
    return {"name": name, "version": directory.name, "sourceURL": field("url"),
            "sourceSHA256": field("sha256"), "mirror": field("mirror"), "recipe": recipe}


def fetch_source(metadata, cache):
    checksum = metadata["sourceSHA256"]
    if not checksum:
        raise RuntimeError(f"A checksum-pinned source archive is required for {metadata['name']}.")
    filename = Path(metadata["sourceURL"].split("?", 1)[0]).name
    target = cache / f"{checksum}-{filename}"
    if target.exists():
        if digest(target) != checksum:
            raise RuntimeError(f"Corrupt source cache: {target}")
        return target, filename
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="download-", dir=cache) as scratch:
        temporary = Path(scratch) / filename
        for url in (metadata["sourceURL"], metadata["mirror"]):
            if not url:
                continue
            try:
                subprocess.run(["curl", "--fail", "--location", "--retry", "2", "--max-time", "120", url, "-o", str(temporary)], check=True)
                if digest(temporary) != checksum:
                    raise RuntimeError(f"Source checksum mismatch for {url}")
                shutil.copyfile(temporary, target)
                return target, filename
            except subprocess.CalledProcessError:
                continue
    raise RuntimeError(f"Could not download matching {metadata['name']} source.")


def source_paths(root):
    # Explicit public roots: never include artwork, runtime, ignored builds,
    # personal config, arbitrary root-level untracked files, or symlink targets.
    if (root / ".git").exists():
        names = run("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", cwd=root).split("\0")
    else:
        names = list(json.loads((root / "SOURCE-SNAPSHOT.json").read_text())["sourceFiles"])
    directories = {"src", "scripts", "tests", "docs", "examples", "vendor", ".github"}
    files = {"README.md", "CHANGELOG.md", "CREDITS.md", "LICENSE", "LICENSE.md", ".gitignore", ".gitattributes", "package.json", "package-lock.json", "tsconfig.json"}
    result = []
    for name in sorted(set(names) - {""}):
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise RuntimeError(f"Invalid source path: {name}")
        path = root / name
        if Path(name).parts[0] not in directories and name not in files:
            continue
        if path.is_symlink():
            raise RuntimeError(f"Source symlinks require explicit review: {name}")
        if path.is_file():
            if root.resolve() not in path.resolve().parents:
                raise RuntimeError(f"Source escapes checkout: {name}")
            result.append(name)
    return result


def source_provenance(root):
    if (root / ".git").exists():
        return {"sourceCommit": run("git", "rev-parse", "HEAD", cwd=root).strip(),
                "sourceDirty": bool(run("git", "status", "--porcelain", cwd=root).strip())}
    snapshot = json.loads((root / "SOURCE-SNAPSHOT.json").read_text())
    changed = any(not (root / name).is_file() or digest(root / name) != value for name, value in snapshot["sourceFiles"].items())
    return {"sourceCommit": snapshot["sourceCommit"], "sourceDirty": snapshot["sourceDirty"] or changed}


def archive_source(root, destination, names):
    hashes = {name: digest(root / name) for name in names}
    with destination.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as archive:
        for name in names:
            info = archive.gettarinfo(str(root / name), arcname=f"libresprite-ai-mcp/{name}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with (root / name).open("rb") as stream:
                archive.addfile(info, stream)
        snapshot = json.dumps({**source_provenance(root), "sourceFiles": hashes}, indent=2).encode() + b"\n"
        info = tarfile.TarInfo("libresprite-ai-mcp/SOURCE-SNAPSHOT.json")
        info.size = len(snapshot)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(snapshot))
    return hashes


def collect_notices(directory, destination):
    destination.mkdir(parents=True)
    candidates = list(directory.iterdir())
    docs = directory / "share/doc"
    if docs.exists():
        candidates.extend(docs.rglob("*"))
    copied = []
    for source in candidates:
        if source.is_file() and re.match(r"(?i)^(license|licence|copying|copyright|notice|patents|authors|readme\.ijg|ftl)", source.name):
            relative = source.relative_to(directory)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(str(relative))
    if not any(re.match(r"(?i)^(license|copying|copyright)", Path(name).name) for name in copied):
        raise RuntimeError(f"Missing license notices for {directory}")


def verify_linkage(app):
    executable = app / "Contents/MacOS/libresprite"
    binaries = [executable, *(app / "Contents/Frameworks").glob("*.dylib")]
    for binary in binaries:
        dependencies, rpaths, _ = loads(run("otool", "-l", binary))
        if any(p.startswith("/") and not p.startswith(SYSTEM) for p in rpaths):
            raise RuntimeError(f"External runtime search path retained: {binary}")
        for dependency in dependencies:
            if dependency.startswith(SYSTEM):
                continue
            if not dependency.startswith("@loader_path/"):
                raise RuntimeError(f"Non-relocatable library dependency: {dependency}")
            target = Path(expand(dependency, binary, executable)).resolve()
            if not target.is_file() or app.resolve() not in target.parents:
                raise RuntimeError(f"Library dependency escapes/is missing: {dependency}")
    run("codesign", "--verify", "--deep", "--strict", app)


def build(output):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Packaging currently requires native Apple Silicon macOS.")
    for tool in ("brew", "cmake", "ninja", "npm", "node", "otool", "lipo", "install_name_tool", "codesign", "strip", "ditto", "sips", "iconutil"):
        if not shutil.which(tool):
            raise RuntimeError(f"Missing build tool: {tool}. See docs/packaging.md.")
    if output.exists() or output.is_symlink() or Path(str(output) + ".zip").exists() or Path(str(output) + ".zip.sha256").exists():
        raise RuntimeError(f"Refusing to overwrite package output: {output}")
    # Always build current source. Existing editors are not touched.
    subprocess.run(["npm", "run", "build"], cwd=ROOT, check=True)
    subprocess.run(["bash", str(ROOT / "scripts/build-libresprite.sh")], cwd=ROOT, check=True)
    native = Path(os.environ.get("LIBRESPRITE_BUILD_DIR", ROOT / "build/libresprite")) / "bin/libresprite"
    native = native.resolve()
    runtime = []
    # Homebrew's SDL2 compatibility shim dlopens SDL3; it isn't an LC_LOAD_DYLIB.
    initial = graph(native, [])
    if any("libSDL2" in p.name and b"@loader_path/libSDL3.dylib" in p.read_bytes() for p in initial):
        runtime.append((Path(run("brew", "--prefix", "sdl3").strip()) / "lib/libSDL3.dylib").resolve())
    libraries = graph(native, runtime)
    version = json.loads((ROOT / "package.json").read_text())["version"]
    minimum = max((v for item in libraries.values() for v in item["minimum"]), key=lambda v: tuple(map(int, v.split("."))))
    formulae = {formula_directory(p) for p in libraries if p != native}
    metadata = [recipe_metadata(d) for d in sorted(formulae)]
    for item in metadata:
        if item["name"] not in LICENSE_POLICIES:
            raise RuntimeError(f"Dependency {item['name']} needs explicit license/source review before packaging.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-", dir=output.parent) as temporary:
        stage = Path(temporary) / output.name
        app = stage / APP_NAME
        contents = app / "Contents"
        resources = contents / "Resources"
        frameworks = contents / "Frameworks"
        (contents / "MacOS").mkdir(parents=True)
        frameworks.mkdir()
        resources.mkdir()
        targets = {native: contents / "MacOS/libresprite"}
        for source in libraries:
            if source == native:
                continue
            target = frameworks / source.name
            if target in targets.values():
                raise RuntimeError(f"Library basename collision: {source.name}")
            targets[source] = target
        for source, target in targets.items():
            shutil.copyfile(source, target)
            target.chmod(0o755)
            subprocess.run(["strip", "-S", str(target)], check=True)
            arguments = []
            if source != native:
                arguments += ["-id", "@rpath/" + target.name]
            for old, dependency in libraries[source]["edges"].items():
                if dependency:
                    relative = os.path.relpath(targets[dependency], target.parent)
                    arguments += ["-change", old, "@loader_path/" + relative]
            for rpath in libraries[source]["rpaths"]:
                # No Homebrew fallbacks, even for dlopen. SDL3 gets a local alias.
                arguments += ["-delete_rpath", rpath]
            if arguments:
                subprocess.run(["install_name_tool", *arguments, str(target)], check=True)
        if runtime:
            (frameworks / "libSDL3.dylib").symlink_to(targets[runtime[0]].name)
        shutil.copytree(native.parent / "data", resources / "data")
        notices = resources / "Licenses"
        notices.mkdir()
        for name in ("LICENSE", "LICENSE.md", "CREDITS.md"):
            shutil.copyfile(ROOT / name, notices / name)
            shutil.copyfile(ROOT / name, stage / name)
        # Preserve all vendored notices, including data/font licenses.
        for source in (ROOT / "vendor").rglob("*"):
            if source.is_file() and re.match(r"(?i)^(license|licence|copying|copyright|notice|patents|authors|contributors)", source.name):
                target = notices / "vendored" / source.relative_to(ROOT / "vendor")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        sources = stage / "sources"
        sources.mkdir()
        recipes = sources / "homebrew-recipes"
        recipes.mkdir()
        for directory in sorted(formulae):
            collect_notices(directory, notices / directory.parent.name)
        dependencies = []
        for item in metadata:
            shutil.copyfile(item["recipe"], recipes / item["recipe"].name)
            entry = {k: v for k, v in item.items() if k not in ("recipe", "mirror")}
            entry["distributedLicense"] = LICENSE_POLICIES[item["name"]]
            if item["name"] in ("freetype", "lz4"):
                # FTL is not GPLv2-compatible: distribute under FreeType's GPLv2 option.
                archive, filename = fetch_source(item, ROOT / ".cache/packaging-source")
                shutil.copyfile(archive, sources / filename)
                entry["includedSource"] = "sources/" + filename
                with tarfile.open(archive) as tar:
                    wanted = ("docs/GPLv2.TXT", "docs/FTL.TXT", "LICENSE.TXT") if item["name"] == "freetype" else ("lib/LICENSE",)
                    for name in wanted:
                        members = [m for m in tar.getmembers() if m.isfile() and m.name.endswith("/" + name)]
                        if len(members) != 1:
                            raise RuntimeError(f"Missing full {item['name']} license: {name}")
                        notice = notices / item["name"] / name
                        notice.parent.mkdir(parents=True, exist_ok=True)
                        notice.write_bytes(tar.extractfile(members[0]).read())
            dependencies.append(entry)
        iconset = Path(temporary) / "libresprite.iconset"
        iconset.mkdir()
        icon = ROOT / "vendor/libresprite/desktop/icons/hicolor/256x256/apps/libresprite.png"
        for size in (16, 32, 128, 256, 512):
            for factor, suffix in ((1, ""), (2, "@2x")):
                run("sips", "-z", size * factor, size * factor, icon, "--out", iconset / f"icon_{size}x{size}{suffix}.png")
        run("iconutil", "-c", "icns", iconset, "-o", resources / "libresprite.icns")
        plist = {"CFBundleName": "LibreSprite AI", "CFBundleDisplayName": "LibreSprite AI",
                 "CFBundleIdentifier": IDENTIFIER, "CFBundleExecutable": "libresprite",
                 "CFBundleVersion": version, "CFBundleShortVersionString": version,
                 "CFBundlePackageType": "APPL", "CFBundleIconFile": "libresprite.icns",
                 "LSMinimumSystemVersion": minimum, "NSHighResolutionCapable": True,
                 "NSHumanReadableCopyright": "Independent modified LibreSprite build. See Resources/Licenses."}
        (contents / "Info.plist").write_bytes(plistlib.dumps(plist))
        mcp = stage / "mcp"
        mcp.mkdir()
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(ROOT / name, mcp / name)
        shutil.copytree(ROOT / "dist", mcp / "dist", ignore=shutil.ignore_patterns("tests"))
        (mcp / "package-layout.json").write_text(json.dumps({"version": version, "layout": 1}) + "\n")
        subprocess.run(["npm", "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=mcp, check=True)
        for name in ("start-mcp.sh", "doctor.sh"):
            shutil.copyfile(ROOT / "scripts/package" / name, mcp / name)
            (mcp / name).chmod(0o755)
        shutil.copytree(ROOT / "docs", stage / "docs")
        shutil.copytree(ROOT / "examples/mcp", stage / "examples")
        shutil.copyfile(ROOT / "scripts/package/START-HERE.md", stage / "START-HERE.md")
        shutil.copyfile(ROOT / "scripts/package/verify-package.py", stage / "verify-package.py")
        source_files = source_paths(ROOT)
        source_hashes = archive_source(ROOT, sources / "libresprite-ai-mcp-source.tar.gz", source_files)
        manifest = {"version": version, "protocolVersion": 1, "architecture": "arm64", "minimumMacOS": minimum,
                    "signing": "ad-hoc; not Developer ID signed or notarized", "node": "external Node.js >=20",
                    **source_provenance(ROOT),
                    "sourceFiles": source_hashes, "dependencies": dependencies,
                    "nativeInputs": {str(targets[p].relative_to(app)): digest(p) for p in libraries},
                    "build": {"sdk": run("xcrun", "--sdk", "macosx", "--show-sdk-version").strip(),
                              "compiler": run("clang", "--version").splitlines()[0], "node": run("node", "--version").strip()}}
        (resources / "package-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (sources / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for binary in targets.values():
            run("codesign", "--force", "--sign", "-", "--timestamp=none", binary, stderr=subprocess.STDOUT)
        run("codesign", "--force", "--sign", "-", "--timestamp=none", app, stderr=subprocess.STDOUT)
        verify_linkage(app)
        # Content hashes include the final signed bundle, sources, and production MCP tree.
        hashes = {str(p.relative_to(stage)): digest(p) for p in sorted(stage.rglob("*")) if p.is_file() and not p.is_symlink()}
        links = {str(p.relative_to(stage)): os.readlink(p) for p in stage.rglob("*") if p.is_symlink()}
        (stage / "checksums.json").write_text(json.dumps({"files": hashes, "symlinks": links}, indent=2) + "\n")
        subprocess.run(["python3", str(stage / "verify-package.py"), str(stage)], check=True)
        archive = Path(str(output) + ".zip")
        staged_zip = Path(temporary) / "package.zip"
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", stage, staged_zip)
        checksum = digest(staged_zip)
        # Exclusive publication also refuses destinations created during the build.
        output.mkdir()
        for child in stage.iterdir():
            os.rename(child, output / child.name)
        os.link(staged_zip, archive)
        with Path(str(archive) + ".sha256").open("x") as stream:
            stream.write(f"{checksum}  {archive.name}\n")
    print(f"Packaged {output}\nArchive: {archive}\nRequires Apple Silicon macOS {minimum}+ and external Node.js 20+.\nNothing installed, committed, pushed, or notarized.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New output directory (existing output is refused).")
    options = parser.parse_args()
    version = json.loads((ROOT / "package.json").read_text())["version"]
    build((options.output or ROOT / f"build/packages/libresprite-ai-mcp-{version}-macos-arm64").absolute())


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
