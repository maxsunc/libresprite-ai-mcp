// GPL-2.0-only. Successful real-MCP workflows for every editing/inspection tool.
import assert from "node:assert/strict";
import { writeFile, readFile } from "node:fs/promises";
import path from "node:path";
import { deflateSync } from "node:zlib";

function linkedSprite() {
  const chunk = (kind, payload) => {
    const header = Buffer.alloc(6); header.writeUInt32LE(payload.length + 6); header.writeUInt16LE(kind, 4);
    return Buffer.concat([header, payload]);
  };
  const layer = Buffer.alloc(18 + 6);
  layer.writeUInt16LE(3); layer[12] = 255; layer.writeUInt16LE(6, 16); layer.write("Linked", 18);
  const frames = [0, 1].map((index) => {
    const cel = Buffer.alloc(16); cel.writeInt16LE(1, 2); cel.writeInt16LE(1, 4); cel[6] = 255;
    cel.writeUInt16LE(index === 0 ? 2 : 1, 7);
    const image = Buffer.from([1, 0, 1, 0]);
    const payload = index === 0 ? Buffer.concat([cel, image, deflateSync(Buffer.from([230, 60, 70, 255]))]) : Buffer.concat([cel, Buffer.alloc(2)]);
    const chunks = index === 0 ? [chunk(0x2004, layer), chunk(0x2005, payload)] : [chunk(0x2005, payload)];
    const data = Buffer.concat(chunks), header = Buffer.alloc(16);
    header.writeUInt32LE(16 + data.length); header.writeUInt16LE(0xf1fa, 4); header.writeUInt16LE(chunks.length, 6); header.writeUInt16LE(100, 8);
    return Buffer.concat([header, data]);
  });
  const header = Buffer.alloc(128);
  header.writeUInt32LE(128 + frames.reduce((size, frame) => size + frame.length, 0)); header.writeUInt16LE(0xa5e0, 4);
  header.writeUInt16LE(2, 6); header.writeUInt16LE(16, 8); header.writeUInt16LE(16, 10); header.writeUInt16LE(32, 12);
  header.writeUInt32LE(1, 14); header.writeUInt16LE(100, 18); header[34] = header[35] = 1;
  return Buffer.concat([header, ...frames]);
}

