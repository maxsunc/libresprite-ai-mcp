// GPL-2.0-only. Real editor + MCP stdio + Windows pipe, in a disposable profile.
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { windowsPipeName } from "../dist/endpoint.js";

assert.equal(process.platform, "win32", "Run this smoke test on native Windows");
const packageRoot = process.argv[2] ? path.resolve(process.argv[2]) : undefined;
const serverRoot = packageRoot ? path.join(packageRoot, "mcp") : process.cwd();
const executable = packageRoot ? path.join(packageRoot, "LibreSprite-AI.exe")
  : process.env.LIBRESPRITE_EXECUTABLE ?? path.resolve("build/libresprite/bin/libresprite.exe");
await mkdir("build", { recursive: true });
const temporary = await mkdtemp(path.resolve("build/windows MCP é "));
const assets = path.join(temporary, "assets é");
const profile = path.join(temporary, "profile é");
await mkdir(assets); await mkdir(profile);
const env = { ...process.env, LIBRESPRITE_SOCKET: windowsPipeName(temporary), LIBRESPRITE_EXECUTABLE: executable,
  LIBRESPRITE_ASSET_ROOT: assets, LIBRESPRITE_USER_DIR: profile };
if (packageRoot) env.PATH = `${process.env.SystemRoot}\\System32;${process.env.SystemRoot}`;
if (process.env.LIBRESPRITE_TEST_HEADLESS === "1") env.SDL_VIDEODRIVER = "dummy";
let client, pid;
async function connectMcp() {
  const transport = new StdioClientTransport({
    command: packageRoot ? path.join(serverRoot, "runtime/node.exe") : process.execPath,
    args: [path.join(serverRoot, "dist/index.js")], env, stderr: "inherit",
  });
  const connection = new Client({ name: "windows-smoke", version: "1.0.0" });
  await connection.connect(transport);
  return connection;
}
async function call(method, args = {}, error) {
  const response = await client.callTool({ name: `libresprite_${method}`, arguments: args });
  const result = JSON.parse(response.content[0].text);
  if (error) { assert.equal(response.isError, true); assert.equal(result.code, error); }
  else assert.ok(!response.isError, JSON.stringify(result));
  return result;
}
async function preview(documentId) {
  const response = await client.callTool({ name: "libresprite_render", arguments: { documentId, frame: 0 } });
  assert.ok(!response.isError, JSON.stringify(response));
  const image = response.content.find((part) => part.type === "image");
  assert.equal(image.mimeType, "image/png");
  assert.equal(Buffer.from(image.data, "base64").subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
  return image.data;
}
try {
  client = await connectMcp();
  pid = (await call("launch")).pid;
  assert.ok(Number.isInteger(pid) && pid > 0);
  let status, lastConnectionError;
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const response = await client.callTool({ name: "libresprite_connect", arguments: {} });
    if (!response.isError) { status = JSON.parse(response.content[0].text); break; }
    lastConnectionError = response;
    await delay(100);
  }
  assert.ok(status, `Editor pipe did not become ready within 30 seconds: ${JSON.stringify(lastConnectionError)}`);
  assert.equal(status.pid, pid);
  assert.equal(status.paused, true);
  await call("create", { width: 16, height: 16 }, "PAUSED");
  await call("set_paused", { paused: false });
  const document = await call("create", { width: 16, height: 16, name: "Windows test" });
  const documentId = document.documentId, layerId = document.layers[0].layerId;
  const target = async () => ({ documentId, expectedRevision: (await call("inspect", { documentId })).revision });
  const blank = await preview(documentId);
  const stale = await target();
  await call("set_pixels", { ...stale, layerId, frame: 0, pixels: [{ x: 2, y: 3, r: 220, g: 50, b: 60, a: 255 }] });
  const painted = await preview(documentId);
  assert.notEqual(painted, blank);
  const conflict = await call("set_pixels", { ...stale, layerId, frame: 0, pixels: [{ x: 0, y: 0, r: 0, g: 0, b: 0, a: 255 }] });
  assert.equal(conflict.applied, false);
  assert.equal(conflict.reason, "STALE_REVISION");
  await call("undo", await target());
  assert.equal(await preview(documentId), blank);
  await call("redo", await target());
  assert.equal(await preview(documentId), painted);
  await call("save", { ...await target(), path: "round trip é.ase" });
  const saved = await readFile(path.join(assets, "round trip é.ase"));
  await call("save", { ...await target(), path: "round trip é.ase" }, "FILE_EXISTS");
  assert.deepEqual(await readFile(path.join(assets, "round trip é.ase")), saved);
  await call("save", { ...await target(), path: "round trip é.ase", overwrite: true });
  for (const bad of ["../escape.ase", "C:escape.ase", "C:\\escape.ase", "\\escape.ase", "round trip é.ase:stream", "NUL.ase", "trailing.ase."]) {
    await call("save", { ...await target(), path: bad }, "PATH_OUTSIDE_ROOT");
  }
  // A junction needs no developer-mode symlink privilege on Windows.
  const { symlink } = await import("node:fs/promises");
  await symlink(temporary, path.join(assets, "escape"), "junction");
  await call("save", { ...await target(), path: "escape/outside.ase" }, "PATH_OUTSIDE_ROOT");
  for (const format of ["png", "gif", "apng"]) {
    const args = format === "png" ? { ...await target(), frame: 0, path: "export é.png" }
      : { ...await target(), format, path: `export é.${format}` };
    const method = format === "png" ? "export_png" : "export_animation";
    await call(method, args);
    const bytes = await readFile(path.join(assets, `export é.${format}`));
    assert.ok(bytes.length > 16);
    await call(method, args, "FILE_EXISTS");
    await call(method, { ...args, overwrite: true });
  }
  const reopened = await call("open", { path: "round trip é.ase" });
  assert.equal(await preview(reopened.documentId), painted);
  assert.equal((await call("inspect", { documentId: reopened.documentId })).modified, false);
  assert.ok(!(await readdir(assets)).some((name) => name.startsWith(".libresprite-ai-")), "Temporary files leaked");
  await client.close(); client = undefined;
  process.kill(pid, 0); // MCP EOF leaves the editor (and any unsaved work) alive.
  await delay(150);
  client = await connectMcp();
  status = await call("connect");
  assert.equal(status.pid, pid);
  assert.equal(status.paused, true, "Disconnect must pause the editor before reconnect");
  await call("create", { width: 16, height: 16 }, "PAUSED");
  console.log("PASS: native Windows MCP launch/pipe, paused editing, PNG feedback, draw/undo/redo, Unicode/spaced paths, atomic save/overwrite, root/junction/device/stream guards, PNG/GIF/APNG export, reopen and disconnect safety.");
} finally {
  if (client) await client.close();
  // Only terminate the NEW disposable process launched by this test.
  if (pid) { try { process.kill(pid); } catch (error) { if (error.code !== "ESRCH") throw error; } }
  await delay(200);
  await rm(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}
