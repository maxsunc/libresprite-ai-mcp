# Live editor and MCP server

This milestone provides a **local, visible, undoable editing slice**, not the
complete artist workflow yet. The editor is a custom build of the pinned
LibreSprite source; an installed stock LibreSprite does not have this bridge.

## Setup

Build the editor using [the native build guide](building.md), then build the MCP
server with Node.js 20 or newer:

```sh
npm ci
npm run build
```

The server speaks MCP over standard input/output:

```sh
node dist/index.js
```

Usually your MCP client starts this command; running it in a terminal alone does
not launch the editor. A generic stdio MCP client configuration looks like:

```json
{
  "mcpServers": {
    "libresprite": {
      "command": "node",
      "args": ["/Users/maxsuncanada/github/libresprite-ai-mcp/dist/index.js"]
    }
  }
}
```

The config shape and location depend on your MCP client. Use absolute paths so
its working directory does not matter. Tool results include real PNG image
content; your AI client/model must support MCP image results to see them.

### Environment settings

| Variable | Default |
| --- | --- |
| `LIBRESPRITE_EXECUTABLE` | `build/libresprite/bin/libresprite` in this repo |
| `LIBRESPRITE_SOCKET` | `.runtime/bridge.sock` in this repo |
| `LIBRESPRITE_ASSET_ROOT` | `assets/` in this repo |

The launcher creates the asset directory if absent. Native file tools only
accept paths **relative to that root**. Asset contents, socket files, editor
logs, and build outputs are ignored by Git. Copy finished assets elsewhere or
explicitly track them if you want them in version control.

Unix sockets have a short path limit (about 100 bytes on macOS). For a long
checkout path, set `LIBRESPRITE_SOCKET` to a shorter path in a directory you own
with permissions `0700`. The socket itself is `0600`. Do not place it directly
in a shared temporary directory.

## First session

1. Call **`libresprite_launch`** to open a new visible development editor. It
   leaves ordinary LibreSprite windows alone. Wait for its window to appear.
2. Call **`libresprite_connect`** to obtain its session/paused state and root.
   Retrying this read-only connection call during startup is safe.
3. Call **`libresprite_set_paused`** with `paused: false` to explicitly allow edits.
4. Call **`libresprite_create`** or **`libresprite_open`**. Record the returned
   `documentId`, `revision`, and image-layer `layerId`.
5. Call **`libresprite_set_pixels`** using those IDs, a zero-based frame index,
   and `expectedRevision`. The whole batch becomes one native undo step.
6. Call **`libresprite_render`** to inspect the actual composited image, optionally
   enlarged with nearest-neighbor scaling. Use the newly returned revision for
   the next edit. Do not infer success from the visible window alone.
7. Call **`libresprite_save`** with a relative `.ase` or `.aseprite` path. Existing
   files are refused unless `overwrite: true` is explicitly supplied.

Example pixel-batch arguments (replace the IDs/revision with current results):

```json
{
  "documentId": 3,
  "layerId": 5,
  "frame": 0,
  "expectedRevision": 1,
  "label": "Draw red corner",
  "pixels": [
    { "x": 0, "y": 0, "r": 220, "g": 50, "b": 60, "a": 255 },
    { "x": 1, "y": 0, "r": 220, "g": 50, "b": 60, "a": 255 }
  ]
}
```

### Tools

| Tool | Purpose |
| --- | --- |
| `libresprite_launch` | Launch one new GUI process, initially paused |
| `libresprite_connect` | Connect/reconnect and inspect bridge status |
| `libresprite_set_paused` | Pause/resume agent mutations |
| `libresprite_list_documents` | List IDs and identify the active document |
| `libresprite_inspect` | Layers/cels, frames/durations, palettes, tags, revision |
| `libresprite_render` | Composite a frame to PNG image content |
| `libresprite_create` | New single-frame transparent RGBA sprite |
| `libresprite_open` | Open PNG or a native sprite inside the root |
| `libresprite_set_pixels` | Atomic replacement-color pixel batch |
| `libresprite_create_layer` | New image layer or group, with explicit parent/order |
| `libresprite_update_layer` | Name, visibility, editable/lock state, image opacity |
| `libresprite_move_layer` | Restack within the same group |
| `libresprite_remove_layer` | Delete a layer or explicitly authorized group subtree |
| `libresprite_add_frame` | Insert a blank frame or independent copy |
| `libresprite_remove_frame` | Delete a frame, keeping at least one |
| `libresprite_set_frame_duration` | Frame timing in milliseconds |
| `libresprite_draw_shape` | Native line, rectangle, or ellipse |
| `libresprite_draw_stroke` | Connected one-pixel polyline |
| `libresprite_flood_fill` | Contiguous fill or all matching colors in a target cel |
| `libresprite_undo` / `libresprite_redo` | One native undo transaction |
| `libresprite_save` | Atomic native-file save inside the root |

