// GPL-2.0-only. Real stdio MCP + NEW generated-only editor, no personal sockets.
// Optional guarded OS gestures need LIBRESPRITE_TEST_GUI_INPUT=1/existing permission.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import path from "node:path";
import { createInterface } from "node:readline";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
await mkdir(path.join(root, ".runtime"), { recursive: true, mode: 0o700 });
const directory = await mkdtemp(path.join(root, ".runtime/c-"));
const assets = path.join(directory, "assets");
await mkdir(assets, { recursive: true, mode: 0o700 });
await mkdir(path.join(directory, "profile"), { mode: 0o700 });
await writeFile(path.join(directory, "profile/libresprite.ini"), "[MiniEditor]\nEnabled = false\n");
const env = { ...process.env, LIBRESPRITE_SOCKET: path.join(directory, "s"), LIBRESPRITE_ASSET_ROOT: assets,
  LIBRESPRITE_USER_DIR: path.join(directory, "profile") };
delete env.SDL_VIDEODRIVER;
const transport = new StdioClientTransport({ command: process.execPath, args: [path.join(root, "dist/index.js")], env, stderr: "pipe" });
const client = new Client({ name: "cooperative-regression", version: "0.13.0" });
let launched, driver, inputLines, held;
async function call(method, args = {}, expectedError) {
  const response = await client.callTool({ name: `libresprite_${method}`, arguments: args });
  const result = JSON.parse(response.content.find(item => item.type === "text").text);
  if (expectedError) { assert.equal(response.isError, true); assert.equal(result.code, expectedError); }
  else assert.ok(!response.isError, `${method}: ${JSON.stringify(result)}`);
  return result;
}
async function input(command) {
  driver.stdin.write(JSON.stringify(command) + "\n");
  const { value, done } = await inputLines.next();
  assert.ok(!done, "GUI driver exited unexpectedly");
  const result = JSON.parse(value); assert.ok(!result.error, result.error); return result;
}
async function mouse(kind, point, button = 0) { await input({ action: "mouse", kind, point, button }); }
try {
  await client.connect(transport); transport.stderr?.pipe(process.stderr);
  assert.equal((await client.listTools()).tools.length, 70);
  launched = await call("launch");
  const deadline = Date.now() + 20000;
  while (true) {
    try { const status = await call("connect"); assert.equal(status.bridgeVersion, "0.13.0"); assert.equal(status.pid, launched.pid); break; }
    catch (error) { if (Date.now() >= deadline) throw error; await delay(100); }
  }
  await call("set_paused", { paused: false });
  const doc = await call("create", { width: 16, height: 16, name: "Cooperative MCP disposable regression" });
  const documentId = doc.documentId, layerId = doc.layers[0].layerId;
  const current = () => call("inspect", { documentId });
  const state = () => call("interaction_state", { documentId });
  const edit = async (method, args = {}) => call(method, { documentId, expectedRevision: (await current()).revision, ...args });
  const pixel = async (x, y) => (await call("read_pixels", { documentId, layerId, frame: 0, x, y, width: 1, height: 1, encoding: "values" })).rows[0][0];
  const red = { r: 230, g: 60, b: 70, a: 255 };
  const operation = { method: "edit_pixels", edits: [{ layerId, frame: 0, pixels: [{ x: 1, y: 1, ...red }] }] };
  const prepare = () => edit("prepare_edit", { operation });
  const apply = token => call("apply_edit", { documentId, editToken: token });
  await edit("set_pixels", { layerId, frame: 0, pixels: [{ x: 0, y: 0, ...red }] });
  let plan = await prepare();
  await edit("set_pixels", { layerId, frame: 0, pixels: [{ x: 12, y: 12, ...red }] });
  let result = await apply(plan.editToken);
  assert.equal(result.status, "applied"); assert.equal(result.rebased, true);
  await edit("undo");
  plan = await prepare();
  await edit("set_pixels", { layerId, frame: 0, pixels: [{ x: 1, y: 1, ...red }] });
  const before = await pixel(1, 1);
  result = await apply(plan.editToken); assert.equal(result.status, "conflict"); assert.equal(result.applied, false); assert.equal(await pixel(1, 1), before);
  await edit("undo");
  const stale = (await current()).revision;
  await edit("set_pixels", { layerId, frame: 0, pixels: [{ x: 13, y: 13, ...red }] });
  result = await call("edit_pixels", { documentId, expectedRevision: stale, edits: operation.edits });
  assert.equal(result.status, "conflict"); assert.equal(result.reason, "STALE_REVISION"); assert.equal(result.applied, false);
  await edit("undo"); await edit("undo");
  console.log("PASS: real MCP 70-tool catalog, immutable guarded plans, disjoint rebase, overlapping and strict stale-revision non-error conflicts, native Undo.");

  driver = spawn("python3", ["-u", path.join(root, "scripts/gui-test-driver.py"), "--pid", String(launched.pid)], { stdio: ["pipe", "pipe", "inherit"] });
  inputLines = createInterface({ input: driver.stdout })[Symbol.asyncIterator]();
  const available = JSON.parse((await inputLines.next()).value).available;
  if (available) {
    await input({ action: "activate" });
    await input({ action: "key", code: 11 }); // B: native pencil.
    const point = async (x, y) => (await input({ action: "canvas_point", state: await state(), x, y })).point;
    await mouse(5, await point(8, 8));
    await input({ action: "key", code: 21 }); // 4: 800% zoom, robust pixel hit-testing.
    assert.equal((await state()).view.zoom, 8);
    const press = async (x, y, button = 0) => { held = { point: await point(x, y), button, up: button === 2 ? 26 : 2 }; await mouse(button === 2 ? 25 : 1, held.point, button); };
    const release = async () => { await mouse(held.up, held.point, held.button); held = undefined; };
    plan = await prepare(); await press(8, 8, 2);
    held.point = [held.point[0]+16, held.point[1]+8]; await mouse(27, held.point, 2);
    const pan = await state(); assert.equal(pan.viewOnlyPanning, true); assert.equal(pan.ready, true);
    result = await apply(plan.editToken); assert.equal(result.status, "applied");
    assert.deepEqual((await state()).view, pan.view);
    result = await call("undo", { documentId, expectedRevision: result.revision });
    assert.equal(result.status, "deferred"); assert.equal(result.applied, false);
    await release(); assert.notEqual(await pixel(1, 1), 0); await edit("undo");
    plan = await prepare(); await press(12, 12);
    assert.equal((await state()).ready, false);
    let done = false;
    const waiting = apply(plan.editToken).then(value => { done = true; return value; });
    await delay(300); assert.equal(done, false, "MCP edit should wait while drawing owns the document.");
    await release(); result = await waiting;
    assert.equal(result.status, "applied"); assert.equal(result.rebased, true);
    const manual = await pixel(12, 12); assert.notEqual(manual, 0);
    await edit("undo"); assert.equal(await pixel(12, 12), manual); assert.equal(await pixel(1, 1), 0);
    await edit("undo"); assert.equal(await pixel(12, 12), 0);
    plan = await prepare(); await press(1, 1);
    const overlap = apply(plan.editToken); await delay(300); await release(); result = await overlap;
    assert.equal(result.status, "conflict"); assert.equal(result.applied, false); assert.notEqual(await pixel(1, 1), 0);
    await edit("undo");
    plan = await prepare(); await press(12, 12);
    result = await apply(plan.editToken);
    assert.equal(result.status, "deferred"); assert.equal(result.applied, false); assert.equal((await call("connect")).paused, false);
    await release(); await delay(200);
    assert.equal(await pixel(1, 1), 0, "No native queued write may execute after a deferred response.");
    result = await apply(plan.editToken); assert.equal(result.status, "applied");
    await edit("undo"); await edit("undo");
    // MCP's cancellation notification reaches the server wait's AbortSignal.
    plan = await prepare(); await press(12, 12);
    const cancelled = new AbortController();
    const cancellation = assert.rejects(client.callTool({ name: "libresprite_apply_edit", arguments: { documentId, editToken: plan.editToken } }, undefined, { signal: cancelled.signal }));
    await delay(300); cancelled.abort(); await cancellation; await delay(200);
    await release(); await delay(200);
    assert.equal(await pixel(1, 1), 0, "Cancelled readiness wait must not send a later correction.");
    result = await apply(plan.editToken); assert.equal(result.status, "applied");
    await edit("undo"); await edit("undo");
    // Remote pause can run while another call is cooperatively waiting.
    plan = await prepare(); await press(12, 12);
    const pauseWait = call("apply_edit", { documentId, editToken: plan.editToken }, "PAUSED");
    await delay(300); await call("set_paused", { paused: true });
    await pauseWait; await release(); assert.equal(await pixel(1, 1), 0);
    await call("set_paused", { paused: false });
    // Actual local Pause is authoritative over real MCP too.
    const control = (await input({ action: "control_point", state: await state() })).point;
    await mouse(1, control); await mouse(2, control);
    assert.equal((await call("connect")).pausedByUser, true);
    await call("set_paused", { paused: false }, "USER_PAUSED");
    await mouse(1, control); await mouse(2, control);
    console.log("PASS: real MCP held pan preserves viewport, view-disrupting Undo defers; held native pencil waits/revalidates, overlaps conflict, long holds defer without queued writes; MCP cancellation prevents later writes, subsequent work continues; pause during waiting/local Resume latch remain authoritative.");
  } else console.log("SKIP: opt-in OS gesture checks (LIBRESPRITE_TEST_GUI_INPUT=1), existing macOS permissions and unused desktop required.");
  await edit("save", { path: "cooperative-mcp.ase" });
  await call("set_paused", { paused: true });
  console.log(`Disposable logs/profile/artifacts: ${directory}`);
} finally {
  if (driver?.exitCode === null) {
    if (held) await mouse(held.up, held.point, held.button).catch(() => {});
    driver.stdin.end(); await once(driver, "exit");
  }
  await client.close();
  // This test owns ONLY this newly launched PID and generated art, no user's editor.
  if (launched?.pid) {
    try { process.kill(launched.pid, "SIGTERM"); } catch (error) { if (error.code !== "ESRCH") throw error; }
    // Do not return while our Cocoa process can still interfere with the next
    // disposable editor's activation. Never signal another PID or force-kill.
    const deadline = Date.now() + 5000;
    while (true) {
      try { process.kill(launched.pid, 0); }
      catch (error) { if (error.code === "ESRCH") break; throw error; }
      if (Date.now() >= deadline) throw new Error(`Test-owned editor ${launched.pid} has not exited after SIGTERM.`);
      await delay(50);
    }
  }
}
