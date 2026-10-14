# Cooperative editing — v0.13 branch review

Experimental **source-only** change on `feat/cooperative-editing`. Not merged or
released; approved v0.9/v0.12 packages are unchanged. Review manually before release.

## What changes

- Ordinary drawing, selection/cel dragging, unfinished transforms, playback and
  modal dialogs do **not** automatically pause the bridge or cancel an agent task.
  Native guards still prevent reading unfinished artwork or writing into it.
- MCP briefly waits after a native `BUSY` response **only when** the native guard
  explicitly says `notStarted:true`. It checks readiness every ~100 ms for up to
  2 seconds. It can resend the **same** operation/parameters/revision only after
  readiness returns. It never replaces stale revisions.
  Pre-operation native reader/writer acquisition failures (for example recovery
  holding a document reader) carry the same explicit no-start guarantee. A lock
  exception inside dispatch/transactions does not; it is never auto-retried.
- A long interaction returns a successful MCP tool result with
  `status:"deferred", applied:false`. **Nothing remains queued in the editor.**
  Releasing the gesture alone cannot execute that abandoned call.
- A proven viewport-only pan over the **exact** Standby state may coexist with
  document reads and atomic pixel/region corrections. All target document views
  must be safe. A pan over Drawing/MovingPixels/MovingCel or another suspended
  state is **not** view-only. Their inheritance from Standby is not sufficient.
- Navigation, closing, Undo/Redo, geometry/topology operations and other
  view-disrupting requests retain the stricter no-capture/no-pan guard.
  Create/open additionally defer immediately on `BUSY`, without auto-reissuing:
  they have no expected document/site snapshot to protect a later focus change.
- **AI Pause** remains the deliberate way to reserve exclusive manual control.
  The local button cannot be overridden by remote resume; disconnect still pauses.

This is serialized cooperation, **not simultaneous writers**. Native transactions
run between UI events. Large atomic corrections/guard scans can briefly delay input.

## Tools and result handling

The source server/bridge now have **70 tools**. Existing editors keep their loaded
bridge; rebuild and launch a new editor with the matching server.

`libresprite_interaction_state({documentId?, allowPanning?})` is a lightweight,
read-only query available even during unfinished gestures and while paused.
`allowPanning` defaults to true; false checks the stricter readiness required by
view-disrupting requests. The response contains:

- `ready`, `reason` (`BUSY`, unavailable document, or null), `viewOnlyPanning`;
- `paused`, `pausedByUser`, `activeDocumentId`, `sessionId`;
- active-editor `view` scroll/zoom/canvas origin/pixel step/editor/window bounds
  and `controlBounds` in native logical UI coordinates (not OS screen coordinates).

It does not inspect partial pixels or acquire a writer. Readiness is transient:
every real request must still pass its normal guards. `ready:true` does not mean
unpaused, active target, or valid revision. The geometry is read-only telemetry,
not permission for an agent to synthesize input.

| Result | Agent action |
|---|---|
| Normal existing success | Use that tool's ordinary result; these tools do not all add a `status` field. |
| `status:"prepared", applied:false` | Retain the opaque token; nothing has been edited. |
| `status:"applied", applied:true` | Guarded attempt completed. Use counts; a no-op creates no Undo step. |
| `status:"deferred", applied:false` | User still interacting. Wait or do independent safe work, then inspect/reconsider. No native queued operation. |
| `status:"conflict", applied:false` | Preserve user work. Inspect dependencies and replan. Do not substitute a newer revision or silently switch documents. |
| `PAUSED` / `USER_PAUSED` error | Stop agent edits. Do not automatically resume. Local pause requires the person's Resume button. |
| Timeout/disconnect/invalid response | Outcome may be unknown. Never automatically repeat a mutation; reconnect and inspect. |

Direct strict-revision/navigation operations turn proven pre-execution
`STALE_REVISION`, `INACTIVE_DOCUMENT` and `ACTIVE_DOCUMENT_CHANGED` into non-error
conflict results through the new MCP server.
The native protocol still returns guarded errors for direct callers. An old bridge
without `interaction_state` keeps the previous strict behavior. Unknown errors and
`BUSY` without `notStarted:true` are never automatically retried.

