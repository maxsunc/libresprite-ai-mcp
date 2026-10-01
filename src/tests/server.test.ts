import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { createServer as netServer } from "node:net";
import path from "node:path";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createServer } from "../server.js";

test("MCP tools enforce schemas, deliver image content, and report native errors", async () => {
  await mkdir(".runtime", { recursive: true, mode: 0o700 });
  const directory = await mkdtemp(path.join(process.cwd(), ".runtime/m-"));
  const socketPath = path.join(directory, "s");
  const methods: string[] = [];
  const requests: Array<{ method: string; params: Record<string, unknown> }> = [];
  const native = netServer((socket) => {
    socket.setEncoding("utf8");
    let input = "";
    socket.on("data", (part) => {
      input += part;
      const newline = input.indexOf("\n");
      if (newline < 0) return;
      const request = JSON.parse(input.slice(0, newline));
      input = input.slice(newline + 1);
      methods.push(request.method);
      requests.push(request);
      let result: Record<string, unknown> = { ok: true };
      if (request.method === "status") result = { protocolVersion: 1, sessionId: "session", paused: true };
      else assert.equal(request.params.sessionId, "session");
      if (request.method === "render") {
        assert.equal(request.params.scale, 1);
        result = { revision: 2, pngBase64: "iVBORw0KGgo=", frame: 0 };
      }
      if (request.method === "set_pixels") socket.write(JSON.stringify({ jsonrpc: "2.0", id: request.id, error: { message: "Paused", data: { code: "PAUSED" } } }) + "\n");
      else socket.write(JSON.stringify({ jsonrpc: "2.0", id: request.id, result }) + "\n");
    });
  });
  await new Promise<void>((resolve) => native.listen(socketPath, resolve));
  const application = createServer({ socketPath, executable: "/not-launched", assetRoot: directory });
  const client = new Client({ name: "test", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  try {
    await application.server.connect(serverTransport);
    await client.connect(clientTransport);
    const tools = (await client.listTools()).tools;
    assert.equal(tools.length, 22);
    assert.equal(tools.find((tool) => tool.name === "libresprite_inspect")?.annotations?.readOnlyHint, true);
    await client.callTool({ name: "libresprite_connect", arguments: {} });
    const rendered = await client.callTool({ name: "libresprite_render", arguments: { documentId: 1, frame: 0 } });
    const content = rendered.content as Array<Record<string, unknown>>;
    assert.equal(content[1]?.type, "image");
    assert.equal(content[1]?.mimeType, "image/png");
    assert.equal(content[1]?.data, "iVBORw0KGgo=");
    assert.equal((content[0]?.text as string).includes("pngBase64"), false);
    const before = methods.length;
    const invalid = await client.callTool({ name: "libresprite_set_pixels", arguments: { documentId: 1, layerId: 1, frame: 0, pixels: [] } });
    assert.equal(invalid.isError, true);
    assert.equal(methods.length, before);
    const paused = await client.callTool({ name: "libresprite_set_pixels", arguments: { documentId: 1, expectedRevision: 1, layerId: 1, frame: 0, pixels: [{ x: 0, y: 0, r: 1, g: 2, b: 3, a: 255 }] } });
    assert.equal(paused.isError, true);
    assert.equal(JSON.parse((paused.content as Array<{ text: string }>)[0]!.text).code, "PAUSED");
    const target = { documentId: 1, expectedRevision: 1 };
    const paint = { ...target, layerId: 1, frame: 0, color: { r: 10, g: 20, b: 30, a: 255 } };
    const valid = [
      ["create_layer", { ...target, name: "Ink" }],
      ["update_layer", { ...target, layerId: 1, visible: false, editable: false, opacity: 0 }],
      ["move_layer", { ...target, layerId: 1, afterLayerId: null }],
      ["remove_layer", { ...target, layerId: 1 }],
      ["add_frame", { ...target, index: 0, copyFrom: 0, durationMs: 65535 }],
      ["remove_frame", { ...target, frame: 0 }],
      ["set_frame_duration", { ...target, frame: 0, durationMs: 75 }],
      ["draw_shape", { ...paint, shape: "rectangle", x1: 1, y1: 2, x2: 5, y2: 6 }],
      ["draw_stroke", { ...paint, points: [{ x: 0, y: 0 }] }],
      ["flood_fill", { ...paint, x: 1, y: 2 }],
    ] as const;
    for (const [method, args] of valid) {
      const result = await client.callTool({ name: `libresprite_${method}`, arguments: args });
      assert.equal(result.isError, undefined, method);
      assert.equal(methods.at(-1), method);
    }
    assert.equal(requests.find((item) => item.method === "create_layer")?.params.type, "image");
    assert.equal(requests.find((item) => item.method === "remove_layer")?.params.recursive, false);
    assert.equal(requests.find((item) => item.method === "draw_shape")?.params.filled, false);
    assert.equal(requests.find((item) => item.method === "flood_fill")?.params.contiguous, true);
    assert.equal(requests.find((item) => item.method === "flood_fill")?.params.tolerance, 0);
    const rejected = [
      ["create_layer", { ...target, name: "", type: "unknown" }],
      ["update_layer", { ...target, layerId: 1, opacity: 256 }],
      ["move_layer", { ...target, layerId: 1 }],
      ["remove_layer", { ...target, layerId: 1, recursive: "true" }],
      ["add_frame", { ...target, index: 256 }],
      ["set_frame_duration", { ...target, frame: 0, durationMs: 65536 }],
      ["draw_shape", { ...paint, shape: "circle", x1: 0, y1: 0, x2: 1, y2: 1 }],
      ["draw_stroke", { ...paint, points: [] }],
      ["flood_fill", { ...paint, x: -1, y: 0 }],
    ] as const;
    for (const [method, args] of rejected) {
      const count = methods.length;
      assert.equal((await client.callTool({ name: `libresprite_${method}`, arguments: args })).isError, true, method);
      assert.equal(methods.length, count, "Invalid tool arguments must not reach the native bridge.");
    }
  } finally {
    application.close();
    await client.close();
    await application.server.close();
    await new Promise<void>((resolve) => native.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  }
});

test("stdio EOF closes the native connection and exits without killing an editor", { timeout: 10_000 }, async () => {
  await mkdir(".runtime", { recursive: true, mode: 0o700 });
  const directory = await mkdtemp(path.join(process.cwd(), ".runtime/e-"));
  const endpoint = path.join(directory, "s");
  let connected!: () => void;
  let disconnected!: () => void;
  const connection = new Promise<void>((resolve) => { connected = resolve; });
  const disconnection = new Promise<void>((resolve) => { disconnected = resolve; });
  const native = netServer((socket) => {
    connected();
    socket.once("close", disconnected);
    socket.setEncoding("utf8");
    socket.on("data", (data) => {
      const request = JSON.parse(data.toString());
      socket.write(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { protocolVersion: 1, sessionId: "s", paused: true } }) + "\n");
    });
  });
  await new Promise<void>((resolve) => native.listen(endpoint, resolve));
  const child = spawn(process.execPath, [path.resolve("dist/index.js")], { env: { ...process.env, LIBRESPRITE_SOCKET: endpoint } });
  let errors = "";
  child.stderr.on("data", (part) => { errors += part; });
  const responses: Array<Record<string, any>> = [];
  const waiting = new Map<number, () => void>();
  let input = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (part) => {
    input += part;
    let end: number;
    while ((end = input.indexOf("\n")) >= 0) {
      const response = JSON.parse(input.slice(0, end));
      input = input.slice(end + 1);
      responses.push(response);
      waiting.get(response.id)?.();
    }
  });
  function send(request: Record<string, unknown>) { child.stdin.write(JSON.stringify(request) + "\n"); }
  function response(id: number) { return new Promise<void>((resolve) => { waiting.set(id, resolve); }); }
  const exit = once(child, "exit");
  try {
    const initialized = response(1);
    send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "eof-test", version: "1.0" } } });
    await initialized;
    send({ jsonrpc: "2.0", method: "notifications/initialized" });
    const tool = response(2);
    send({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "libresprite_connect", arguments: {} } });
    await connection;
    await tool;
    assert.equal(responses.find((item) => item.id === 2)?.result.isError, undefined);
    child.stdin.end();
    await disconnection;
    const [code] = await exit;
    assert.equal(code, 0, errors);
  } finally {
    if (child.exitCode === null) child.kill("SIGTERM");
    await new Promise<void>((resolve) => native.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  }
});
