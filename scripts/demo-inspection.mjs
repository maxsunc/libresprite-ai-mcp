// Read-only animation inspection review over real MCP. GPL-2.0-only.
// Launches only a NEW editor with generated artwork; disconnect leaves it paused.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.join(root, ".runtime", `inspection-${Date.now().toString(36)}`);
const assets = path.join(directory, "assets");
const socketPath = path.join(directory, "b.sock");
await mkdir(assets, { recursive: true, mode: 0o700 });
const environment = Object.fromEntries(Object.entries(process.env).filter(([, value]) => value !== undefined));
delete environment.SDL_VIDEODRIVER;
const transport = new StdioClientTransport({
  command: process.execPath, args: [path.join(root, "dist/index.js")],
  env: { ...environment, LIBRESPRITE_SOCKET: socketPath, LIBRESPRITE_ASSET_ROOT: assets }, stderr: "pipe",
});
const client = new Client({ name: "libresprite-inspection-review", version: "0.10.0" });
let documentId;
async function request(method, args = {}, output) {
  const response = await client.callTool({ name: `libresprite_${method}`, arguments: args });
  const metadata = JSON.parse(response.content.find((item) => item.type === "text").text);
  assert.ok(!response.isError, `${method}: ${JSON.stringify(metadata)}`);
  if (output) {
    await writeFile(path.join(assets, `${output}.json`), JSON.stringify(metadata, null, 2) + "\n");
    const image = response.content.find((item) => item.type === "image");
    if (image) await writeFile(path.join(assets, `${output}.png`), Buffer.from(image.data, "base64"));
  }
  return metadata;
}
async function edit(method, args) {
  const current = await request("inspect", { documentId });
  return request(method, { documentId, expectedRevision: current.revision, ...args });
}
const rgba = (r, g, b, a = 255) => ({ r, g, b, a });
try {
  await client.connect(transport);
  transport.stderr?.pipe(process.stderr);
  assert.equal((await client.listTools()).tools.length, 62);
  const launched = await request("launch");
  const deadline = Date.now() + 20_000;
  let status;
  while (true) {
    try { status = await request("connect"); break; }
    catch (error) {
      if (Date.now() >= deadline) throw error;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  assert.equal(status.bridgeVersion, "0.10.0");
  await request("set_paused", { paused: false });
  const document = await request("create", { width: 32, height: 24, name: "Animation inspection — generated arrow" });
  documentId = document.documentId;
  const base = document.layers[0].layerId;
  await edit("update_layer", { layerId: base, name: "Unrelated backdrop" });
  await edit("draw_shape", { layerId: base, frame: 0, shape: "rectangle", x1: 2, y1: 18, x2: 29, y2: 20, filled: true, color: rgba(30, 45, 65) });
  await edit("set_frame_duration", { frame: 0, durationMs: 91 });
  await edit("add_frame", { index: 1, copyFrom: 0, durationMs: 7 });
  await edit("add_frame", { index: 2, copyFrom: 0, durationMs: 110 });
  const group = (await edit("create_layer", { name: "Moving arrow", type: "group" })).createdLayerId;
  const moving = (await edit("create_layer", { name: "Arrow pixels", parentId: group })).createdLayerId;
  const hidden = (await edit("create_layer", { name: "Hidden study — visibility stays off" })).createdLayerId;
  const arrow = [];
  for (let y = -3; y <= 3; ++y) for (let x = 0; x <= 9; ++x) {
    if ((x <= 5 && Math.abs(y) <= 1) || (x >= 5 && Math.abs(y) <= 9 - x))
      arrow.push({ x, y, ...rgba(65, 210, 185) });
  }
  for (let frame = 0; frame < 3; ++frame) {
    await edit("set_pixels", { layerId: moving, frame, pixels: arrow.map((pixel) => ({ ...pixel, x: pixel.x + 4 + frame * 3, y: pixel.y + 10 - frame })) });
    await edit("draw_shape", { layerId: hidden, frame, shape: "ellipse", x1: 12, y1: 4, x2: 18, y2: 10, filled: true, color: rgba(240, 180, 60) });
  }
  await edit("update_layer", { layerId: hidden, visible: false });
  const tagId = (await edit("create_tag", { name: "Arrow pingpong", from: 0, to: 2, direction: "pingpong" })).createdTagId;
  await edit("set_active_site", { layerId: moving, frame: 1 });
  await edit("save", { path: "inspection-arrow.ase" });
  const before = await request("inspect", { documentId });
  await request("set_paused", { paused: true });
  await request("render", { documentId, frame: 1, scale: 6 }, "composite");
  await request("render_layer", { documentId, layerId: group, frame: 1, scale: 6 }, "isolated");
  await request("render_layer", { documentId, layerId: hidden, frame: 1, scale: 6, includeHidden: true }, "hidden-study");
  await request("render_frame_diff", { documentId, fromFrame: 0, toFrame: 1, scale: 6 }, "frame-diff");
  await request("render_frame_diff", { documentId, layerId: group, fromFrame: 0, toFrame: 1, scale: 6 }, "scoped-diff");
  await request("contact_sheet", { documentId, layerId: group, frames: [2, 0, 1], columns: 3, scale: 4, padding: 2 }, "scoped-contact");
  const analysis = await request("analyze_animation", { documentId, layerId: group, tagId }, "animation-analysis");
  assert.deepEqual(analysis.steps.map((step) => step.frame), [0, 1, 2, 1]);
  assert.equal(analysis.timing.totalDurationMs, 215);
  assert.equal(analysis.loopBoundary.fromFrame, 1);
  assert.equal(analysis.gif.exportable, false);
  const after = await request("inspect", { documentId });
  assert.equal(after.revision, before.revision);
  assert.deepEqual(after.selection, before.selection);
  assert.equal(after.activeLayerId, before.activeLayerId);
  assert.equal(after.activeFrame, before.activeFrame);
  assert.equal(after.modified, before.modified);
  assert.equal(after.canUndo, before.canUndo);
  assert.equal(after.canRedo, before.canRedo);
  assert.equal(after.layers.find((layer) => layer.layerId === hidden).visible, false);
  const review = { ...launched, socketPath, assetRoot: assets, documentId, revision: after.revision, group, moving, hidden, tagId, paused: true };
  await writeFile(path.join(directory, "review.json"), JSON.stringify(review, null, 2) + "\n");
  console.log(JSON.stringify(review, null, 2));
  console.log("PASS: all three inspection tools over real MCP; generated editor is paused and left open. See docs/testing-v0.10.md.");
} finally {
  await client.close();
}