MCP cancellation cancels readiness waiting and unsent/queued requests. Once a
request is sent, the client continues collecting its response rather than claiming
it was rolled back. A cancelled client may discard that result; inspect before
further edits. No general client/model can be guaranteed to continue automatically:
**agents must explicitly understand deferred/conflict results.**

## Immutable prepared corrections

The optional prepare/apply workflow lets a specific correction coexist with
disjoint manual changes instead of abandoning it at any revision change.

```json
{
  "documentId": 123,
  "expectedRevision": 7,
  "operation": {
    "method": "edit_pixels",
    "edits": [{
      "layerId": 456,
      "frame": 0,
      "pixels": [{"x": 4, "y": 5, "r": 230, "g": 60, "b": 70, "a": 255}]
    }],
    "label": "AI: planned pixel correction"
  }
}
```

Send this to `libresprite_prepare_edit`. It validates/dry-runs without modifying
artwork, focus, selection, viewport, native history or files. It returns predicted
counts/bounds and an `editToken`. Then use:

```json
{"documentId":123, "editToken":"<32 lowercase hex characters from prepare>"}
```

with `libresprite_apply_edit`. The operation is held in the native connection and
cannot be altered at apply time. There is deliberately no revision override.

Supported nested operations are `edit_pixels`, `translate_regions` and
`stamp_region` with their existing explicit arguments, optionally `label`; stamp
also supports `expectedSourceHash`. Do not nest document/revision/dryRun fields.
There is no prepared flood-fill, arbitrary command, script or inferred merge.

Under one native writer lock, apply checks:

- exact original destination samples for explicit pixels;
- the full bounding source/destination union for moves/copies, including holes
  and the space between them (conservative, not an inferred minimal footprint);
- the full destination footprint and decoded source digest for stamping,
  including transparent/masked-out samples; source changes are conflicts;
- canvas, color mode, transparent index, sprite version, layer hierarchy/order/
  properties, frame timing, palettes/tags, existing cel identities/frame mappings,
  and target cel opacity/user data;
- existing locked/hidden/shared/linked/background, format, source/path,
  clipping and aggregate memory limits.

Unrelated raw pixel or GUI selection edits may be accepted with `rebased:true`;
changed dependencies return conflict with **no mutation or extra Undo step**.
New destination cels from disjoint painting can coexist. Existing cel deletion/
recreation, frame permutations, and conservative semantic changes conflict even
if a rendered pose looks identical. Cel image bounds may grow/shrink naturally;
the guard compares canvas-coordinate raw samples, not storage cropping.
Selection is intentionally not an input to these explicit corrections and is
preserved. This is a bounded content check, not knowledge of all the agent's
artistic assumptions: if the plan depends on other pixels/context not covered by
these guards, the agent must inspect/reconsider them before applying.

Preparation is bounded to 1,048,576 destination/dependency samples, a 2 MiB
serialized operation+guard ticket, at most 8 live tickets and 8 MiB serialized
total (JSON/container overhead and existing native scratch budgets are separate). Existing 1 MiB
wire-request and correction limits also apply. Tokens expire after 5 minutes,
belong to one document/connection, and are invalidated on disconnect. Native
requests still require the current editor session. Tokens are opaque single-use
capabilities, not document IDs or permission to replay after an uncertain outcome.
An attempted validation/conflict consumes its token. Busy/pause/inactive checks
before validation do not; completed/expired tickets may be reclaimed on preparation.

Successful corrections use one native Undo transaction separate from the user's
edits and preserve live frame/layer/mask/viewport. Native Undo/Redo and all safety
guards remain authoritative. Nothing is auto-saved.

## Testing and profile isolation

See [the branch checklist](testing-v0.13.md). `LIBRESPRITE_USER_DIR` explicitly
selects a separate editor profile (preferences/recovery/user data); if unset,
existing defaults are unchanged. The tests set it to their disposable directory.
This is process environment configuration, not an MCP tool or a personal-profile
migration. Do not point it at personal configuration for tests.