export async function exerciseAllTools(call, assets, artifacts) {
  let document = await call("create", { width: 32, height: 32, name: "All Windows MCP tools" });
  let documentId = document.documentId, layerId = document.layers[0].layerId;
  const originalId = documentId;
  const current = () => call("inspect", { documentId });
  const edit = async (method, args = {}) => {
    const before = await current();
    const result = await call(method, { documentId, expectedRevision: before.revision, ...args });
    assert.ok(!["conflict", "deferred"].includes(result.status), `${method}: ${JSON.stringify(result)}`);
    return result;
  };
  const red = { r: 230, g: 60, b: 70, a: 255 }, blue = { r: 50, g: 80, b: 220, a: 255 };
  const cel = () => ({ layerId, frame: 0 });
  await edit("set_pixels", { ...cel(), pixels: [{ x: 1, y: 1, ...red }, { x: 2, y: 1, ...blue }] });
  const pixels = await call("read_pixels", { documentId, ...cel(), x: 1, y: 1, width: 2, height: 1, encoding: "values" });
  assert.deepEqual(pixels.rows, [[0xff463ce6, 0xffdc5032]]);
  const mask = await call("extract_mask", { documentId, ...cel(), x: 0, y: 0, width: 4, height: 4 });
  assert.equal(mask.selectedPixels, 2);
  await edit("edit_pixels", { edits: [{ ...cel(), pixels: [{ x: 3, y: 1, ...red }] }] });
  const prepared = await edit("prepare_edit", { operation: { method: "edit_pixels", edits: [{ ...cel(), pixels: [{ x: 4, y: 1, ...blue }] }] } });
  assert.equal(prepared.status, "prepared");
  assert.equal((await call("apply_edit", { documentId, editToken: prepared.editToken })).status, "applied");
  await edit("draw_shape", { ...cel(), shape: "rectangle", x1: 6, y1: 6, x2: 12, y2: 12, color: blue });
  await edit("draw_stroke", { ...cel(), points: [{ x: 5, y: 15 }, { x: 15, y: 19 }], color: red });
  await edit("draw_brush_stroke", { ...cel(), points: [{ x: 20, y: 5 }, { x: 24, y: 8 }], brush: { width: 3, height: 3, bits: "010111010" }, color: blue });
  await edit("flood_fill", { ...cel(), x: 8, y: 8, color: red });
  await edit("set_selection", { x1: 6, y1: 6, x2: 8, y2: 8 });
  await edit("fill_selection", { ...cel(), color: blue });
  await edit("translate_selection", { ...cel(), dx: 1, dy: 1, copy: true });
  await edit("set_bitmap_selection", { x: 6, y: 6, width: 2, height: 3, bits: "100110" });
  await edit("transform_selection", { layerId, frames: [0], operation: "rotate_cw" });
  await edit("set_polygon_selection", { vertices: [{ x: 1, y: 1 }, { x: 5, y: 1 }, { x: 1, y: 5 }] });
  await call("render_selection", { documentId, frame: 0, mode: "mask" });
  await edit("modify_selection", { action: "none" });
  await edit("translate_regions", { edits: [{ ...cel(), mask: { x: 1, y: 1, width: 2, height: 1, bits: "11" }, dx: 0, dy: 2, copy: true }] });
  await edit("stamp_region", { source: { ...cel(), x: 1, y: 1, width: 2, height: 1 }, mode: "replace", edits: [{ ...cel(), x: 20, y: 20 }] });
  await edit("update_cel", { ...cel(), opacity: 230 });
  await edit("transform_cel", { ...cel(), operation: "flip_horizontal" });

  const other = (await edit("create_layer", { name: "Copy" })).createdLayerId;
  await edit("copy_cel", { layerId: other, frame: 0, sourceLayerId: layerId, sourceFrame: 0 });
  await edit("update_layer", { layerId: other, name: "Multiplied copy", opacity: 180, blendMode: "multiply" });
  await edit("move_layer", { layerId: other, afterLayerId: null });
  const group = (await edit("create_layer", { name: "Group", type: "group" })).createdLayerId;
  await edit("reparent_layer", { layerId: other, parentId: group });
  const copy = (await edit("duplicate_layer", { layerId: group, name: "Independent subtree" })).createdLayerId;
  await edit("remove_layer", { layerId: copy, recursive: true });
  await edit("reparent_layer", { layerId: other, parentId: null });
  await edit("remove_layer", { layerId: group });
  await edit("add_frame", { index: 1, copyFrom: 0 });
  await edit("set_frame_duration", { frame: 1, durationMs: 140 });
  await edit("set_frame_durations", { durations: [{ frame: 0, durationMs: 120 }, { frame: 1, durationMs: 160 }] });
  assert.equal((await edit("duplicate_frames", { frames: [1, 0], index: 2 })).frameCount, 4);
  await edit("reorder_frames", { order: [3, 2, 1, 0] });
  assert.equal((await edit("remove_frame", { frame: 3 })).frameCount, 3);
  await edit("edit_cels", { edits: [{ layerId, frame: 0, opacity: 190 }, { layerId, frame: 1, operation: "rotate_180" }] });
  await edit("set_palette", { frame: 1, entries: [{ index: 1, color: red }] });
  await edit("remove_palette", { frame: 1 });
  const tag = (await edit("create_tag", { name: "Loop", from: 0, to: 2 })).createdTagId;
  await edit("update_tag", { tagId: tag, name: "Pingpong", direction: "pingpong" });
  await call("analyze_animation", { documentId, tagId: tag });
  await call("render_layer", { documentId, layerId: other, frame: 0 });
  await call("render_frame_diff", { documentId, fromFrame: 0, toFrame: 1 });
  await call("contact_sheet", { documentId, frames: [0, 1, 2], columns: 3 });
  await call("render_onion_skin", { documentId, frame: 1, position: "front" });
  await edit("remove_tag", { tagId: tag });
  assert.equal((await edit("resize_canvas", { width: 34, height: 34, offsetX: 1, offsetY: 1 })).width, 34);
  assert.equal((await edit("crop_canvas", { x: 1, y: 1, width: 32, height: 32, discardOutside: true })).width, 32);
  await edit("undo"); assert.equal((await current()).width, 34);
  await edit("redo"); assert.equal((await current()).width, 32);
  await edit("set_active_site", { layerId, frame: 1 });
  assert.equal((await current()).activeFrame, 1);
  await call("interaction_state", { documentId });
  await edit("export_png", { frame: 0, path: "all-tools.png", scale: 8 });
  await edit("export_sprite_sheet", { path: "all-tools-sheet.png", frames: [0, 1, 2], columns: 3, scale: 4 });
  for (const format of ["gif", "apng"]) await edit("export_animation", { path: `all-tools.${format}`, format, scale: 4 });
  await edit("save", { path: "all-tools.ase" });
  await call("list_assets");
  await call("preview_asset", { path: "all-tools.ase", frame: 1, scale: 4 });

  document = await call("create", { width: 16, height: 16, colorMode: "indexed", name: "Indexed tools" });
  documentId = document.documentId; layerId = document.layers[0].layerId;
  await edit("set_palette", { frame: 0, entries: [{ index: 1, color: red }, { index: 2, color: blue }] });
  await edit("set_indexed_pixels", { ...cel(), pixels: [{ x: 1, y: 1, index: 1 }, { x: 2, y: 1, index: 2 }] });
  assert.deepEqual((await call("read_pixels", { documentId, ...cel(), x: 1, y: 1, width: 2, height: 1, encoding: "values" })).rows, [[1, 2]]);
  await edit("draw_brush_stroke", { ...cel(), points: [{ x: 8, y: 8 }], brush: { width: 3, height: 3, bits: "010111010" }, index: 2 });
  await edit("save", { path: "all-tools-indexed.ase" });
  await edit("close_document", { confirm: true });

  await writeFile(path.join(assets, "linked-fixture.ase"), linkedSprite());
  document = await call("open", { path: "linked-fixture.ase" });
  documentId = document.documentId; layerId = document.layers[0].layerId;
  assert.equal(document.layers[0].cels[0].celDataId, document.layers[0].cels[1].celDataId);
  await edit("unlink_cel", { layerId, frame: 1 });
  const unlinked = await current();
  assert.notEqual(unlinked.layers[0].cels[0].celDataId, unlinked.layers[0].cels[1].celDataId);
  await edit("save", { path: "all-tools-unlinked.ase" });
  await edit("close_document", { confirm: true });
  documentId = originalId;
  const active = (await call("list_documents")).activeDocumentId;
  await edit("activate_document", { expectedActiveDocumentId: active });
  assert.equal((await call("list_documents")).activeDocumentId, originalId);
  await call("set_paused", { paused: true });
  await call("render", { documentId, frame: 0, scale: 8 });
  await call("set_paused", { paused: false });
  for (const name of ["all-tools.ase", "all-tools.png", "all-tools-sheet.png", "all-tools.gif", "all-tools.apng", "all-tools-indexed.ase", "all-tools-unlinked.ase"]) {
    const bytes = await readFile(path.join(assets, name));
    assert.ok(bytes.length > 16, name);
    await writeFile(path.join(artifacts, name), bytes);
  }
  console.log("PASS: real MCP layer/group/cel/frame/selection/canvas/palette/tag workflows, raw pixels/masks/corrections, inspection, all export formats, indexed painting, actual linked-cel unlink, navigation and saved-only closing.");
}
