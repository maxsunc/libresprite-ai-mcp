// End-to-end demonstration through the actual MCP stdio protocol. GPLv2.
// Leaves its own editor open and paused. Never attaches to another window.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
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
const client = new Client({ name: "libresprite-live-demo", version: "0.1.0" });
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
  assert.equal((await client.listTools()).tools.length, 12);
  console.log((await call("libresprite_launch")).metadata);
  const deadline = Date.now() + 15_000;
  while (true) {
    try { await call("libresprite_connect"); break; }
    catch (error) { if (Date.now() > deadline) throw error; await wait(100); }
  }
  await call("libresprite_set_paused", { paused: false });
  let document = (await call("libresprite_create", { width: 32, height: 32, name: "MCP live demo - mushroom" })).metadata;
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
  const beforeUndo = await call("libresprite_render", { documentId, frame: 0, scale: 8 });
  document = (await call("libresprite_undo", { documentId, expectedRevision: document.revision })).metadata;
  await wait(200);
  document = (await call("libresprite_redo", { documentId, expectedRevision: document.revision })).metadata;
  const afterRedo = await call("libresprite_render", { documentId, frame: 0, scale: 8 });
  const image = afterRedo.content.find((item) => item.type === "image");
  assert.equal(image.data, beforeUndo.content.find((item) => item.type === "image").data);
  document = (await call("libresprite_save", { documentId, expectedRevision: document.revision, path: "mushroom.ase" })).metadata;
  assert.equal(document.modified, false);
  const png = path.join(assets, "mushroom-preview.png");
  await writeFile(png, Buffer.from(image.data, "base64"));
  await writeFile(path.join(directory, "result.json"), JSON.stringify({ ...document, png, assetRoot: assets }, null, 2) + "\n");
  await call("libresprite_set_paused", { paused: true });
  console.log(`PASS: real MCP stdio -> native GUI -> pixel batches -> PNG -> undo/redo -> .ase save.`);
  console.log(`Preview: ${png}`);
  console.log("The demo editor is left open and paused. Close it when finished.");
} finally {
  try { await call("libresprite_set_paused", { paused: true }); } catch {}
  await client.close();
}
