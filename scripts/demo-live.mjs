// End-to-end demonstration through the actual MCP stdio protocol. GPLv2.
// Leaves its own editor open and paused. Never attaches to another window.
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.join(root, ".runtime", `demo-${Date.now().toString(36)}`);
const assets = path.join(directory, "assets");
await mkdir(directory, { recursive: true, mode: 0o700 });
const environment = Object.fromEntries(Object.entries(process.env).filter(([, value]) => value !== undefined));
delete environment.SDL_VIDEODRIVER;
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [path.join(root, "dist/index.js")],
  env: { ...environment, LIBRESPRITE_SOCKET: path.join(directory, "b.sock"), LIBRESPRITE_ASSET_ROOT: assets },
  stderr: "pipe",
});
const client = new Client({ name: "libresprite-live-demo", version: "0.3.0" });
const animation = process.argv.includes("--animation");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function call(name, args = {}) {
  const response = await client.callTool({ name, arguments: args });
  if (response.isError) throw new Error(`${name}: ${JSON.stringify(response.content)}`);
  const content = response.content;
  const metadata = JSON.parse(content.find((item) => item.type === "text").text);
  return { metadata, content };
}

try {
  await client.connect(transport);
  transport.stderr?.pipe(process.stderr);
  assert.equal((await client.listTools()).tools.length, 28);
  console.log((await call("libresprite_launch")).metadata);
  const deadline = Date.now() + 15_000;
  while (true) {
    try { await call("libresprite_connect"); break; }
    catch (error) { if (Date.now() > deadline) throw error; await wait(100); }
  }
  await call("libresprite_set_paused", { paused: false });
  let document = (await call("libresprite_create", { width: 32, height: 32, name: animation ? "MCP animation demo - mushroom" : "MCP live demo - mushroom" })).metadata;
  const documentId = document.documentId;
  const layerId = document.layers[0].layerId;
  const rows = [
    "................",
    "......OOOO......",
    "....OORRRROO....",
    "...ORRWWRRRRO...",
    "..ORRWWWRRWWRO..",
    "..ORRRRRRRWWRO..",
    ".ORRWWRRRRRRRRO.",
    ".ORRWWRRWWRRRRO.",
    ".OOOOOOOOOOOOOO.",
    ".....OCCCCO.....",
    ".....OCKKCO.....",
    ".....OCCCCO.....",
    ".....OCCCCO.....",
    "....OOCCCCOO....",
    "..GGGOOOOGGGGG..",
    "................",
  ];
  const palette = { O: [62, 38, 68], R: [234, 92, 79], W: [255, 219, 172], C: [239, 193, 140], K: [62, 38, 68], G: [60, 157, 126] };
  for (let first = 0; first < rows.length; first += 3) {
    const pixels = [];
    for (let y = first; y < Math.min(first + 3, rows.length); y++) {
      for (let x = 0; x < rows[y].length; x++) {
        const color = palette[rows[y][x]];
        if (color) pixels.push({ x: x + 8, y: y + 8, r: color[0], g: color[1], b: color[2], a: 255 });
      }
    }
    if (!pixels.length) continue;
    document = (await call("libresprite_set_pixels", { documentId, layerId, expectedRevision: document.revision, frame: 0, label: `Mushroom rows ${first + 1}-${Math.min(first + 3, rows.length)}`, pixels })).metadata;
    await wait(200);
  }
  let previewFrame = 0;
  async function mutate(method, args) {
    document = (await call(`libresprite_${method}`, { documentId, expectedRevision: document.revision, ...args })).metadata;
    await wait(120);
    return document;
  }
  if (animation) {
    await mutate("update_layer", { layerId, name: "Mushroom" });
    const backdrop = (await mutate("create_layer", { name: "Backdrop", afterLayerId: null })).createdLayerId;
    await mutate("flood_fill", { layerId: backdrop, frame: 0, x: 0, y: 0, color: { r: 27, g: 35, b: 60, a: 255 } });
    const effects = (await mutate("create_layer", { name: "Effects", type: "group" })).createdLayerId;
    const sparkle = (await mutate("create_layer", { name: "Sparkles", parentId: effects })).createdLayerId;
    const cream = { r: 255, g: 219, b: 172, a: 255 };
    const clear = { r: 0, g: 0, b: 0, a: 0 };
    await mutate("draw_stroke", { layerId: sparkle, frame: 0, color: cream, points: [{ x: 3, y: 4 }, { x: 3, y: 8 }] });
    await mutate("draw_stroke", { layerId: sparkle, frame: 0, color: cream, points: [{ x: 1, y: 6 }, { x: 5, y: 6 }] });
    for (let frame = 1; frame < 4; frame++) {
      await mutate("add_frame", { index: frame, copyFrom: 0, durationMs: [100, 150, 100, 200][frame] });
      await mutate("draw_shape", { layerId: sparkle, frame, shape: "rectangle", x1: 0, y1: 0, x2: 31, y2: 31, color: clear, filled: true });
      const [x, y] = [[25, 6], [25, 25], [5, 25]][frame - 1];
      await mutate("draw_stroke", { layerId: sparkle, frame, color: cream, points: [{ x, y: y - 2 }, { x, y: y + 2 }] });
      await mutate("draw_stroke", { layerId: sparkle, frame, color: cream, points: [{ x: x - 2, y }, { x: x + 2, y }] });
    }
    assert.equal(document.frameCount, 4);
    assert.equal(document.layers.length, 4);
    assert.ok(document.layers.every((layer) => (layer.cels ?? []).every((cel) => cel.links === 0)));
    previewFrame = 3;
  }
  const beforeUndo = await call("libresprite_render", { documentId, frame: previewFrame, scale: 8 });
  document = (await call("libresprite_undo", { documentId, expectedRevision: document.revision })).metadata;
  await wait(200);
  document = (await call("libresprite_redo", { documentId, expectedRevision: document.revision })).metadata;
  const afterRedo = await call("libresprite_render", { documentId, frame: previewFrame, scale: 8 });
  const image = afterRedo.content.find((item) => item.type === "image");
  assert.equal(image.data, beforeUndo.content.find((item) => item.type === "image").data);
  const filename = animation ? "mushroom-animation.ase" : "mushroom.ase";
  document = (await call("libresprite_save", { documentId, expectedRevision: document.revision, path: filename })).metadata;
  assert.equal(document.modified, false);
  const png = path.join(assets, "mushroom-preview.png");
  await writeFile(png, Buffer.from(image.data, "base64"));
  if (animation) {
    const frames = [];
    for (let frame = 0; frame < 4; frame++) {
      const rendered = await call("libresprite_render", { documentId, frame, scale: 8 });
      const data = rendered.content.find((item) => item.type === "image").data;
      frames.push(data);
      await writeFile(path.join(assets, `frame-${frame}.png`), Buffer.from(data, "base64"));
    }
    const exported = await call("libresprite_export_png", { documentId, expectedRevision: document.revision, frame: 3, scale: 8, path: "mushroom-frame.png" });
    assert.equal(exported.metadata.revision, document.revision);
    assert.deepEqual(await readFile(path.join(assets, "mushroom-frame.png")), Buffer.from(frames[3], "base64"));
    const layout = { columns: 4, scale: 4, padding: 1 };
    const exportedSheet = await call("libresprite_export_sprite_sheet", { documentId, expectedRevision: document.revision, path: "mushroom-sheet.png", ...layout });
    // The bridge publishes only the PNG atomically. This optional demo-owned
    // sidecar is written separately from the returned tool-result manifest.
    await writeFile(path.join(assets, "mushroom-sheet.json"), JSON.stringify(exportedSheet.metadata.sheet, null, 2) + "\n", { flag: "wx" });
    await call("libresprite_set_paused", { paused: true });
    const sheetPreview = await call("libresprite_contact_sheet", { documentId, ...layout });
    assert.deepEqual(exportedSheet.metadata.sheet, sheetPreview.metadata.sheet);
    assert.deepEqual(await readFile(path.join(assets, "mushroom-sheet.png")), Buffer.from(sheetPreview.content.find((item) => item.type === "image").data, "base64"));
    const listed = await call("libresprite_list_assets");
    assert.ok(listed.metadata.entries.some((entry) => entry.path === filename));
    const thumbnail = await call("libresprite_preview_asset", { path: filename, frame: 3, scale: 8 });
    assert.equal(thumbnail.metadata.documentId, undefined);
    assert.equal(thumbnail.content.find((item) => item.type === "image").data, frames[3]);
    const effects = document.layers.find((layer) => layer.name === "Effects").layerId;
    const onions = await call("libresprite_render_onion_skin", { documentId, frame: 1, layerId: effects, position: "front", scale: 8 });
    await writeFile(path.join(assets, "mushroom-onion-skin.png"), Buffer.from(onions.content.find((item) => item.type === "image").data, "base64"));
    assert.equal((await call("libresprite_inspect", { documentId })).metadata.revision, document.revision);
    await call("libresprite_set_paused", { paused: false });
    const reopened = (await call("libresprite_open", { path: filename })).metadata;
    assert.deepEqual(reopened.frames.map((frame) => frame.durationMs), [100, 150, 100, 200]);
    assert.equal(reopened.layers.length, 4);
    for (let frame = 0; frame < 4; frame++) {
      const rendered = await call("libresprite_render", { documentId: reopened.documentId, frame, scale: 8 });
      assert.equal(rendered.content.find((item) => item.type === "image").data, frames[frame]);
    }
  }
  await writeFile(path.join(directory, "result.json"), JSON.stringify({ ...document, png, assetRoot: assets }, null, 2) + "\n");
  await call("libresprite_set_paused", { paused: true });
  console.log(animation
    ? "PASS: real MCP -> grouped animation, undo/redo, exact save/reopen, asset thumbnails, contact/onion previews, atomic PNG/sheet exports."
    : "PASS: real MCP stdio -> native GUI -> pixel batches -> PNG -> undo/redo -> .ase save.");
  console.log(`Preview: ${png}`);
  if (animation) console.log(`Sprite sheet: ${path.join(assets, "mushroom-sheet.png")}`);
  console.log("The demo editor is left open and paused. Close it when finished.");
  if (animation) console.log("Agent editing is paused; use LibreSprite's play button to preview the animation.");
} finally {
  try { await call("libresprite_set_paused", { paused: true }); } catch {}
  await client.close();
}
