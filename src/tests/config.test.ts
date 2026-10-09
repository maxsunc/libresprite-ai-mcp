// GPL-2.0-only. No real GUI, live socket, or user configuration involved.
import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { resolveOptions } from "../config.js";
import { diagnose } from "../doctor.js";
import { inspectMachO } from "../macho.js";

test("read-only Mach-O parser bounds checks commands and preserves local paths", () => {
  const filename = Buffer.from("@loader_path/../Frameworks/a library.dylib\0");
  const commandSize = Math.ceil((24 + filename.length) / 8) * 8;
  const bytes = Buffer.alloc(32 + commandSize + 24);
  bytes.writeUInt32LE(0xfeedfacf, 0);
  bytes.writeUInt32LE(0x0100000c, 4);
  bytes.writeUInt32LE(2, 16);
  bytes.writeUInt32LE(commandSize + 24, 20);
  bytes.writeUInt32LE(0xc, 32);
  bytes.writeUInt32LE(commandSize, 36);
  bytes.writeUInt32LE(24, 40);
  filename.copy(bytes, 56);
  const version = 32 + commandSize;
  bytes.writeUInt32LE(0x32, version);
  bytes.writeUInt32LE(24, version + 4);
  bytes.writeUInt32LE(1, version + 8);
  bytes.writeUInt32LE(26 << 16, version + 12);
  assert.deepEqual(inspectMachO(bytes), { dependencies: [filename.toString().slice(0, -1)], rpaths: [], minimumMacOS: ["26.0.0"] });
  assert.throws(() => inspectMachO(bytes.subarray(0, bytes.length - 1)));
  const invalid = Buffer.from(bytes);
  invalid.writeUInt32LE(0xffffffff, 40);
  assert.throws(() => inspectMachO(invalid));
  invalid.writeUInt32LE(24, 40);
  invalid.writeUInt32LE(0x01000007, 4);
  assert.throws(() => inspectMachO(invalid));
});

test("development and packaged defaults are distinct and explicit overrides win", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ls-config-"));
  try {
    const development = resolveOptions(root, {});
    assert.equal(development.assetRoot, path.join(root, "assets"));
    assert.equal(development.socketPath, path.join(root, ".runtime/bridge.sock"));
    await writeFile(path.join(root, "package-layout.json"), '{"layout":1}');
    const packaged = resolveOptions(root, {});
    assert.equal(packaged.executable, path.resolve(root, "../LibreSprite AI.app/Contents/MacOS/libresprite"));
    assert.equal(packaged.assetRoot, path.join(os.homedir(), "Pictures/LibreSprite AI MCP"));
    assert.equal(packaged.socketPath, path.join(os.tmpdir(), `lsai-${process.getuid?.() ?? "user"}`, "b.sock"));
    const explicit = resolveOptions(root, { LIBRESPRITE_EXECUTABLE: "/custom/editor", LIBRESPRITE_SOCKET: "/custom/b.sock", LIBRESPRITE_ASSET_ROOT: "/custom/art" });
    assert.deepEqual(explicit, { executable: "/custom/editor", socketPath: "/custom/b.sock", assetRoot: "/custom/art" });
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("default diagnostics are read-only and report missing runtime as warnings", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ls-doctor-"));
  try {
    const executable = path.join(root, "bin/libresprite");
    await mkdir(path.join(root, "bin/data"), { recursive: true });
    await writeFile(executable, '#!/bin/sh\ntouch "$0.was-run"\nexit 1\n', { mode: 0o700 });
    await writeFile(path.join(root, "bin/data/gui.xml"), "fixture");
    const options = { executable, socketPath: path.join(root, "private/b.sock"), assetRoot: path.join(root, "art") };
    const result = await diagnose(options);
    assert.equal(result.ok, true, JSON.stringify(result));
    assert.equal(result.checks.find((check) => check.name === "socket")?.status, "warning");
    assert.ok(!result.checks.some((check) => check.name === "bridge"));
    assert.equal(existsSync(path.join(root, "private")), false);
    assert.equal(existsSync(options.assetRoot), false);
    assert.equal(existsSync(executable + ".was-run"), false, "Diagnostics must never execute the editor, even for --version.");
    const invalid = await diagnose({ ...options, executable: path.join(root, "missing"), socketPath: path.join(root, "x".repeat(200)) });
    assert.equal(invalid.ok, false);
    assert.equal(invalid.checks.find((check) => check.name === "socket-path")?.status, "error");
    await mkdir(path.join(root, "private"), { mode: 0o755 });
    const unsafe = await diagnose(options);
    assert.equal(unsafe.checks.find((check) => check.name === "socket-directory")?.status, "error");
  } finally { await rm(root, { recursive: true, force: true }); }
});
