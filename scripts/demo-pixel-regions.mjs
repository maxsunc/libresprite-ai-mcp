// Exact reads, component masks and atomic stamping over real MCP. GPL-2.0-only.
// Uses only a NEW visible editor with generated art; leaves it paused/open.
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// Packaging review uses the REAL relocated launcher/production server.
const packagedMcp = process.env.LIBRESPRITE_MCP_ROOT;
const directory = path.join(root, ".runtime", `regions-${Date.now().toString(36)}`);
const assets = path.join(directory, "assets");
const socketPath = path.join(directory, "b.sock");
await mkdir(assets, { recursive: true, mode: 0o700 });
const environment = Object.fromEntries(Object.entries(process.env).filter(([, value]) => value !== undefined));
delete environment.SDL_VIDEODRIVER;
const transport = new StdioClientTransport({ command: packagedMcp ? "bash" : process.execPath,
  args: [packagedMcp ? path.join(packagedMcp, "start-mcp.sh") : path.join(root, "dist/index.js")],
  env: { ...environment, LIBRESPRITE_SOCKET: socketPath, LIBRESPRITE_ASSET_ROOT: assets }, stderr: "pipe" });
const client = new Client({ name: "libresprite-pixel-region-review", version: "0.12.0" });
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
  const state = await request("inspect", { documentId });
  return request(method, { documentId, expectedRevision: state.revision, ...args }, output);
}
function stable(state) {
  const result = structuredClone(state);
  for (const layer of result.layers) {
    if (layer.version === 0) layer.version = 1;
    for (const cel of layer.cels ?? []) if (cel.imageVersion === 0) cel.imageVersion = 1;
  }
  return result;
}
function preserved(before, after) {
  for (const key of ["frames", "palettes", "tags", "selection", "activeLayerId", "activeFrame"])
    assert.deepEqual(after[key], before[key], key);
}
const color = (r, g, b, a = 255) => ({ r, g, b, a });
try {
  await client.connect(transport); transport.stderr?.pipe(process.stderr);
  assert.equal((await client.listTools()).tools.length, 67);
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
  assert.equal(status.bridgeVersion, "0.12.0");
  await request("set_paused", { paused: false });
  const doc = await request("create", { width: 32, height: 24, name: "Pixel regions — generated reusable part" });
  documentId = doc.documentId;
  const base = doc.layers[0].layerId;
  await edit("update_layer", { layerId: base, name: "Unchanged backdrop / focus" });
  await edit("draw_shape", { layerId: base, frame: 0, shape: "rectangle", filled: true, x1: 2, y1: 20, x2: 29, y2: 21, color: color(35, 45, 65) });
  await edit("set_frame_duration", { frame: 0, durationMs: 90 });
  await edit("add_frame", { index: 1, copyFrom: 0, durationMs: 120 });
  await edit("add_frame", { index: 2, copyFrom: 0, durationMs: 100 });
  const sourceLayer = (await edit("create_layer", { name: "Reusable part — hidden/locked" })).createdLayerId;
  const destination = (await edit("create_layer", { name: "Stamped copies" })).createdLayerId;
  const shape = ["01000", "11110", "11111", "11110", "01000"];
  const pixels = [];
  for (let y = 0; y < shape.length; ++y) for (let x = 0; x < shape[y].length; ++x) {
    if (shape[y][x] === "1") pixels.push({ x: x + 2, y: y + 2, ...color(x < 2 ? 45 : 100, 195 + y * 8, 185, x === 4 ? 128 : 255) });
  }
  pixels.push({ x: 8, y: 8, ...color(245, 165, 50) }); // Disconnected distractor.
  await edit("set_pixels", { layerId: sourceLayer, frame: 0, pixels });
  await edit("update_layer", { layerId: sourceLayer, visible: false, editable: false });
  const tagId = (await edit("create_tag", { name: "Reusable part motion", from: 0, to: 2, direction: "pingpong" })).createdTagId;
  await edit("set_bitmap_selection", { x: 29, y: 1, width: 2, height: 2, bits: "1001" });
  await edit("set_active_site", { layerId: base, frame: 1 });
  await edit("save", { path: "regions-before.ase" });
  let baseline = await request("inspect", { documentId });
  const rectangle = { x: 0, y: 0, width: 10, height: 10 };
  await request("set_paused", { paused: true });
  const raw = await request("read_pixels", { documentId, layerId: sourceLayer, frame: 0, ...rectangle }, "source-pixels");
  assert.equal(raw.encoding, "runs");
  const decoded = raw.rows.flatMap((row) => row.flatMap(([length, value]) => Array(length).fill(value)));
  for (const pixel of pixels)
    assert.equal(decoded[pixel.y * 10 + pixel.x], pixel.r + pixel.g * 256 + pixel.b * 65536 + pixel.a * 16777216);
  const mask = await request("extract_mask", { documentId, layerId: sourceLayer, frame: 0, ...rectangle, seed: { x: 3, y: 3 }, connectivity: 4 }, "source-mask");
  assert.equal(mask.selectedPixels, pixels.length - 1);
  assert.equal(mask.mask.bits[8 * 10 + 8], "0");
  const sourcePng = await request("render_layer", { documentId, layerId: sourceLayer, frame: 0, includeHidden: true }, "source-part");
  const maskBefore = await request("render_selection", { documentId, frame: 1, mode: "mask" }, "gui-mask-before");
  const sheet = { documentId, frames: [0, 1, 2], columns: 3, scale: 4, padding: 2 };
  const beforeSheet = await request("contact_sheet", sheet, "before-contact");
  assert.deepEqual(stable(await request("inspect", { documentId })), stable(baseline));
  await request("set_paused", { paused: false });
  if (packagedMcp) {
    // Exercise BOTH correction methods over the production MCP server, then
    // restore generated artwork before the final stamp clears this redo branch.
    const edits = [0, 1, 2].map((frame) => ({ layerId: destination, frame,
      pixels: [{ x: 1, y: 1, ...color(235, 140, 75) }] }));
    const predicted = await edit("edit_pixels", { edits, dryRun: true }, "package-pixel-dry-run");
    assert.equal(predicted.changedPixels, 3); assert.equal(predicted.editedCels, 0);
    assert.deepEqual(stable(await request("inspect", { documentId })), stable(baseline));
    const applied = await edit("edit_pixels", { edits }, "package-pixel-applied");
    assert.deepEqual(applied.changes, predicted.changes); preserved(baseline, applied);
    const moves = [0, 1, 2].map((frame) => ({ layerId: destination, frame,
      mask: { x: 1, y: 1, width: 1, height: 1, bits: "1" }, dx: 1, dy: 0 }));
    const movePrediction = await edit("translate_regions", { edits: moves, dryRun: true }, "package-region-dry-run");
    assert.equal(movePrediction.changedPixels, 6);
    const moved = await edit("translate_regions", { edits: moves }, "package-region-applied");
    assert.deepEqual(moved.changes, movePrediction.changes); preserved(baseline, moved);
    assert.deepEqual((await request("render_layer", { documentId, layerId: destination, frame: 1 })).analysis.bounds,
      { x: 2, y: 1, width: 1, height: 1 });
    await edit("undo");
    assert.deepEqual((await request("render_layer", { documentId, layerId: destination, frame: 1 })).analysis.bounds,
      { x: 1, y: 1, width: 1, height: 1 });
    await edit("undo");
    assert.equal((await request("contact_sheet", sheet)).pngBase64, beforeSheet.pngBase64);
    const restored = await request("inspect", { documentId });
    assert.equal(restored.modified, false); preserved(baseline, restored);
    baseline = restored; // Native Undo advances versions/revision, not artwork.
  }
  const params = { source: { layerId: sourceLayer, frame: 0, ...rectangle }, mode: "nontransparent", maskBits: mask.mask.bits,
    label: "Review: reusable part across three frames", edits: [
      { layerId: destination, frame: 0, x: 3, y: 6 },
      { layerId: destination, frame: 1, x: 8, y: 5 },
      { layerId: destination, frame: 2, x: 14, y: 7 },
    ] };
  const preview = await edit("stamp_region", { ...params, dryRun: true }, "stamp-dry-run");
  assert.equal(preview.editedCels, 0); assert.equal(preview.wouldEditCels, 3);
  assert.deepEqual(stable(await request("inspect", { documentId })), stable(baseline));
  const documents = await request("list_documents");
  const pngPreview = await edit("stamp_region", { ...params, source: { path: "source-part.png", ...rectangle }, dryRun: true }, "png-dry-run");
  assert.equal(pngPreview.sourceHash, preview.sourceHash);
  assert.deepEqual(pngPreview.changes, preview.changes);
  assert.deepEqual(await request("list_documents"), documents);
  const applied = await edit("stamp_region", { ...params, expectedSourceHash: preview.sourceHash }, "stamp-applied");
  assert.deepEqual(applied.changes, preview.changes); preserved(baseline, applied);
  const afterSheet = await request("contact_sheet", sheet, "after-contact");
  assert.notEqual(afterSheet.pngBase64, beforeSheet.pngBase64);
  await edit("undo");
  assert.equal((await request("contact_sheet", sheet, "undo-contact")).pngBase64, beforeSheet.pngBase64);
  assert.equal((await request("inspect", { documentId })).modified, false);
  await edit("redo");
  assert.equal((await request("contact_sheet", sheet)).pngBase64, afterSheet.pngBase64);
  const beforeNoOp = await request("inspect", { documentId });
  assert.equal((await edit("stamp_region", params)).changedPixels, 0);
  assert.deepEqual(stable(await request("inspect", { documentId })), stable(beforeNoOp));
  assert.equal((await request("render_selection", { documentId, frame: 1, mode: "mask" }, "gui-mask-after")).pngBase64, maskBefore.pngBase64);
  assert.equal((await request("render_layer", { documentId, layerId: sourceLayer, frame: 0, includeHidden: true })).pngBase64, sourcePng.pngBase64);
  await edit("save", { path: "regions-after.ase" });
  if (packagedMcp) {
    const beforeExports = await request("inspect", { documentId });
    await edit("export_png", { path: "package-review.png", frame: 1, scale: 6 });
    await edit("export_sprite_sheet", { path: "package-contact.png", frames: sheet.frames,
      columns: sheet.columns, scale: sheet.scale, padding: sheet.padding });
    assert.equal((await readFile(path.join(assets, "package-contact.png"))).toString("base64"), afterSheet.pngBase64);
    await edit("export_animation", { path: "package-review.gif", format: "gif", tagId, scale: 4 });
    await edit("export_animation", { path: "package-review.apng", format: "apng", tagId, scale: 4 });
    assert.match((await readFile(path.join(assets, "package-review.gif"))).subarray(0, 6).toString(), /^GIF8[79]a$/);
    const apng = await readFile(path.join(assets, "package-review.apng"));
    assert.equal(apng.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
    assert.ok(apng.includes(Buffer.from("acTL")));
    assert.deepEqual(stable(await request("inspect", { documentId })), stable(beforeExports));
  }
  await request("set_paused", { paused: true });
  const state = await request("inspect", { documentId }); preserved(baseline, state);
  if (packagedMcp) {
    const difference = await request("render_frame_diff", { documentId, layerId: destination,
      fromFrame: 0, toFrame: 1, scale: 4 }, "package-frame-diff");
    assert.ok(difference.difference.changedPixels > 0);
    const analysis = await request("analyze_animation", { documentId, layerId: destination, tagId }, "package-analysis");
    assert.deepEqual(analysis.steps.map((step) => step.frame), [0, 1, 2, 1]);
    assert.equal(analysis.timing.totalDurationMs, 430);
    assert.deepEqual(stable(await request("inspect", { documentId })), stable(state));
  }
  assert.equal(state.layers.find((layer) => layer.layerId === sourceLayer).visible, false);
  assert.equal(state.layers.find((layer) => layer.layerId === sourceLayer).editable, false);
  const review = { ...launched, ...(packagedMcp ? { packagedMcp: path.resolve(packagedMcp) } : {}),
    socketPath, assetRoot: assets, documentId, revision: state.revision, base, sourceLayer, destination, tagId, sourceHash: preview.sourceHash, paused: true };
  await writeFile(path.join(directory, "review.json"), JSON.stringify(review, null, 2) + "\n");
  console.log(JSON.stringify(review, null, 2));
  console.log("PASS: all three pixel-region features over real MCP, PNG/live source equivalence, dry-run/apply/Undo/Redo/no-op and preserved source/mask/focus/metadata. Generated editor remains paused/open. See docs/testing-v0.12.md.");
  if (packagedMcp) console.log("PASS: relocated production MCP/app, both atomic correction tools/Undo, paused frame differences/timing analysis and PNG/sheet/GIF/APNG exports. See docs/testing-package-v0.12.md.");
} finally {
  await client.close();
}
