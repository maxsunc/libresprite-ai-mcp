import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { createServer, type Socket } from "node:net";
import path from "node:path";
import { test } from "node:test";
import { BridgeClient, BridgeError } from "../bridge-client.js";

async function mock(handler: (request: Record<string, any>, socket: Socket) => void) {
  // Keep Unix socket paths short even on macOS's long TMPDIR.
  await mkdir(path.join(process.cwd(), ".runtime"), { recursive: true, mode: 0o700 });
  const directory = await mkdtemp(path.join(process.cwd(), ".runtime/t-"));
  const endpoint = path.join(directory, "s");
  const peers = new Set<Socket>();
  const server = createServer((socket) => {
    peers.add(socket);
    socket.once("close", () => peers.delete(socket));
    socket.setEncoding("utf8");
    let input = "";
    socket.on("data", (part) => {
      input += part;
      let newline: number;
      while ((newline = input.indexOf("\n")) >= 0) {
        const line = input.slice(0, newline);
        input = input.slice(newline + 1);
        handler(JSON.parse(line), socket);
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(endpoint, resolve));
  return { endpoint, async close() {
    for (const peer of peers) peer.destroy();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  } };
}
function reply(socket: Socket, request: Record<string, any>, result: Record<string, unknown>) {
  socket.write(JSON.stringify({ jsonrpc: "2.0", id: request.id, result }) + "\n");
}

test("serializes requests, injects handshake session, and handles fragmented responses", async () => {
  const calls: string[] = [];
  const fixture = await mock((request, socket) => {
    calls.push(request.method);
    if (request.method === "status") {
      const response = JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { protocolVersion: 1, sessionId: "session", paused: true } }) + "\n";
      socket.write(response.slice(0, 15));
      setTimeout(() => socket.write(response.slice(15)), 5);
    } else {
      assert.equal(request.params.sessionId, "session");
      reply(socket, request, { method: request.method });
    }
  });
  const client = new BridgeClient(fixture.endpoint);
  try {
    const results = await Promise.all([client.request("status"), client.request("inspect"), client.request("render")]);
    assert.deepEqual(calls, ["status", "inspect", "render"]);
    assert.equal(results[1]?.method, "inspect");
  } finally { client.close(); await fixture.close(); }
});

test("native errors retain their code and do not break the queue", async () => {
  const fixture = await mock((request, socket) => {
    if (request.method === "status") reply(socket, request, { protocolVersion: 1, sessionId: "s" });
    else if (request.method === "edit") socket.write(JSON.stringify({ jsonrpc: "2.0", id: request.id, error: { message: "Changed", data: { code: "STALE_REVISION" } } }) + "\n");
    else reply(socket, request, { ok: true });
  });
  const client = new BridgeClient(fixture.endpoint);
  try {
    await client.request("status");
    await assert.rejects(client.request("edit"), (error) => error instanceof BridgeError && error.code === "STALE_REVISION");
    assert.equal((await client.request("inspect")).ok, true);
  } finally { client.close(); await fixture.close(); }
});

test("timeout does not retry edits and clears the session token", async () => {
  let edits = 0;
  const fixture = await mock((request, socket) => {
    if (request.method === "status") reply(socket, request, { protocolVersion: 1, sessionId: "s" });
    else edits++;
  });
  const client = new BridgeClient(fixture.endpoint, 100);
  try {
    await client.request("status");
    await assert.rejects(client.request("set_pixels"), (error) => error instanceof BridgeError && error.code === "OUTCOME_UNKNOWN");
    assert.equal(edits, 1);
    assert.equal(client.sessionId, undefined);
    await assert.rejects(client.request("set_pixels"), (error) => error instanceof BridgeError && error.code === "NOT_CONNECTED");
    assert.equal(edits, 1);
    assert.equal((await client.request("status")).sessionId, "s");
  } finally { client.close(); await fixture.close(); }
});

test("wrong response ID fails the request instead of accepting another result", async () => {
  const fixture = await mock((_request, socket) => socket.write(JSON.stringify({ jsonrpc: "2.0", id: "wrong", result: { ok: true } }) + "\n"));
  const client = new BridgeClient(fixture.endpoint);
  try {
    await assert.rejects(client.request("status"), (error) => error instanceof BridgeError && error.code === "INVALID_RESPONSE");
  } finally { client.close(); await fixture.close(); }
});

test("unsupported protocol never leaves an active session", async () => {
  const fixture = await mock((request, socket) => reply(socket, request, { protocolVersion: 999, sessionId: "s" }));
  const client = new BridgeClient(fixture.endpoint);
  try {
    await assert.rejects(client.request("status"), (error) => error instanceof BridgeError && error.code === "PROTOCOL_MISMATCH");
    assert.equal(client.sessionId, undefined);
  } finally { client.close(); await fixture.close(); }
});

test("closing with queued work rejects requests without opening another connection", async () => {
  let requests = 0;
  let received!: () => void;
  const first = new Promise<void>((resolve) => { received = resolve; });
  const fixture = await mock(() => { requests++; received(); });
  const client = new BridgeClient(fixture.endpoint);
  try {
    const pending = Promise.allSettled([client.request("status"), client.request("status")]);
    await first;
    client.close();
    const results = await pending;
    assert.equal(results[0]?.status, "rejected");
    assert.equal(results[1]?.status, "rejected");
    assert.equal(requests, 1);
    assert.equal(client.sessionId, undefined);
  } finally { client.close(); await fixture.close(); }
});

test("reported capabilities refuse unsupported methods before sending an edit", async () => {
  const methods: string[] = [];
  const fixture = await mock((request, socket) => {
    methods.push(request.method);
    reply(socket, request, { protocolVersion: 1, sessionId: "s", methods: ["status", "inspect"] });
  });
  const client = new BridgeClient(fixture.endpoint);
  try {
    await client.request("status");
    await assert.rejects(client.request("add_frame"), (error) => error instanceof BridgeError && error.code === "UNSUPPORTED_METHOD");
    assert.deepEqual(methods, ["status"]);
    await client.request("inspect");
    assert.deepEqual(methods, ["status", "inspect"]);
  } finally { client.close(); await fixture.close(); }
});
