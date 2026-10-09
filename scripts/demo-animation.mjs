// Step 2 review over actual MCP, generated sprites in a NEW editor. GPL-2.0-only.
// No existing windows/artwork/configuration are changed. Ctrl+C only disconnects.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.join(root, ".runtime", `anim-${Date.now().toString(36)}`);
const assets = path.join(directory, "assets");
await mkdir(assets, { recursive: true, mode: 0o700 });
const environment = Object.fromEntries(Object.entries(process.env).filter(([, value]) => value !== undefined));
delete environment.SDL_VIDEODRIVER;
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [path.join(root, "dist/index.js")],
  env: { ...environment, LIBRESPRITE_SOCKET: path.join(directory, "b.sock"), LIBRESPRITE_ASSET_ROOT: assets },
  stderr: "pipe",
});
const client = new Client({ name: "libresprite-animation-review", version: "0.7.0" });
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let stopping = false;
process.once("SIGINT", () => { stopping = true; });
process.once("SIGTERM", () => { stopping = true; });
async function request(method, args = {}, error) {
  const response = await client.callTool({ name: `libresprite_${method}`, arguments: args });
  const result = JSON.parse(response.content.find((item) => item.type === "text").text);
  if (error) { assert.equal(response.isError, true); assert.equal(result.code, error); }
  else assert.ok(!response.isError, `${method}: ${JSON.stringify(result)}`);
  return result;
}
let documentId;
async function target() {
  const result = await request("inspect", { documentId });
  return { documentId, expectedRevision: result.revision };
}
async function edit(method, args) { return request(method, { ...await target(), ...args }); }
try {
  await client.connect(transport);
  transport.stderr?.pipe(process.stderr);
  assert.equal((await client.listTools()).tools.length, 51);
  const launched = await request("launch");
  const deadline = Date.now() + 15_000;
  let status;
  while (true) {
    try { status = await request("connect"); break; }
    catch (error) { if (Date.now() > deadline) throw error; await wait(100); }
  }
  assert.equal(status.bridgeVersion, "0.7.0");
  await request("set_paused", { paused: false });
  let doc = await request("create", { width: 48, height: 48, name: "Step 2 animation review" });
  documentId = doc.documentId;
  const body = doc.layers[0].layerId;
  await edit("update_layer", { layerId: body, name: "Blue arrow — copied independent cels" });
  const blue = { r: 55, g: 165, b: 225, a: 255 };
  const gold = { r: 250, g: 185, b: 65, a: 255 };
  await edit("draw_shape", { layerId: body, frame: 0, shape: "rectangle", x1: 12, y1: 18, x2: 23, y2: 23, filled: true, color: blue });
  await edit("draw_stroke", { layerId: body, frame: 0, points: [{ x: 22, y: 14 }, { x: 29, y: 21 }, { x: 22, y: 28 }], color: blue });
  await edit("add_frame", { index: 1 });
  await edit("add_frame", { index: 2 });
  await edit("copy_cel", { layerId: body, frame: 1, sourceLayerId: body, sourceFrame: 0 });
  await edit("copy_cel", { layerId: body, frame: 2, sourceLayerId: body, sourceFrame: 0 });
  const accent = (await edit("create_layer", { name: "Gold accent — cross-layer copy" })).createdLayerId;
  await edit("draw_shape", { layerId: accent, frame: 0, shape: "rectangle", x1: 14, y1: 20, x2: 18, y2: 21, filled: true, color: gold });
  await edit("copy_cel", { layerId: accent, frame: 1, sourceLayerId: accent, sourceFrame: 0 });
  await edit("copy_cel", { layerId: accent, frame: 2, sourceLayerId: accent, sourceFrame: 0 });
  const extra = (await edit("create_layer", { name: "Cross-layer copy test (hidden)" })).createdLayerId;
  await edit("update_layer", { layerId: extra, visible: false });
  await edit("copy_cel", { layerId: extra, frame: 1, sourceLayerId: accent, sourceFrame: 0 });
  await edit("duplicate_frames", { frames: [0, 1], index: 3 });
  await edit("reorder_frames", { order: [3, 4, 0, 1, 2] });
  await edit("set_frame_durations", { durations: [90, 140, 110, 180, 220].map((durationMs, frame) => ({ frame, durationMs })) });
  await edit("set_selection", { x1: 12, y1: 14, x2: 29, y2: 28 });
  await edit("transform_selection", { layerId: body, frames: [1, 3], operation: "flip_horizontal" });
  await edit("modify_selection", { action: "none" });
  await edit("create_tag", { name: "Review loop", from: 0, to: 4 });
  await edit("save", { path: "before-batch.ase" });
  const before = await request("inspect", { documentId });
  const edits = [];
  for (let frame = 0; frame < 5; ++frame) {
    const dx = [0, 4, 8, 4, 0][frame];
    for (const layerId of [body, accent]) {
      const cel = before.layers.find((layer) => layer.layerId === layerId).cels.find((cel) => cel.frame === frame);
      edits.push({ layerId, frame, x: cel.x + dx, y: cel.y, opacity: [255, 220, 190, 220, 255][frame] });
    }
  }
  doc = await edit("edit_cels", { edits });
  assert.equal(doc.editedCels, 6);
  await edit("save", { path: "after-batch.ase" });
  await edit("export_animation", { path: "review.gif", format: "gif", scale: 4, loop: true });
  await edit("export_sprite_sheet", { path: "review-contact.png", columns: 5, scale: 4, padding: 2 });
  await edit("set_active_site", { layerId: body, frame: 2 });
  await request("set_paused", { paused: true });
  const inspected = await request("inspect", { documentId });
  const review = { ...launched, bridgeVersion: status.bridgeVersion, documentId, layerIds: { body, accent, extra }, revision: inspected.revision, frames: 5, lastUndoStep: "Atomic six-cel position/opacity change across three frames", assets: ["before-batch.ase", "after-batch.ase", "review.gif", "review-contact.png"] };
  await writeFile(path.join(directory, "review.json"), JSON.stringify(review, null, 2) + "\n");
  console.log(JSON.stringify(review, null, 2));
  console.log("READY: five-frame animation, three layers, saved before/after files and GIF/contact previews. Connected and paused. ONE native Undo removes the entire last multi-frame cel batch; Redo restores it. Test playback/scrubbing/Pause/Resume. The monitor makes NO further document edits. Ctrl+C disconnects and leaves the GUI open.");
  let lastState;
  while (!stopping) {
    status = await request("connect");
    const state = JSON.stringify({ paused: status.paused, pausedByUser: status.pausedByUser, controlText: status.controlText });
    if (state !== lastState) {
      console.log(state);
      if (status.pausedByUser) {
        await request("set_paused", { paused: false }, "USER_PAUSED");
        console.log("PASS: remote resume cannot override an editor-side pause.");
      }
      lastState = state;
    }
    await wait(500);
  }
} finally {
  await client.close();
}