There are **22 tools** in server/bridge version **0.2.0**. Rebuild the editor
and start a **new development window** when upgrading: already-running windows
keep their old native bridge. `libresprite_connect` reports `bridgeVersion`
and supported native `methods` in new builds. Older bridge builds may not
provide those fields; a missing new method requires rebuilding/relaunching,
not blindly retrying it.

## Layers, drawing, and animation

Every mutating tool below requires the active `documentId`, `expectedRevision`,
and a resumed bridge. Layer/frame operations use native undo transactions just
like pixel edits. Inspection now also reports `activeLayerId` and `activeFrame`;
changing UI selection alone does not change the document revision.

### Layers

- `create_layer` accepts `type: "image"` (default) or `"group"`, a `name`, and
  optional `parentId`. Omitted/null parent means the root. It returns
  `createdLayerId` so agents do not need to identify a new layer by name.
- Layer order is **bottom to top**, recursively in inspection output.
  Omit `afterLayerId` when creating to append on top; use an explicit null to
  insert at the bottom. Moving requires a sibling ID or null and never reparents
  a layer. Insertion below a background layer is refused.
- `update_layer` accepts any combination of `name`, `visible`, `editable`, and
  image `opacity` (0–255). The whole update is one undo step. A locked layer can
  be explicitly unlocked, but **only in a separate request** before other
  property edits. Locked ancestors cannot be bypassed. Group opacity and blend
  mode changes are not exposed yet.
- Creating layers/frames honors LibreSprite's existing auto-show-timeline
  preference. Group rows show empty cells; children have their own editable rows.
  Group expand/collapse controls are not added in this milestone.
- `remove_layer` deletes cels on **all frames**. A nonempty group requires
  `recursive: true`. Locked/background descendants and deletion of the last
  image layer are refused. Undo restores group children and their data.

### Drawing

- `draw_shape`: `shape` is `line`, `rectangle`, or `ellipse`; `x1,y1,x2,y2` are
  **inclusive canvas endpoints**. Rectangles/ellipses can use reversed corners.
  `filled` defaults false and must remain false for a line. Outlines are one
  pixel wide; rasterization uses the editor's native primitives.
- `draw_stroke`: connect 1–1,024 `{x,y}` points with native one-pixel lines as a
  single atomic undo step. A one-point stroke draws one pixel. Brush width,
  pressure, smoothing, and selection-aware brush behavior are not added yet.
- `flood_fill`: use seed `x,y`, `tolerance` (0–255, default 0), and `contiguous`
  (default true). It samples **only the target cel**, with transparent pixels
  filling the rest of its canvas, **not the visible multi-layer composite**.
  Non-contiguous mode replaces all matching pixels in that cel. Native color
  matching compares channels and treats fully transparent colors as equivalent.
- All use explicit `layerId`, zero-based `frame`, and a `color` object containing
  `r,g,b,a`. Colors replace pixels rather than alpha-blending; alpha 0 erases.
  Existing pixels outside the shape/region are preserved, including cropped cels.
  Selection masks are deliberately ignored. Drawing requires an editable,
  transparent RGBA image layer and an unlinked cel. Geometry/fill/stroke requests
  that do not change any stored pixels do not add undo history.

For example, draw an outlined rectangle, then fill its interior:

```json
{
  "documentId": 3,
  "expectedRevision": 4,
  "layerId": 5,
  "frame": 0,
  "shape": "rectangle",
  "x1": 2, "y1": 2, "x2": 13, "y2": 13,
  "color": { "r": 62, "g": 38, "b": 68, "a": 255 },
  "filled": false
}
```

Call `libresprite_draw_shape`, then use its returned revision in a
`libresprite_flood_fill` call with seed `{x: 5, y: 5}` and your interior color.
Render afterwards to inspect the result.

### Frames

