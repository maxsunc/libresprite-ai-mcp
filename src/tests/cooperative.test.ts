// GPL-2.0-only. No GUI or user socket; exercise scheduling without mutation retries.
import assert from "node:assert/strict";
import { test } from "node:test";
import { BridgeClient, BridgeError, type BridgeResult } from "../bridge-client.js";
import { cooperativeRequest } from "../cooperative.js";

class Fixture extends BridgeClient {
  calls: Array<{ method: string; params: BridgeResult }> = [];
  constructor(private handler: (method: string, params: BridgeResult) => Promise<BridgeResult> | BridgeResult, private enabled = true) { super("not-connected"); }
  override supports(): boolean { return this.enabled; }
  override async request(method: string, params: BridgeResult = {}, signal?: AbortSignal): Promise<BridgeResult> {
    if (signal?.aborted) throw new BridgeError("ABORTED", "cancelled");
    this.calls.push({ method, params }); return this.handler(method, params);
  }
}
const busy = () => new BridgeError("BUSY", "drawing", { notStarted: true });

test("cooperative waiting sends unchanged parameters only after proven pre-execution BUSY", async () => {
  let edits = 0;
  const bridge = new Fixture((method) => {
    if (method === "interaction_state") return { ready: true, paused: false };
    if (++edits === 1) throw busy();
    return { status: "applied" };
  });
  const params = { documentId: 1, expectedRevision: 7 };
  assert.equal((await cooperativeRequest(bridge, "edit_pixels", params)).status, "applied");
  assert.deepEqual(bridge.calls.map(c => c.method), ["edit_pixels", "interaction_state", "edit_pixels"]);
  assert.deepEqual(bridge.calls.filter(c => c.method === "edit_pixels").map(c => c.params), [params, params]);
  assert.equal(bridge.calls[1]?.params.allowPanning, true);
});

test("stale revision after a manual gesture is a non-applied conflict, never revision substitution", async () => {
  const bridge = new Fixture(() => { throw new BridgeError("STALE_REVISION", "changed", { notStarted: true }); });
  const result = await cooperativeRequest(bridge, "set_pixels", { expectedRevision: 1 });
  assert.equal(result.status, "conflict"); assert.equal(result.applied, false); assert.equal(bridge.calls.length, 1);
});

test("long gestures defer without any parked mutation; a later release cannot execute it", async () => {
  const bridge = new Fixture(method => { if (method === "interaction_state") return { ready: false, reason: "BUSY" }; throw busy(); });
  const result = await cooperativeRequest(bridge, "apply_edit", { documentId: 1, editToken: "a".repeat(32) }, undefined, 25);
  assert.equal(result.status, "deferred"); assert.equal(result.applied, false);
  assert.equal(bridge.calls.filter(c => c.method === "apply_edit").length, 1);
});

test("button pause during waiting is authoritative and never remotely resumed", async () => {
  const bridge = new Fixture(method => { if (method === "interaction_state") return { ready: false, paused: true, pausedByUser: true }; throw busy(); });
  await assert.rejects(cooperativeRequest(bridge, "apply_edit", {}), e => e instanceof BridgeError && e.code === "USER_PAUSED");
  assert.deepEqual(bridge.calls.map(c => c.method), ["apply_edit", "interaction_state"]);
});

test("cancelled waits send no later mutation, and closing/disconnecting is not retried", async () => {
  const controller = new AbortController();
  const bridge = new Fixture(method => { if (method === "interaction_state") return { ready: true }; controller.abort(); throw busy(); });
  await assert.rejects(cooperativeRequest(bridge, "apply_edit", {}, controller.signal), e => e instanceof BridgeError && e.code === "ABORTED");
  assert.equal(bridge.calls.length, 1);
  for (const code of ["OUTCOME_UNKNOWN", "INVALID_RESPONSE", "DISCONNECTED", "BUSY"]) {
    const fixture = new Fixture(() => { throw new BridgeError(code, "uncertain"); });
    await assert.rejects(cooperativeRequest(fixture, "apply_edit", {}), e => e instanceof BridgeError && e.code === code);
    assert.equal(fixture.calls.length, 1);
  }
});

test("older editors keep strict behavior and destructive view operations do not allow panning", async () => {
  const older = new Fixture(() => { throw busy(); }, false);
  await assert.rejects(cooperativeRequest(older, "set_pixels", {}), e => e instanceof BridgeError && e.code === "BUSY");
  let attempts = 0;
  const bridge = new Fixture(method => { if (method === "interaction_state") return { ready: true }; if (!attempts++) throw busy(); return {}; });
  await cooperativeRequest(bridge, "close_document", { documentId: 1 });
  assert.equal(bridge.calls[1]?.params.allowPanning, false);
});

test("create/open do not automatically jump focus after a user gesture", async () => {
  for (const method of ["create", "open"]) {
    const bridge = new Fixture(() => { throw busy(); });
    const result = await cooperativeRequest(bridge, method, { path: "test.ase" });
    assert.equal(result.status, "deferred"); assert.equal(result.applied, false);
    assert.deepEqual(bridge.calls.map(c => c.method), [method]);
  }
});

test("manual document navigation conflicts instead of silently navigating back", async () => {
  const bridge = new Fixture(() => { throw new BridgeError("ACTIVE_DOCUMENT_CHANGED", "changed", { notStarted: true }); });
  const result = await cooperativeRequest(bridge, "activate_document", { documentId: 2, expectedActiveDocumentId: 1 });
  assert.equal(result.status, "conflict"); assert.equal(result.reason, "ACTIVE_DOCUMENT_CHANGED");
  assert.equal(bridge.calls.length, 1);
});
