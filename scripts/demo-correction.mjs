// Atomic animation correction review over real MCP. GPL-2.0-only.
// Launches only a NEW editor with generated artwork; disconnect leaves it paused.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.join(root, ".runtime", `correction-${Date.now().toString(36)}`);
const assets = path.join(directory, "assets");
const socketPath = path.join(directory, "b.sock");
await mkdir(assets, { recursive: true, mode: 0o700 });
const environment = Object.fromEntries(Object.entries(process.env).filter(([, value]) => value !== undefined));
delete environment.SDL_VIDEODRIVER;
const transport = new StdioClientTransport({
  command: process.execPath, args: [path.join(root, "dist/index.js")],
  env: { ...environment, LIBRESPRITE_SOCKET: socketPath, LIBRESPRITE_ASSET_ROOT: assets }, stderr: "pipe",
});
const client = new Client({ name: "libresprite-correction-review", version: "0.11.0" });
let documentId;
async function request(method, args = {}, output) {
  const response = await client.callTool({ name: `libresprite_${method}`, arguments: args });
  const metadata = JSON.parse(response.content.find((item) => item.type === "text").text);
  assert.ok(!response.isError, `${method}: ${JSON.stringify(metadata)}`);
  const image = response.content.find((item) => item.type === "image");
  if (output) {
    await writeFile(path.join(assets, `${output}.json`), JSON.stringify(metadata, null, 2) + "\n");
    if (image) await writeFile(path.join(assets, `${output}.png`), Buffer.from(image.data, "base64"));
  }
  return image ? { ...metadata, pngBase64: image.data } : metadata;
}
async function edit(method, args = {}, output) {
  const current = await request("inspect", { documentId });
  return request(method, { documentId, expectedRevision: current.revision, ...args }, output);
}
const rgba = (r, g, b, a = 255) => ({ r, g, b, a });
function stableInspection(state) {
  // Match native revision fingerprints: recovery's initial 0->1 is equivalent,
  // but all IDs, higher versions, properties and history remain significant.
  const result = structuredClone(state);
  for (const layer of result.layers) {
    if (layer.version === 0) layer.version = 1;
    for (const cel of layer.cels ?? []) if (cel.imageVersion === 0) cel.imageVersion = 1;
  }
  return result;
}
function unchangedMetadata(before, after) {
  for (const key of ["frames", "tags", "palettes", "selection", "activeFrame", "activeLayerId"])
    assert.deepEqual(after[key], before[key], key);
}
try {
  await client.connect(transport);
  transport.stderr?.pipe(process.stderr);
  assert.equal((await client.listTools()).tools.length, 64);
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
  assert.equal(status.bridgeVersion, "0.11.0");
  await request("set_paused", { paused: false });
  const document = await request("create", { width: 32, height: 24, name: "Animation correction — generated arrow" });
  documentId = document.documentId;
  const base = document.layers[0].layerId;
  await edit("update_layer", { layerId: base, name: "Unrelated backdrop / focus stays here" });
  await edit("draw_shape", { layerId: base, frame: 0, shape: "rectangle", x1: 2, y1: 18, x2: 29, y2: 20, filled: true, color: rgba(30, 45, 65) });
  await edit("set_frame_duration", { frame: 0, durationMs: 90 });
  await edit("add_frame", { index: 1, copyFrom: 0, durationMs: 120 });
  await edit("add_frame", { index: 2, copyFrom: 0, durationMs: 100 });
  const group = (await edit("create_layer", { name: "Moving arrow", type: "group" })).createdLayerId;
  const moving = (await edit("create_layer", { name: "Corrected pixels", parentId: group })).createdLayerId;
  const hidden = (await edit("create_layer", { name: "Hidden study — unchanged" })).createdLayerId;
  const arrow = [];
  for (let y = -3; y <= 3; ++y) for (let x = 0; x <= 9; ++x) {
    if ((x <= 5 && Math.abs(y) <= 1) || (x >= 5 && Math.abs(y) <= 9 - x))
      arrow.push({ x, y, ...rgba(65, 210, 185) });
  }
  const centers = [10, 8, 9];
  for (let frame = 0; frame < 3; ++frame) {
    const pixels = arrow.map((pixel) => ({ ...pixel, x: pixel.x + 4 + frame * 3, y: pixel.y + centers[frame] }));
    pixels.push({ x: 27, y: 4 + frame, ...rgba(240, 180, 60) });
    await edit("set_pixels", { layerId: moving, frame, pixels });
    await edit("draw_shape", { layerId: hidden, frame, shape: "ellipse", x1: 12, y1: 4, x2: 18, y2: 10, filled: true, color: rgba(240, 180, 60) });
  }
  await edit("update_layer", { layerId: hidden, visible: false });
  const tagId = (await edit("create_tag", { name: "Arrow pingpong", from: 0, to: 2, direction: "pingpong" })).createdTagId;
  // The selection intentionally does NOT cover correction coordinates.
  await edit("set_bitmap_selection", { x: 1, y: 1, width: 2, height: 2, bits: "1001" });
  await edit("set_active_site", { layerId: base, frame: 1 });
  await edit("save", { path: "correction-arrow-before.ase" });
  const baseline = await request("inspect", { documentId });
  const sheet = { documentId, frames: [0, 1, 2], columns: 3, scale: 4, padding: 2 };
  const beforeSheet = await request("contact_sheet", sheet, "before-contact");
  const beforeHidden = await request("render_layer", { documentId, layerId: hidden, frame: 1, includeHidden: true }, "hidden-before");
  const beforeMask = await request("render_selection", { documentId, frame: 1, mode: "mask" }, "mask-before");

  const pixelBatch = {
    label: "Review: pixel cleanup across three frames",
    edits: centers.map((center, frame) => ({ layerId: moving, frame, pixels: [
      { x: 27, y: 4 + frame, ...rgba(0, 0, 0, 0) },
      { x: 13 + frame * 3, y: center, ...rgba(120, 240, 225) },
    ] })),
  };
  const pixelDryRun = await edit("edit_pixels", { ...pixelBatch, dryRun: true }, "pixel-dry-run");
  assert.equal(pixelDryRun.editedCels, 0);
  assert.equal(pixelDryRun.wouldEditCels, 3);
  assert.equal(pixelDryRun.changedPixels, 6);
  assert.deepEqual(stableInspection(await request("inspect", { documentId })), stableInspection(baseline));
  const pixelsApplied = await edit("edit_pixels", pixelBatch, "pixel-applied");
  assert.deepEqual(pixelsApplied.changes, pixelDryRun.changes);
  unchangedMetadata(baseline, pixelsApplied);
  const pixelsSheet = await request("contact_sheet", sheet, "pixels-contact");

  const regionBatch = {
    label: "Review: explicit per-frame vertical alignment",
    edits: [1, 2].map((frame) => {
      const bits = Array(10 * 7).fill("0");
      for (const pixel of arrow) bits[(pixel.y + 3) * 10 + pixel.x] = "1";
      return { layerId: moving, frame, mask: { x: 4 + frame * 3, y: centers[frame] - 3, width: 10, height: 7, bits: bits.join("") }, dx: 0, dy: 10 - centers[frame] };
    }),
  };
  const pixelsState = await request("inspect", { documentId });
  const regionDryRun = await edit("translate_regions", { ...regionBatch, dryRun: true }, "region-dry-run");
  assert.equal(regionDryRun.editedCels, 0);
  assert.equal(regionDryRun.wouldEditCels, 2);
  assert.deepEqual(stableInspection(await request("inspect", { documentId })), stableInspection(pixelsState));
  const regionsApplied = await edit("translate_regions", regionBatch, "region-applied");
  assert.deepEqual(regionsApplied.changes, regionDryRun.changes);
  unchangedMetadata(baseline, regionsApplied);
  const afterSheet = await request("contact_sheet", sheet, "after-contact");
  assert.notEqual(afterSheet.pngBase64, pixelsSheet.pngBase64);

  // Each correction batch is exactly ONE history step, including across frames.
  await edit("undo");
  assert.equal((await request("contact_sheet", sheet, "undo-regions-contact")).pngBase64, pixelsSheet.pngBase64);
  await edit("undo");
  assert.equal((await request("contact_sheet", sheet, "undo-both-contact")).pngBase64, beforeSheet.pngBase64);
  assert.equal((await request("inspect", { documentId })).modified, false);
  await edit("redo");
  await edit("redo");
  assert.equal((await request("contact_sheet", sheet)).pngBase64, afterSheet.pngBase64);
  const noOpState = await request("inspect", { documentId });
  assert.equal((await edit("edit_pixels", { edits: pixelBatch.edits.map(({ layerId, frame, pixels }) => ({ layerId, frame, pixels: [pixels[0]] })) })).changedPixels, 0);
  assert.deepEqual(stableInspection(await request("inspect", { documentId })), stableInspection(noOpState));
  assert.equal((await request("render_layer", { documentId, layerId: hidden, frame: 1, includeHidden: true }, "hidden-after")).pngBase64, beforeHidden.pngBase64);
  assert.equal((await request("render_selection", { documentId, frame: 1, mode: "mask" }, "mask-after")).pngBase64, beforeMask.pngBase64);
  await edit("save", { path: "correction-arrow-after.ase" });
  await request("set_paused", { paused: true });
  const after = await request("inspect", { documentId });
  unchangedMetadata(baseline, after);
  assert.equal(after.layers.find((layer) => layer.layerId === hidden).visible, false);
  const review = { ...launched, socketPath, assetRoot: assets, documentId, revision: after.revision, base, group, moving, hidden, tagId, paused: true, correctionUndoSteps: 2 };
  await writeFile(path.join(directory, "review.json"), JSON.stringify(review, null, 2) + "\n");
  console.log(JSON.stringify(review, null, 2));
  console.log("PASS: real-MCP pixel/region dry runs, atomic apply and Undo/Redo, exact previews and preserved mask/focus/metadata. Generated editor is paused and left open. See docs/testing-v0.11.md.");
} finally {
  await client.close();
}
