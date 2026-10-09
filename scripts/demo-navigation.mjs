// Step 1 review through real MCP, in a NEW editor with generated artwork. GPLv2-only.
// Keeps a connection for testing the editor button; Ctrl+C disconnects/pauses,
// but never kills or closes the GUI. No existing artwork/configuration is used.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.join(root, ".runtime", `nav-${Date.now().toString(36)}`);
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
const client = new Client({ name: "libresprite-navigation-review", version: "0.8.0" });
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
async function target(documentId) {
  const result = await request("inspect", { documentId });
  return { documentId, expectedRevision: result.revision };
}

try {
  await client.connect(transport);
  transport.stderr?.pipe(process.stderr);
  assert.ok((await client.listTools()).tools.some((tool) => tool.name === "libresprite_activate_document"));
  const launched = await request("launch");
  const deadline = Date.now() + 15_000;
  let status;
  while (true) {
    try { status = await request("connect"); break; }
    catch (error) { if (Date.now() > deadline) throw error; await wait(100); }
  }
  assert.ok(status.methods.includes("activate_document"));
  await request("set_paused", { paused: false });
  const sprites = [];
  for (const [name, color] of [["Step 1 review A", { r: 60, g: 160, b: 220, a: 255 }], ["Step 1 review B", { r: 235, g: 150, b: 60, a: 255 }]]) {
    let doc = await request("create", { width: 32, height: 32, name });
    const documentId = doc.documentId;
    const layerId = doc.layers[0].layerId;
    doc = await request("draw_shape", { ...await target(documentId), layerId, frame: 0, shape: "rectangle", x1: 8, y1: 8, x2: 23, y2: 23, filled: true, color });
    await request("add_frame", { ...await target(documentId), index: 1, copyFrom: 0, durationMs: 200 });
    await request("update_cel", { ...await target(documentId), layerId, frame: 1, x: 10, y: 8 });
    const path = name.endsWith("A") ? "review-a.ase" : "review-b.ase";
    doc = await request("save", { ...await target(documentId), path });
    sprites.push({ documentId, layerId, path, revision: doc.revision });
  }
  const [a, b] = sprites;
  let active = (await request("list_documents")).activeDocumentId;
  await request("activate_document", { ...await target(a.documentId), expectedActiveDocumentId: active });
  const before = await request("inspect", { documentId: a.documentId });
  const focused = await request("set_active_site", { ...await target(a.documentId), layerId: a.layerId, frame: 0 });
  assert.equal(focused.revision, before.revision);
  const blank = await request("create", { width: 8, height: 8, name: "Safe-close check" });
  await request("close_document", { ...await target(blank.documentId), confirm: true }, "UNSAVED_CHANGES");
  await request("save", { ...await target(blank.documentId), path: "safe-close.ase" });
  await request("close_document", { ...await target(blank.documentId), confirm: true });
  active = (await request("list_documents")).activeDocumentId;
  await request("activate_document", { ...await target(a.documentId), expectedActiveDocumentId: active });
  await request("set_paused", { paused: true });
  const review = { ...launched, bridgeVersion: status.bridgeVersion, sprites, initialActiveDocumentId: a.documentId };
  await writeFile(path.join(directory, "review.json"), JSON.stringify(review, null, 2) + "\n");
  console.log(JSON.stringify(review, null, 2));
  console.log("READY: A and B are saved generated test sprites. Agent is connected and paused. Click Resume, then Pause in the bottom-right status bar. This script only monitors status and verifies a user pause cannot be remotely overridden; it makes NO further sprite/navigation edits. Ctrl+C disconnects and leaves the editor open.");
  let lastState;
  while (!stopping) {
    status = await request("connect");
    const state = JSON.stringify({ paused: status.paused, pausedByUser: status.pausedByUser, controlText: status.controlText });
    if (state !== lastState) {
      console.log(state);
      if (status.pausedByUser) {
        await request("set_paused", { paused: false }, "USER_PAUSED");
        console.log("PASS: remote resume refused (USER_PAUSED); only the editor's Resume button releases this pause.");
      }
      lastState = state;
    }
    await wait(500);
  }
} finally {
  await client.close();
}