- `add_frame`: `index` is the insertion position, from 0 through the existing
  frame count (maximum total is 256). Omit `copyFrom` for a blank frame; supply
  a **pre-insertion** frame index for an independent copy across image layers,
  including group children. Copies are explicitly **unlinked**, regardless of
  the editor's continuous-layer preferences. It returns `insertedFrame`.
- `durationMs` is optional when adding: blank defaults to 100 ms; a copy inherits
  the source duration. `set_frame_duration` updates one frame, with an inclusive
  native-file-safe range of **1–65,535 ms**.
- `remove_frame` deletes the frame's cels and duration, retaining at least one
  frame. Adding/removing adjusts existing tag ranges with the native API.
- **Indices shift after insertion/removal.** Inspect again rather than reusing
  an old frame index or revision. A changed duration can be undone/redone just
  like a drawing batch.
- Structural frame edits refuse locked layers and sprites with per-frame palette
  changes: upstream does not yet shift those palettes safely. They are not
  silently flattened or discarded. Duration-only edits remain available.

## Manual editing, disconnects, and safety

- **Pause before editing manually.** Native pause blocks agent operations; it
  does not disable your mouse/keyboard or lock the document against you. There
  is no dedicated pause button in the editor yet; use the MCP tool, disconnect
  the MCP client, or close the agent-owned window to stop agent activity.
- Mutations target only the **active GUI document**, with explicit document,
  layer, and frame identifiers. The bridge never silently switches documents
  for an edit. Create/open visibly select the new document.
- An edit, save, undo, or redo requires the latest revision. Revisions are
  derived from metadata, native history, and actual image bytes. A manual edit
  observed before a request causes `STALE_REVISION`. IDs/revisions are scoped
  to a session, not persistent file identifiers.
- Drawing gestures, playback, transforms, captured mouse input, and modal
  dialogs cause `BUSY`. Finish the interaction, inspect, then continue.
- **Disconnect pauses the native bridge.** Reconnect, inspect, and explicitly
  resume; do not assume a reconnected server is permitted to edit.
- On a timeout/disconnect during an operation, the outcome is **unknown**:
  the native transaction may already have completed. The server never retries
  edits automatically. Reconnect and inspect rather than blindly repeating.
- Successful JSON-RPC requests can be replayed with the **same ID and exact
  contents** while retained in the native deduplication cache (128 entries,
  bounded to 16 MiB). This is not durable or unlimited exactly-once delivery;
  the MCP client does not depend on it to retry mutations.
- Ending the MCP server leaves the GUI and unsaved work open. Close it yourself.
  The launcher will not overwrite an existing socket. After an editor crash,
  remove an endpoint only after confirming it is stale, or choose a new path.
- File operations reject traversal and symlink escapes; saves encode to a
  unique sibling file before publication. No-overwrite saves use atomic hard
  linking; overwrite saves use atomic rename. The root policy is not a
  hardened sandbox against hostile processes running as the same OS user.
- This development build still uses ordinary LibreSprite preferences/recovery
  locations. It is not a completely isolated editor profile.

## Current limits

- Native transport: **macOS and Linux** (tested on macOS/Apple Silicon); Windows
  is explicitly unsupported for now. Stock editor behavior remains unchanged
  when no automation flags are passed.
- One bridge client and serialized short requests on the UI thread. There is
  no TCP listener, arbitrary script tool, or remote network endpoint.
- At most a 1024×1024 canvas, 1,048,576 preview pixels, 256 frames,
  128 layers **including nested groups/children**, 32 open
  documents, and 32 MiB of image working data / input file size.
- Pixel batches: 1–16,384 pixels, transparent **RGBA image layers only**.
  Background/locked layers and linked cels are refused. Colors replace pixels,
  duplicates use the last supplied color, and selection masks are not applied.
- Palette/tag creation and editing, asset browsing, contact sheets, onion-skin
  previews, brush engines, cross-group reparenting, and GIF/animation export are
  not exposed yet. Multi-frame native `.ase` files can be created and saved now.
- The pinned editor's legacy bulk group UI and crash-recovery paths are not fully
  implemented/validated. Use the guarded MCP layer/frame operations for grouped
  structural edits, select an image child for manual drawing, and save native
  files regularly; do not rely on crash recovery to preserve group hierarchy.
