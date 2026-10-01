#!/usr/bin/env python3
"""Check the native executable and a lossless PNG -> ASE -> PNG round trip."""

import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib


ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(os.environ.get("LIBRESPRITE_BUILD_DIR", ROOT / "build/libresprite"))
EXECUTABLE = BUILD / "bin/libresprite"
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def write_fixture(path):
    width = height = 16
    colors = [(0, 0, 0, 0), (220, 50, 60, 255), (40, 180, 100, 255), (60, 100, 220, 255)]
    pixels = bytes(
        channel
        for y in range(height)
        for x in range(width)
        for channel in colors[0 if x in (0, 15) or y in (0, 15) else 1 + (x + y) % 3]
    )
    rows = b"".join(b"\0" + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return width, height, pixels


def read_png(path):
    data = path.read_bytes()
    if not data.startswith(SIGNATURE):
        raise RuntimeError("Export is not a PNG: " + str(path))
    position = len(SIGNATURE)
    compressed = bytearray()
    palette = b""
    alpha = b""
    header = None
    while position < len(data):
        size = struct.unpack_from(">I", data, position)[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + size]
        crc = struct.unpack_from(">I", data, position + 8 + size)[0]
        if zlib.crc32(kind + payload) != crc:
            raise RuntimeError("Invalid PNG checksum: " + str(path))
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"tRNS":
            alpha = payload
        position += size + 12
        if kind == b"IEND":
            break
    if header is None:
        raise RuntimeError("PNG has no header.")
    width, height, depth, color_type, compression, filtering, interlace = header
    if depth != 8 or color_type not in (2, 3, 6) or compression or filtering or interlace:
        raise RuntimeError("Unexpected PNG encoding in baseline smoke test: " + str(header))
    channels = {2: 3, 3: 1, 6: 4}[color_type]
    stride = width * channels
    raw = zlib.decompress(compressed)
    if len(raw) != height * (stride + 1):
        raise RuntimeError("Unexpected PNG data length.")
    previous = bytearray(stride)
    result = bytearray()
    for y in range(height):
        start = y * (stride + 1)
        method = raw[start]
        row = bytearray(raw[start + 1:start + 1 + stride])
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            above = previous[x]
            diagonal = previous[x - channels] if x >= channels else 0
            if method == 0:
                predictor = 0
            elif method == 1:
                predictor = left
            elif method == 2:
                predictor = above
            elif method == 3:
                predictor = (left + above) // 2
            elif method == 4:
                p = left + above - diagonal
                distances = (abs(p - left), abs(p - above), abs(p - diagonal))
                predictor = (left, above, diagonal)[distances.index(min(distances))]
            else:
                raise RuntimeError("Unknown PNG filter: " + str(method))
            row[x] = (row[x] + predictor) & 255
        if color_type == 6:
            result.extend(row)
        elif color_type == 2:
            for x in range(0, stride, 3):
                result.extend(row[x:x + 3])
                result.append(255)
        else:
            for index in row:
                color = palette[index * 3:index * 3 + 3]
                if len(color) != 3:
                    raise RuntimeError("PNG contains an invalid palette index.")
                result.extend(color)
                result.append(alpha[index] if index < len(alpha) else 255)
        previous = row
    return width, height, bytes(result)


def run(*arguments):
    environment = os.environ.copy()
    environment["SDL_VIDEODRIVER"] = "dummy"
    result = subprocess.run(
        [str(EXECUTABLE), *map(str, arguments)],
        capture_output=True, text=True, timeout=60, env=environment,
    )
    if result.returncode:
        raise RuntimeError("LibreSprite failed:\n" + result.stdout + result.stderr)
    return result.stdout


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    require(EXECUTABLE.is_file(), "Build LibreSprite before running the smoke test.")
    version = run("--version").splitlines()[0].strip()
    require("LibreSprite" in version, "Unexpected version output: " + version)
    help_text = run("--help")
    require(all(option in help_text for option in ("--batch", "--script", "--save-as")), "Expected CLI options are missing.")
    print("PASS: version and CLI options ({}).".format(version))

    scratch = ROOT / "build/smoke-tests"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="baseline-", dir=scratch) as directory:
        directory = Path(directory)
        source = directory / "input.png"
        native = directory / "sprite.ase"
        exported = directory / "roundtrip.png"
        sheet = directory / "sheet.png"
        metadata = directory / "sheet.json"
        script = directory / "scripting.js"
        expected = write_fixture(source)
        script.write_text('console.log("SCRIPTING_OK:" + app.version);\n')
        require("SCRIPTING_OK:" in run("--batch", source, "--script", script), "The JavaScript engine did not execute the smoke-test script.")
        print("PASS: bundled JavaScript engine executes a batch script.")
        run("--batch", source, "--save-as", native)
        require(native.is_file(), "Native sprite file was not saved.")
        data = native.read_bytes()
        require(len(data) >= 128, "Native sprite header is incomplete.")
        magic, frames, width, height, depth = struct.unpack_from("<5H", data, 4)
        require((magic, frames, width, height, depth) == (0xA5E0, 1, 16, 16, 32), "Unexpected native sprite header.")
        run("--batch", native, "--save-as", exported)
        require(read_png(exported) == expected, "RGBA pixels changed during the native-file round trip.")
        print("PASS: PNG -> ASE -> PNG preserves dimensions and every RGBA pixel.")

        run("--batch", "--format", "json-array", "--sheet-type", "horizontal", native,
            "--sheet", sheet, "--data", metadata)
        require(read_png(sheet) == expected, "Sprite-sheet pixels differ from the input.")
        information = json.loads(metadata.read_text())
        require(len(information["frames"]) == 1, "Expected one sprite-sheet frame.")
        frame = information["frames"][0]
        require(frame["frame"]["w"] == 16 and frame["frame"]["h"] == 16, "Incorrect sprite-sheet frame bounds.")
        require(frame["duration"] > 0, "Sprite-sheet duration is missing or invalid.")
        print("PASS: sprite-sheet PNG and JSON frame metadata.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error))
