// GPL-2.0-only. Only wait/reissue when native guards prove execution never began.
import { setTimeout as delay } from "node:timers/promises";
import { BridgeClient, BridgeError, type BridgeResult } from "./bridge-client.js";

const reads = new Set(["list_documents", "list_assets", "preview_asset", "inspect", "render", "contact_sheet",
  "render_onion_skin", "render_selection", "render_frame_diff", "render_layer", "analyze_animation", "read_pixels", "extract_mask", "prepare_edit"]);
const panSafe = new Set([...reads, "edit_pixels", "translate_regions", "stamp_region", "apply_edit"]);
// These focus-changing calls have no expected document/site snapshot. A busy
// rejection must not become an automatic focus jump after the user's gesture.
const unguardedNavigation = new Set(["create", "open"]);

export async function cooperativeRequest(bridge: BridgeClient, method: string, params: BridgeResult,
  signal?: AbortSignal, waitMs = 2000): Promise<BridgeResult> {
  const enabled = bridge.supports("interaction_state") && !["status", "set_paused", "interaction_state"].includes(method);
  const deadline = Date.now() + waitMs;
  while (true) {
    if (signal?.aborted) throw new BridgeError("ABORTED", "Cooperative wait cancelled; no further request was sent.", { notStarted: true });
    try { return await bridge.request(method, params, signal); }
    catch (error) {
      if (!enabled || !(error instanceof BridgeError) || error.data.notStarted !== true) throw error;
      if (["STALE_REVISION", "INACTIVE_DOCUMENT", "ACTIVE_DOCUMENT_CHANGED"].includes(error.code)) return {
        status: "conflict", applied: false, reason: error.code, method,
        nextAction: "Inspect and reconsider the operation, preserving manual edits. Never just substitute a newer revision or silently switch documents.",
      };
      if (error.code !== "BUSY") throw error;
      if (unguardedNavigation.has(method)) return { status: "deferred", applied: false, reason: "BUSY", method,
        nextAction: "This focus-changing operation was not queued. Wait and inspect the active document before explicitly requesting it again." };
      while (true) {
        if (Date.now() >= deadline) return { status: "deferred", applied: false, reason: "BUSY", method,
          nextAction: "The user is still interacting. No operation is queued in the editor. Wait, inspect and reconsider before another call; continue other safe work if useful." };
        try { await delay(Math.min(100, Math.max(0, deadline - Date.now())), undefined, { signal }); }
        catch { throw new BridgeError("ABORTED", "Cooperative wait cancelled; no edit was applied.", { notStarted: true }); }
        const state = await bridge.request("interaction_state", {
          ...(params.documentId === undefined ? {} : { documentId: params.documentId }), allowPanning: panSafe.has(method),
        }, signal);
        if (state.paused && !reads.has(method)) throw new BridgeError(state.pausedByUser ? "USER_PAUSED" : "PAUSED",
          "Agent edits are paused. Do not resume automatically; a local pause requires the person's Resume button.", { notStarted: true });
        if (state.ready === true) break;
        if (state.reason && state.reason !== "BUSY") return { status: "conflict", applied: false, reason: state.reason, method,
          nextAction: "The target is no longer available. Inspect the session/documents and reconsider; no edit was applied." };
      }
      // Exactly the same parameters/revision. A gesture may have changed the
      // document; the normal native revision guard or prepared token checks win.
    }
  }
}
