#!/usr/bin/env python3
"""Create an unsigned Windows x64 PRIVATE REVIEW ZIP, never install or overwrite. GPLv2.

shortcut: third-party corresponding source/license compatibility is not audited,
complete that audit and bundle the required sources before public redistribution.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def run(*args, **kwargs):
    return subprocess.check_output(list(map(str, args)), text=True, **kwargs)


def pe_imports(text):
    names = re.findall(r"DLL Name:\s*(\S+)", text)
    if any(Path(name).name != name or "/" in name or "\\" in name or ":" in name for name in names):
        raise RuntimeError("Invalid PE dependency name")
    return names


def dll_closure(executable, prefix, inspect, system):
    libraries = {p.name.lower(): p for p in (prefix / "bin").glob("*.dll")}
    pending, result = [executable], {}
    while pending:
        binary = pending.pop()
        if binary.name.lower() in result:
            continue
        result[binary.name.lower()] = binary
        for name in inspect(binary):
            key = name.lower()
            if key in libraries:
                pending.append(libraries[key])
            elif key.startswith(("api-ms-win-", "ext-ms-win-")) or (system / name).is_file():
                continue
            else:
                raise RuntimeError(f"Unresolved runtime DLL {name} from {binary}; nothing is silently skipped")
    return list(result.values())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output, prefix, node, node_license):
    if os.name != "nt":
        raise RuntimeError("Build this package on native Windows x64")
    zip_path = Path(str(output) + ".zip")
    if output.exists() or zip_path.exists():
        raise RuntimeError("Refusing to replace an existing output directory or ZIP")
    objdump = prefix / "bin/objdump.exe"
    native = Path(os.environ.get("LIBRESPRITE_BUILD_DIR", ROOT / "build/libresprite")) / "bin/libresprite.exe"
    system = Path(os.environ["SystemRoot"]) / "System32"
    info = json.loads(run(node, "-p", "JSON.stringify({version:process.version,arch:process.arch,platform:process.platform})"))
    if info["platform"] != "win32" or info["arch"] != "x64" or int(info["version"][1:].split(".")[0]) < 20:
        raise RuntimeError("A native Windows x64 Node.js >=20 runtime is required")
    version = json.loads((ROOT / "package.json").read_text())["version"]

    def inspect(binary):
        if "pei-x86-64" not in run(objdump, "-f", binary):
            raise RuntimeError(f"Expected x64 PE executable/library: {binary}")
        return pe_imports(run(objdump, "-p", binary))

    binaries = dll_closure(native, prefix, inspect, system)
    # MSYS2 SDL2-compat loads SDL3 dynamically, outside the PE import table.
    sdl2 = prefix / "bin/SDL2.dll"
    if sdl2.is_file() and b"SDL3.dll" in sdl2.read_bytes():
        binaries += dll_closure(prefix / "bin/SDL3.dll", prefix, inspect, system)
    node_binaries = dll_closure(node, prefix, inspect, system)
    spec = importlib.util.spec_from_file_location("mac_packager", ROOT / "scripts/package-macos.py")
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    names = source.source_paths(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="windows-package-", dir=output.parent) as scratch:
        stage = Path(scratch) / output.name
        stage.mkdir()
        shutil.copyfile(native, stage / "LibreSprite-AI.exe")
        shutil.copytree(native.parent / "data", stage / "data")
        for binary in binaries:
            if binary != native:
                shutil.copyfile(binary, stage / binary.name)
        mcp = stage / "mcp"
        runtime = mcp / "runtime"
        runtime.mkdir(parents=True)
        shutil.copyfile(node, runtime / "node.exe")
        for binary in node_binaries:
            if binary != node:
                shutil.copyfile(binary, runtime / binary.name)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(ROOT / name, mcp / name)
        shutil.copytree(ROOT / "dist", mcp / "dist", ignore=shutil.ignore_patterns("tests"))
        subprocess.run(["npm.cmd", "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=mcp, check=True)
        (mcp / "package-layout.json").write_text(json.dumps({"layout": 1, "version": version, "platform": "win32-x64"}))
        for name in ("start-mcp.cmd", "doctor.cmd"):
            shutil.copyfile(ROOT / "scripts/package" / name, stage / name)
        shutil.copyfile(ROOT / "docs/windows.md", stage / "START-HERE.md")
        licenses = stage / "licenses"
        licenses.mkdir()
        for name in ("LICENSE", "CREDITS.md"):
            shutil.copyfile(ROOT / name, licenses / name)
        shutil.copytree(prefix / "share/licenses", licenses / "msys2")
        if node_license:
            shutil.copyfile(node_license, licenses / "NODE-LICENSE.txt")
        else:
            url = f"https://raw.githubusercontent.com/nodejs/node/{info['version']}/LICENSE"
            with urllib.request.urlopen(url, timeout=30) as response:
                (licenses / "NODE-LICENSE.txt").write_bytes(response.read())
        packages = []
        for desc in sorted((prefix.parent / "var/lib/pacman/local").glob("*/desc")):
            packages.append(desc.read_text(encoding="utf8"))
        if not packages:
            raise RuntimeError("MSYS2 package provenance is required")
        (licenses / "msys2-packages.json").write_text(json.dumps(packages, indent=2), encoding="utf8")
        sources = stage / "sources"
        sources.mkdir()
        source.archive_source(ROOT, sources / "libresprite-ai-source.tar.gz", names)
        manifest = {"version": version, "platform": "win32-x64", "minimumWindows": "Windows 11 x64 (review target)",
                    "distribution": "PRIVATE REVIEW ONLY: third-party source/license audit pending; do not publicly redistribute this binary package",
                    "signing": "unsigned", "node": info, "source": source.source_provenance(ROOT),
                    "nativeDLLs": sorted({p.name for p in binaries if p != native})}
        (stage / "package-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
        shutil.copyfile(ROOT / "scripts/package/verify-package.py", stage / "verify-package.py")
        files = {p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob("*")) if p.is_file()}
        (stage / "checksums.json").write_text(json.dumps({"files": files, "symlinks": {}}, indent=2), encoding="utf8")
        archive = Path(shutil.make_archive(str(Path(scratch) / output.name), "zip", root_dir=stage.parent, base_dir=stage.name))
        shutil.move(str(stage), output)
        shutil.move(str(archive), zip_path)
    print(f"Private review package: {output}\nZIP: {zip_path}\nUnsigned; do not publicly redistribute before the third-party licensing/source audit.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-review", action="store_true", required=True, help="Acknowledge this is not a redistributable public release")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prefix", type=Path, help="MSYS2 UCRT64 prefix (defaults to the gcc.exe installation prefix)")
    parser.add_argument("--node", type=Path, default=Path(shutil.which("node") or "node.exe"))
    parser.add_argument("--node-license", type=Path, help="Matching Node LICENSE; otherwise fetched from its exact official version")
    args = parser.parse_args()
    gcc = shutil.which("gcc")
    if not args.prefix and not gcc:
        parser.error("Supply --prefix C:\\msys64\\ucrt64 or run from the UCRT64 shell")
    prefix = (args.prefix or Path(gcc).parent.parent).resolve()
    version = json.loads((ROOT / "package.json").read_text())["version"]
    build((args.output or ROOT / f"build/packages/libresprite-ai-{version}-windows-x64").resolve(), prefix, args.node.resolve(), args.node_license)


if __name__ == "__main__":
    main()