- File opening uses upstream codecs; compressed native input can allocate more
  memory than its file size before working limits are checked. Only open
  trusted assets. Modern Aseprite files may contain chunks LibreSprite skips;
  saving them must not be assumed lossless.
- Native file encoding and rendering run on the UI thread and may briefly
  block input within these limits. Large operations will need asynchronous
  preparation in a later milestone.

## Tests

```sh
npm test
python3 -m unittest discover -s tests -v
python3 scripts/smoke-test-libresprite.py
python3 scripts/test-live-bridge.py
```

`test-live-bridge.py` opens a **new real GUI process**, edits only its disposable
sprites, and terminates only that test-owned process. It verifies PNG pixels,
native undo/redo, cel cropping/clearing/recreation, save/reopen, revisions,
deduplication, pause/reconnect, and path boundaries. It also runs the cases in
`scripts/bridge_workflow_cases.py`: geometry/fill/strokes, properties/locks,
group traversal/copy/deletion/save/reopen, blank/independent frame insertion,
durations/deletion/undo, tag ranges, and unsupported-palette guards.
All ten new mutations are checked against session/pause/revision gates, and
an oversized frame copy must roll back its data, saved state, and selection.
Linked-cel and background restrictions have explicit regression cases too.
Do not interact with that test window while it runs. The tests do not establish
cross-platform GUI correctness or unlimited hostile-input resilience.

For a small end-to-end MCP demonstration that leaves its own editor open:

```sh
node scripts/demo-live.mjs
node scripts/demo-live.mjs --animation
```

It uses the real MCP stdio protocol, creates a new demo sprite, draws it in
several visible batches, exercises undo/redo, saves it, and returns a rendered
PNG under `.runtime/`. It pauses the editor before disconnecting. Each run uses
a distinct socket and asset directory; it never changes another window.

`--animation` adds a backdrop, an effects group, and four independent twinkling
frames using the new native tools. It verifies every frame and duration after
saving/reopening `.ase`, and writes enlarged frame PNGs under the printed asset
directory. Agent editing is paused at the end; you can still use LibreSprite's
play button to preview the animation manually.

## Native implementation notes

The app starts `app/automation/bridge.cpp` only with `--automation-socket` and
`--automation-root`. A native 16 ms UI timer performs bounded nonblocking socket
I/O and processes at most one request per tick. Short pixel batches are built
off-document, validated in full, then applied under `ContextWriter` using
`Transaction`, `PatchCel`, and `AddCel`. The existing renderer composites
frames; enlarged previews use nearest-neighbor copying into a PNG surface.
Native layer commands handle addition/properties/restacking/removal. Frame tools
reuse the existing `DocumentApi` range adjustments and use explicit unlinked
`CopyCel` operations. Drawing primitives prepare a bitmap mask off-document,
convert it to changed spans, and apply one patch transaction. Working-data
limits are checked before committing, so oversized edits roll back.
Rollback may still advance native version counters; inspect again for a fresh
revision after a limit refusal, even though pixels and history were restored.

Two upstream fixes accompany this milestone:

- Frame insertion at index 0 no longer reads a duration at index -1.
- Layer counts and layer/cel iterators follow preorder through groups rather
  than only siblings. This fixes native image enumeration, grouped frame
  copying/deletion, and group save/undo paths, not just MCP inspection. Group rows
  and brush previews no longer reinterpret groups as image layers; deleting a
  group moves descendant selections out of the subtree in every document view.
  Manual painting also refuses a group itself rather than treating it as a cel.

Changes to this native code require rebuilding LibreSprite. Changes to `src/`
need only `npm run build`; normal agent sprite edits need neither rebuild.

The initial unmodified baseline is committed separately from native changes.
`scripts/vendor-libresprite.py --verify` intentionally reports those native
changes as differences. `vendor/libresprite.upstream.json` continues to describe
the **imported upstream baseline**, not the current modified working tree.
The JSON parser is MIT-licensed nlohmann/json v3.11.3, pinned with provenance
and its license under `vendor/`.

### Verified milestone

On the development Apple Silicon Mac, the native build, seven Python helper
tests, nine TypeScript/MCP tests, the baseline CLI smoke test, and the real GUI
bridge test pass. The visible four-frame mushroom animation demonstration also
passed end to end through MCP stdio, including grouped layers, independent cels,
pixel-identical previews before undo/after redo, and exact frames/timing after a
native save/reopen. Linux support is implemented but has not been tested here.
