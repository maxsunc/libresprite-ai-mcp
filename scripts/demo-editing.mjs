// Step 3 review over actual MCP in a NEW editor. GPL-2.0-only.
// Generated sprites only; Ctrl+C disconnects/pauses and leaves the GUI open.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// Optional packaging review uses the REAL relocated launcher/production server.
const packagedMcp = process.env.LIBRESPRITE_MCP_ROOT;
const directory = path.join(root, ".runtime", `edit-${Date.now().toString(36)}`);
const assets = path.join(directory, "assets");
await mkdir(assets, { recursive: true, mode: 0o700 });
const environment = Object.fromEntries(Object.entries(process.env).filter(([, value]) => value !== undefined));
delete environment.SDL_VIDEODRIVER;
const transport = new StdioClientTransport({
  command: packagedMcp ? "bash" : process.execPath,
  args: [packagedMcp ? path.join(packagedMcp, "start-mcp.sh") : path.join(root, "dist/index.js")],
  env: { ...environment, LIBRESPRITE_SOCKET: path.join(directory, "b.sock"), LIBRESPRITE_ASSET_ROOT: assets },
  stderr: "pipe",
});
const client = new Client({ name: "libresprite-editing-review", version: "0.9.0" });
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
  const doc = await request("inspect", { documentId });
  return { documentId, expectedRevision: doc.revision };
}
async function edit(method, args) { return request(method, { ...await target(), ...args }); }
async function activate(id) {
  const docs = await request("list_documents");
  const doc = await request("inspect", { documentId: id });
  await request("activate_document", { documentId: id, expectedRevision: doc.revision, expectedActiveDocumentId: docs.activeDocumentId });
  documentId = id;
}
const rgba = (r, g, b, a = 255) => ({ r, g, b, a });
const swatches = [rgba(0, 0, 0, 0), rgba(25, 34, 58), rgba(25, 88, 109), rgba(31, 153, 165), rgba(83, 220, 210), rgba(221, 255, 232), rgba(240, 178, 70), rgba(103, 75, 141)];
const star = { width: 7, height: 7, bits: ["0001000", "0001000", "0011100", "1111111", "0011100", "0001000", "0001000"].join("") };
// A small original generated crystal/pedestal icon, not working project artwork.
const pedestal = [], crystal = [], highlights = [];
for (let y = 0; y < 48; ++y) for (let x = 0; x < 48; ++x) {
  const dx = x - 24;
  if (y >= 32 && y <= 39 && Math.abs(dx) <= (y === 32 || y === 39 ? 10 : 14)) {
    const edge = y === 39 || Math.abs(dx) >= 12;
    pedestal.push({ x, y, index: edge ? 1 : y <= 34 ? 7 : y <= 36 ? 2 : 1 });
  }
  if ((y === 34 || y === 36) && Math.abs(dx) <= 10) pedestal.push({ x, y, index: y === 34 ? 6 : 3 });
  if (y >= 6 && y <= 31) {
    const radius = Math.floor((y <= 17 ? y - 6 : 31 - y) * 0.65);
    if (Math.abs(dx) <= radius) {
      const edge = Math.abs(dx) === radius || y === 6 || y === 31;
      crystal.push({ x, y, index: edge ? 1 : dx < -2 ? 4 : dx <= 1 ? 3 : 2 });
      if (!edge && dx === -Math.max(1, radius - 2) && y < 22) highlights.push({ x, y, index: 5 });
    }
  }
}
const colors = (pixels) => pixels.map(({ x, y, index }) => ({ x, y, ...swatches[index] }));
try {
  await client.connect(transport);
  transport.stderr?.pipe(process.stderr);
  assert.ok((await client.listTools()).tools.some((tool) => tool.name === "libresprite_draw_brush_stroke"));
  const launched = await request("launch");
  const deadline = Date.now() + 15_000;
  let status;
  while (true) {
    try { status = await request("connect"); break; }
    catch (error) { if (Date.now() > deadline) throw error; await wait(100); }
  }
  // The approved v0.9 package remains a valid step-3 regression target.
  assert.ok(status.methods.includes("draw_brush_stroke"));
  await request("set_paused", { paused: false });
  let doc = await request("create", { width: 48, height: 48, name: "Step 3 — RGBA crystal / crop undo" });
  documentId = doc.documentId;
  const rgbaDocumentId = documentId;
  const base = doc.layers[0].layerId;
  await edit("update_layer", { layerId: base, name: "Pedestal — original pixel clusters" });
  await edit("set_pixels", { layerId: base, frame: 0, pixels: colors(pedestal) });
  const scene = (await edit("create_layer", { name: "Scene — reparenting example", type: "group" })).createdLayerId;
  const group = (await edit("create_layer", { name: "Crystal — independent subtree source", type: "group" })).createdLayerId;
  const gem = (await edit("create_layer", { name: "Faceted cyan crystal", parentId: group })).createdLayerId;
  const shine = (await edit("create_layer", { name: "Screen highlight / custom stars", parentId: group })).createdLayerId;
  await edit("set_pixels", { layerId: gem, frame: 0, pixels: colors(crystal) });
  await edit("set_pixels", { layerId: shine, frame: 0, pixels: colors(highlights) });
  await edit("update_layer", { layerId: shine, blendMode: "screen", opacity: 220 });
  await edit("reparent_layer", { layerId: group, parentId: scene });
  await edit("add_frame", { index: 1, copyFrom: 0, durationMs: 140 });
  await edit("add_frame", { index: 2, copyFrom: 0, durationMs: 180 });
  for (let frame = 0; frame < 3; ++frame) {
    await edit("draw_brush_stroke", { layerId: shine, frame, brush: star, points: [{ x: 12 + frame * 2, y: 15 - frame * 2 }], color: swatches[5] });
  }
  const study = (await edit("duplicate_layer", { layerId: group, name: "Independent study copy (hidden)", parentId: null })).createdLayerId;
  await edit("update_layer", { layerId: study, visible: false });
  await edit("set_polygon_selection", { vertices: [{ x: 20, y: 25 }, { x: 24, y: 21 }, { x: 28, y: 25 }, { x: 24, y: 30 }] });
  await edit("fill_selection", { layerId: gem, frame: 1, color: swatches[4] });
  await edit("modify_selection", { action: "none" });
  await edit("create_tag", { name: "Crystal glimmer", from: 0, to: 2 });
  await edit("resize_canvas", { width: 64, height: 56, offsetX: 8, offsetY: 4 });
  const border = (await edit("create_layer", { name: "Outside-crop gold markers — Undo restores ALL frames" })).createdLayerId;
  for (let frame = 0; frame < 3; ++frame) {
    await edit("draw_brush_stroke", { layerId: border, frame, brush: star, points: [{ x: 4, y: 10 + frame * 10 }], color: swatches[6] });
  }
  const maskBits = Array.from({ length: 12 * 12 }, (_, i) => (Math.floor(i / 12) + i % 12) % 3 === 0 ? "1" : "0").join("");
  await edit("set_bitmap_selection", { x: 4, y: 2, width: 12, height: 12, bits: maskBits });
  await edit("save", { path: "rgba-before-crop.ase" });
  await edit("export_png", { path: "rgba-before-crop.png", frame: 1, scale: 5 });
  await request("crop_canvas", { ...await target(), x: 8, y: 4, width: 48, height: 48 }, "WOULD_DISCARD_PIXELS");
  doc = await edit("crop_canvas", { x: 8, y: 4, width: 48, height: 48, discardOutside: true });
  assert.equal(doc.width, 48); assert.ok(doc.discardedOutside);
  await edit("save", { path: "rgba-after-crop.ase" });
  await edit("export_png", { path: "rgba-after-crop.png", frame: 1, scale: 5 });
  await edit("export_sprite_sheet", { path: "rgba-contact.png", columns: 3, scale: 5, padding: 2 });
  await edit("export_animation", { path: "rgba-review.gif", format: "gif", scale: 5 });
  if (packagedMcp) await edit("export_animation", { path: "rgba-review.apng", format: "apng", scale: 5 });
  const rgbaRevision = (await request("inspect", { documentId })).revision;

  doc = await request("create", { width: 48, height: 48, name: "Step 3 — exact indexed crystal", colorMode: "indexed" });
  documentId = doc.documentId;
  const indexedDocumentId = documentId, indexedLayer = doc.layers[0].layerId;
  await edit("update_layer", { layerId: indexedLayer, name: "Exact palette bytes — no RGBA conversion" });
  await edit("set_palette", { frame: 0, size: swatches.length, entries: swatches.map((color, index) => ({ index, color })) });
  await edit("set_indexed_pixels", { layerId: indexedLayer, frame: 0, pixels: [...pedestal, ...crystal, ...highlights] });
  await edit("draw_brush_stroke", { layerId: indexedLayer, frame: 0, brush: star, points: [{ x: 12, y: 15 }], index: 6 });
  await edit("set_bitmap_selection", { x: 21, y: 10, width: 3, height: 3, bits: "010111010" });
  await edit("draw_brush_stroke", { layerId: indexedLayer, frame: 0, brush: star, points: [{ x: 22, y: 11 }], index: 5, respectSelection: true });
  await edit("modify_selection", { action: "none" });
  await edit("save", { path: "indexed-crystal.ase" });
  await edit("export_png", { path: "indexed-crystal.png", frame: 0, scale: 5 });
  await activate(rgbaDocumentId);
  await edit("set_active_site", { layerId: gem, frame: 1 });
  await request("set_paused", { paused: true });
  doc = await request("inspect", { documentId });
  assert.equal(doc.revision, rgbaRevision);
  const review = {
    ...launched, bridgeVersion: status.bridgeVersion, ...(packagedMcp ? { packagedMcp } : {}),
    rgba: { documentId: rgbaDocumentId, revision: doc.revision, layerIds: { base, scene, group, gem, shine, study, border }, frames: 3, beforeSize: [64, 56], afterSize: [48, 48] },
    indexed: { documentId: indexedDocumentId, layerId: indexedLayer, paletteSize: swatches.length, transparentIndex: 0 },
    lastUndoStep: "ALL-frame canvas crop: restores original size, discarded gold stars and selection in ONE Undo",
    assets: ["rgba-before-crop.ase", "rgba-after-crop.ase", "rgba-before-crop.png", "rgba-after-crop.png", "rgba-contact.png", "rgba-review.gif", "indexed-crystal.ase", "indexed-crystal.png", ...(packagedMcp ? ["rgba-review.apng"] : [])],
  };
  await writeFile(path.join(directory, "review.json"), JSON.stringify(review, null, 2) + "\n");
  console.log(JSON.stringify(review, null, 2));
  console.log("READY: generated RGBA/indexed crystals. Connected and paused on RGBA after crop. ONE native Undo restores the 64×56 canvas, outside gold stars on ALL three frames, and full sparse mask; Redo returns to 48×48. Other tab is an eight-color indexed sprite. The monitor makes NO further document edits/navigation. Ctrl+C disconnects but leaves the GUI open.");
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
