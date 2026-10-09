# Live editor and MCP server

This milestone provides a **local, visible, undoable editing slice**, not the
complete artist workflow yet. The editor is a custom build of the pinned
LibreSprite source; an installed stock LibreSprite does not have this bridge.

## Setup

For the relocatable Apple Silicon `.app` and production MCP folder, see
[packaging/setup](packaging.md). The instructions below describe source builds.
Packaged defaults use a sibling app, a private system-temporary socket directory,
and `~/Pictures/LibreSprite AI MCP/`, not checkout-local paths. `--doctor` provides
read-only setup checks; `--doctor --connect` explicitly connects/pauses on
disconnect. Neither adds an MCP tool or automatically resumes editing.

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
      "args": ["/absolute/path/to/libresprite-ai-mcp/dist/index.js"]
    }
  }
}
```

The config shape and location depend on your MCP client. Use absolute paths so
its working directory does not matter. Tool results include real PNG image
content; your AI client/model must support MCP image results to see them.
Replace the placeholder path with your checkout's actual absolute path. See
[`examples/mcp/`](../examples/mcp/README.md) for generic stdio and OpenCode V2
templates. Merge the relevant entry into existing client settings; do not
replace unrelated settings. Personal client configuration stays untracked.

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
| `libresprite_activate_document` | Explicit revision/previous-active guarded tab switch |
| `libresprite_set_active_site` | Focus a layer/frame without editing document data |
| `libresprite_close_document` | Confirmed saved/unmodified active-document close |
| `libresprite_copy_cel` | Independent whole-cel copy within one sprite |
| `libresprite_duplicate_frames` | Ordered copies of explicit pre-edit frame indices |
| `libresprite_reorder_frames` | Full permutation with pose timing/link/tag guards |
| `libresprite_edit_cels` | Atomic explicit multi-frame/layer cel property/transforms |
| `libresprite_set_frame_durations` | Atomic explicit frame/timing batch |
| `libresprite_transform_selection` | Selected-region flips/rotations across explicit frames |
| `libresprite_resize_canvas` | Resize/shift all frames while preserving off-canvas pixels |
| `libresprite_crop_canvas` | Explicit, guarded, undoable all-frame pixel/mask crop |
| `libresprite_duplicate_layer` | Independent image-layer or nested-group subtree copy |
| `libresprite_reparent_layer` | ID-preserving cycle-safe move into an explicit group/root |
| `libresprite_set_polygon_selection` | Even-odd polygon pixel mask with native inclusive edges |
| `libresprite_set_bitmap_selection` | Explicit sparse row-major binary pixel mask |
| `libresprite_draw_brush_stroke` | Explicit bitmap brush along a connected native path |
| `libresprite_set_indexed_pixels` | Exact palette-index painting/erasure without conversion |
| `libresprite_inspect` | Layers/cels, frames/durations, palettes, tags, revision |
| `libresprite_render` | Composite a frame to PNG image content |
| `libresprite_list_assets` | Browse supported assets/directories inside the root |
| `libresprite_preview_asset` | Render a file thumbnail without opening a GUI tab |
| `libresprite_contact_sheet` | Read-only tiled animation preview with frame rectangles |
| `libresprite_render_onion_skin` | Read-only native ghost-frame preview |
| `libresprite_export_png` | Atomic composited frame PNG export |
| `libresprite_export_sprite_sheet` | Atomic PNG sheet export with returned layout/timing metadata |
| `libresprite_export_animation` | Atomic GIF or lossless RGBA APNG export |
| `libresprite_create` | New single-frame transparent RGBA or indexed sprite |
| `libresprite_open` | Open PNG or a native sprite inside the root |
| `libresprite_set_pixels` | Atomic replacement-color pixel batch |
| `libresprite_create_layer` | New image layer or group, with explicit parent/order |
| `libresprite_update_layer` | Name, visibility, editable/lock state, image opacity/blend |
| `libresprite_move_layer` | Restack within the same group |
| `libresprite_remove_layer` | Delete a layer or explicitly authorized group subtree |
| `libresprite_add_frame` | Insert a blank frame or independent copy |
| `libresprite_remove_frame` | Delete a frame, keeping at least one |
| `libresprite_set_frame_duration` | Frame timing in milliseconds |
| `libresprite_set_palette` | Undoable sparse palette entries and/or resize at a frame |
| `libresprite_remove_palette` | Undoably remove a nonzero palette keyframe |
| `libresprite_create_tag` | New native animation tag with inclusive range |
| `libresprite_update_tag` | Atomic tag name/range/direction/label color |
| `libresprite_remove_tag` | Undoably delete one tag by explicit ID |
| `libresprite_draw_shape` | Native line, rectangle, or ellipse |
| `libresprite_draw_stroke` | Connected one-pixel polyline |
| `libresprite_flood_fill` | Contiguous fill or all matching colors in a target cel |
| `libresprite_update_cel` | Atomic cel position and/or opacity |
| `libresprite_transform_cel` | Whole-cel flips and exact quarter-turn/180° rotations |
| `libresprite_unlink_cel` | Make a native linked cel independent, explicitly |
| `libresprite_set_selection` | Rectangle/ellipse mask replace/add/subtract/intersect |
| `libresprite_modify_selection` | Select all, clear, or invert within the canvas |
| `libresprite_render_selection` | Read-only cyan selection overlay or white mask PNG |
| `libresprite_fill_selection` | Replace/erase selected RGBA pixels in one cel |
| `libresprite_translate_selection` | Atomic selected-pixel move/copy plus mask movement |
| `libresprite_undo` / `libresprite_redo` | One native undo transaction |
| `libresprite_save` | Atomic native-file save inside the root |

There are **59 tools** in server/bridge version **0.8.0**. Rebuild the editor
and start a **new development window** when upgrading: already-running windows
keep their old native bridge. `libresprite_connect` reports `bridgeVersion`
and supported native `methods` in new builds. Older bridge builds may not
provide those fields; a missing new method requires rebuilding/relaunching,
not blindly retrying it.
Restart/refresh the MCP server in your client after TypeScript upgrades too:
already-running stdio servers retain their original tool schemas/catalog.

## Visible user controls and navigation

Only bridge-enabled windows have the persistent bottom-right **AI control**:

- **AI: Waiting (paused)**: no client; disabled. Disconnect always pauses edits.
- **AI: Paused | Resume**: connected but agent mutations/navigation are blocked.
- **AI: Enabled | Pause**: connected and permitted to issue guarded operations;
  this does not mean an operation is currently running.

Click **Pause** before manual work. That sets a local user-pause latch: the agent
cannot override it with `set_paused(false)` (`USER_PAUSED`). It survives reconnect
and only the editor's **Resume** button releases it. Ordinary startup/disconnect
pauses without that latch can still be explicitly resumed through MCP.
Resume refuses busy drawing/playback/dialogs. Pause is available regardless of
the idle checks, but native work is synchronous: a click stops subsequent
requests, not a request already executing on the UI thread. This is not a
mid-operation cancellation button. `connect` returns `connected`, `paused`,
`pausedByUser`, and `controlText` for diagnostics.

All three navigation tools require a resumed bridge, current target revision,
and idle GUI. They are **not read-only tools**, even where document data is
unchanged; pausing also blocks agent-driven navigation and closing.

### Activate an open document

`activate_document` requires `documentId`, `expectedRevision`, and
`expectedActiveDocumentId` from `list_documents` (explicit null when Home/no
sprite is active). If the person changes tabs in between, the request fails with
`ACTIVE_DOCUMENT_CHANGED` rather than stealing focus. It selects an existing
native view and restores its frame/layer; already-active targets keep the current
view. No pixels, masks, saved state, revision, or undo history are changed.
Busy target views are refused too. It does not implicitly open/save/resume.

### Focus a frame or layer

`set_active_site` requires the **active** document, revision, and at least one of
`layerId`/`frame`. Omitted values remain unchanged. Both values are validated
before either is changed. Hidden, locked, and group layers can be focused for
review but are not shown/unlocked/painted. It refreshes the native timeline,
palette, and frame feedback without editing pixels/mask/history/saved state or
advancing the revision. Frame indices are zero-based.

### Close a saved document

`close_document` requires the **active** document, revision, and `confirm: true`.
The sprite must have an associated saved file (`hasFile: true` in inspect/list)
and be unmodified; even a never-saved blank sprite is refused with
`UNSAVED_CHANGES`. Save a native copy first. There is no discard/force/save-dialog
mode. Every target view must be idle. Closing removes **all cloned views** of
the sprite via native destruction, releases its undo history and session IDs,
and is **not undoable**, but does not delete/change saved files or quit the editor.
It returns `closedDocumentId`, `lastRevision`, and the newly selected
`activeDocumentId` (possibly null). Reopening creates a new document ID.
After an uncertain response list documents instead of blindly retrying.

## Atomic animation workflows (v0.7.0)

The following operations require a resumed bridge, the active sprite/current
revision, and idle GUI/target views. Frame arrays use explicit **zero-based**
indices rather than an implicit timeline selection. Each request is one native
undo transaction; invalid later targets cannot leave earlier targets edited.
These are targeted native operations, not an arbitrary-script or general batch
dispatcher. Cross-document/system-clipboard copy and general multi-frame
painting are not implemented by these tools.

### Copy a cel

`copy_cel` uses `sourceLayerId`/`sourceFrame` plus destination `layerId`/`frame`
in the **same sprite**. No frames are created. A source image cel is mandatory;
missing source is `CEL_NOT_FOUND`, not permission to erase a destination.
Hidden/locked/linked source cels may be read. Destination layers must be
transparent/editable with editable ancestors; linked/shared-image destinations
are refused. Existing destinations require explicit `overwrite: true`
(`CEL_EXISTS` otherwise). Same source/destination is a no-op.

This replaces the whole destination cel, including transparent pixels, and
copies the full cropped/off-canvas image, top-left position, opacity, and cel
user data into an **independent** image/cel-data object. It never silently links,
trims to canvas, flattens layers, or follows continuous-layer preferences. It
supports RGBA/indexed/grayscale. Indexed source/destination palettes must be
identical (`UNSUPPORTED_PALETTES` otherwise); no silent index remapping. The
selection mask is ignored and retained. Success focuses the destination.

### Duplicate frames

`duplicate_frames` takes 1–256 unique source `frames` and insertion `index`
in `0..frameCount` (append allowed, including index 256 when permitted by bounds).
Source indices always refer to the **pre-edit sprite**, and array order controls
the order of inserted copies. All sources are snapshotted before insertion,
including when source/destination ranges overlap.

It copies every image layer (nested/hidden/background included), missing cels as
missing, durations, raw images/positions/opacities/user data. Original links
remain intact; new cels are never linked. Group/layer properties stay unchanged.
Native insertion rules shift/extend existing tag ranges but create no new tags.
Locked layers/ancestors and multiple palette keys are refused. Total frames must
stay ≤256 and predicted image/scratch data within bounds. It focuses the first
inserted frame; inspect again because later indices shifted.

### Reorder frames

`reorder_frames` requires `order`, a complete unique permutation of every current
frame. `order[newIndex] = oldIndex`; e.g. `[2,0,1]` places original frame 2 first.
All cels/images/cel-data (including links, off-canvas pixels and user data) retain
their identities. Durations move with poses; active pose remains focused at its
new index. Identity order is a no-op.

Tag ranges move with the **original member frames**. If those frames would become
disjoint the request fails with `TAG_SPLIT`; update/remove that tag explicitly
first rather than silently broadening or splitting it. Within a surviving range
the requested permutation controls playback order; tag direction/color/name/ID
are unchanged. Multiple palette keys and locked layers/ancestors are refused.

### Atomic cel and timing batches

`edit_cels` takes 1–256 `edits`, each identifying an existing `layerId`/`frame`
and at least one of `x`, `y`, `opacity`, or `operation`. Position values are
absolute signed native coordinates (−32768..32767); opacity is 0..255. Exact
operations are `flip_horizontal`, `flip_vertical`, `rotate_cw`, `rotate_ccw`, and
`rotate_180`. A transform permutes the entire cel at its top-left, then optional
position/opacity overrides apply. It supports RGBA/indexed/grayscale, ignores
the selection, and preserves off-canvas data. Existing transparent editable
unlinked cels are required; transforms also refuse shared images. Duplicate
layer/frame pairs are refused. All properties/targets are validated, and all
transformed images prepared, before the transaction starts. It leaves focus
unchanged and reports `editedCels` (changed targets only).

`set_frame_durations` takes 1–256 `durations`, each with unique `frame` and
`durationMs` (1..65535). It validates all entries before changing any timing,
leaves pixels/masks/tags/focus unchanged, and works with palette keyframes. It
reports `editedDurations` (changed frames only). Both batches preserve revision
and undo/redo history when nothing changed.

### Selected-region transforms across frames

`transform_selection` takes one `layerId`, 1–256 unique `frames`, and exact
`operation` from the list above. It requires a **visible nonempty document-wide
selection** (`NO_SELECTION` otherwise), RGBA mode, and editable transparent
unlinked/unshared targets. A missing cel samples as transparent. There is never
a whole-cel fallback or implicit unlink.

The selection bounding-box **top-left stays anchored**. Quarter turns swap
width/height; the original and destination bounds must both be wholly on canvas.
Clipping is refused. The operation snapshots each frame, clears only original
selected bits, and replaces transformed destination bits with original samples
(including transparent overwrites). Sparse mask holes and unrelated pixels
outside source/destination selected bits remain untouched, as do off-canvas cel
pixels. The mask itself transforms **once**, and is included with all frame edits
in one undo step. Mask-only changes do not mark the sprite modified; no pixel/mask
change consumes no history. Success focuses the first requested frame.

Aggregate worst-case crop growth is checked before allocations/edits. Native
working image data and per-request image scratch are each bounded at 32 MiB;
requests can conservatively refuse a large/off-canvas operation even if later
native trimming might reduce its final size. Whole-cel transformed bounds are
at most 1024×1024. Native undo can advance internal version/revision counters
even while restoring pixel-perfect persistent data: always inspect again.
Background recovery can initialize native layer/image version telemetry from
0 to 1 without editing anything. Revision fingerprints treat only that initial
bookkeeping transition as equivalent; properties/pixels/IDs/history and higher
versions still detect changes. The raw version fields in inspect remain native
telemetry and can therefore change during an otherwise read-only workflow.

Run `python3 scripts/test-live-bridge.py --animation-only` for focused disposable
GUI/native-file regressions, or `node scripts/demo-animation.mjs` for the
[step 2 manual review](testing-v0.7.md).

## Canvas, layers, masks, brushes, and indexed painting (v0.8.0)

These edits require an active document/current revision, resumed bridge, and idle
target views. Each request is one native undo transaction; unchanged requests
preserve revision/history/focus. Invalid later targets or work limits cannot
leave earlier changes applied. The same idle-view check now also applies to
earlier document-mutating tools, including undo/redo/save.

### Canvas resize versus destructive crop

`resize_canvas` takes `width`/`height` (1..1024), optional signed `offsetX`/
`offsetY` (−1023..1023, default 0). It changes the canvas **without scaling or
deleting pixels**, even when shrinking. Off-canvas cel pixels remain in the
native file and return when the canvas grows. Offsets move every unique linked
cel-data object **once**, and move the full selection, including hidden/off-canvas
masks. No centering is inferred. Signed native cel/selection origin limits are
checked before changes. Timing/tags/palettes/link identities/focus stay intact.
If there are no cels or selection to shift, an unchanged-size offset request is
a no-op; if only the selection shifts, saved/modified state remains unchanged.

`crop_canvas` takes explicit in-canvas `x`, `y`, `width`, `height`; this rectangle
becomes the new canvas at origin 0,0. It crops raw cel images on **all frames and
layers**, removes wholly outside cels, and clips/moves the visible selection.
Any cel **bounds** (even transparent padding/off-canvas data) or mask bounds
outside the crop is `WOULD_DISCARD_PIXELS` unless `discardOutside: true` is
explicitly provided. Do not authorize this automatically just to bypass a refusal.
One Undo restores every removed pixel/cel, the old canvas size, positions and mask.
Remaining linked cels stay linked, and opacity/user data/timing/tags/palettes stay
intact. A full-canvas crop can still discard existing off-canvas data.

Both support transparent RGBA/indexed/grayscale layers, refuse native background
layers and locked layers/ancestors, and never convert/remap colors. Convert a
background deliberately in the editor first. Crop also refuses a retained hidden
selection (`HIDDEN_SELECTION`), cross-layer shared cel data (`SHARED_CEL_DATA`),
or images shared by separate cel-data objects (`SHARED_IMAGE`) rather than
implicitly unlinking or corrupting aliases. Scratch images are prepared and
bounded to 32 MiB before mutation. Resize retains all these aliases unchanged.

### Independent subtree duplication and reparenting

`duplicate_layer` takes source `layerId`, optional `name`, destination `parentId`
(omitted=same parent, null=root), and `afterLayerId` (omitted=after source in same
parent or destination top, null=bottom). Image layers or complete nested groups
are copied across all frames: names, flags (including visibility/lock/continuous),
image-layer opacity/blend, layer/cel user data, raw off-canvas pixels, positions
and cel opacity. **Every copied cel/image is independent**, including linked
sources; source links remain unchanged. Copies get new IDs and success focuses
the new top-level layer. Hidden/locked sources can be read, but destination
ancestors must be editable. Background sources, below-background insertion,
more than 128 layers, or predicted data above 32 MiB are refused.

`reparent_layer` moves a layer/group subtree to explicit `parentId` (null=root).
Optional `afterLayerId` means a destination sibling or null=bottom; omission
keeps position for the same parent or appends at the new destination top. It
retains every layer/cel/image ID, byte, link and property. Compositing can change
because group visibility and stack order change. It refuses self/descendant
cycles (`LAYER_CYCLE`), locked source/destination ancestry, movement-locked or
background targets, and below-background insertion. One Undo restores parent/order,
even after a later folder deletion/restoration; focus remains on the existing
layer/frame. `move_layer` retains its earlier same-parent-only behavior.

`update_layer` additionally accepts `blendMode` for transparent image layers:
`normal`, `multiply`, `screen`, `overlay`, `darken`, `lighten`, `color_dodge`,
`color_burn`, `hard_light`, `soft_light`, `difference`, `exclusion`, `hue`,
`saturation`, `color`, `luminosity` (native values 0..15 in this order).
Properties remain atomic, lock checks unchanged, and group/background blend or
opacity changes remain unsupported. Inspect reports numeric `blendMode`,
`continuous` and `movable` flags; no global preferences are changed.
Cel metadata includes `celId`/`celDataId`/`imageId` for verifying independent
copies and retained links/identity. Nonempty layer/cel `userData` contains native
`text`/packed RGBA `color`; these properties also participate in revisions, so a
first user-data edit is not hidden by recovery's initial version canonicalization.

### Polygon and explicit bitmap masks

`set_polygon_selection` takes 3..128 in-canvas `{x,y}` vertices with at least
three distinct points. It fills at pixel centers using the **even-odd** rule,
then includes native one-pixel boundary lines. Winding reversal is equivalent;
self-intersections use even-odd fill rather than refusing, and degenerate edges
remain one-pixel lines. No antialiasing. Bounding-box pixels × edge count is
limited to 8,388,608 to keep work bounded.

`set_bitmap_selection` takes in-canvas `x/y/width/height` and `bits`, a string of
exactly `width*height` binary digits, row-major top-to-bottom, up to 262,144
digits. `1` selects, `0` doesn't: sparse/disconnected regions and holes are allowed.
All zeros clears in replace mode. Larger simple masks can use rectangle/polygon
tools rather than a large binary string.

Both accept `mode: replace | add | subtract | intersect` (default replace),
combine the actual pixel mask within canvas, treat hidden masks as empty, and
clear empty results. These are document-wide, all-color-mode selections, not
saved sprite pixels. One Undo restores the visible mask without changing
saved/modified state or focus; identical masks preserve redo/history. Use
`render_selection` to check actual pixels.

### Explicit bitmap brushes and exact palette indices

`draw_brush_stroke` requires explicit `layerId`/`frame`, 1..1024 in-canvas path
`points`, and `brush: {width, height, bits, anchorX?, anchorY?}`. Footprints are
1..32 pixels per dimension, exact row-major binary strings with at least one
set bit. The anchor defaults to `(floor(width/2), floor(height/2))`; custom anchors
must be inside the footprint. Native one-pixel lines connect the points and the
brush is stamped at each unique center; overlapping stamps just replace the
same color/index. Work is bounded to 8,388,608 stamp-pixel visits. Brush footprint
clipping is refused unless `clipToCanvas: true`; no global brush/pressure/smoothing
settings are touched.

RGBA sprites require `color: {r,g,b,a}`, indexed sprites require exact `index`
(0..255); supply **exactly one**, and no grayscale painting/conversion is added.
Replacement is not alpha blending; RGBA alpha0 or the sprite's transparent palette
index erases. `respectSelection: true` requires a visible mask and limits every
stamp pixel; default ignores the mask. Target must be an editable transparent
image layer with no linked/shared image. One Undo restores the complete stroke.
Changed strokes focus the target; no-op strokes don't.

`create` accepts `colorMode: rgba | indexed` (default rgba). Indexed sprites
start with a native 256-entry palette and transparent index0; set explicit
swatches with `set_palette`. Inspect/list/preview report `transparentIndex`
(null for nonindexed), so agents don't infer which index erases an existing file.
`set_indexed_pixels` takes 1..16384 `{x,y,index}` pixels in an indexed target.
The index must exist in that frame's effective palette or equal transparentIndex.
Duplicate coordinates use the **last supplied index**. All pixels validate even
if unselected; `respectSelection` and target guards match brush painting. Missing
cels can be created; no-op/transparent-on-empty patches don't consume history.
Raw indices are never converted, alpha-blended, recolored, or remapped; palette
keyframes affect rendering only through their normal index lookup.

Run `python3 scripts/test-live-bridge.py --editing-only` for focused disposable-GUI
regressions, or `node scripts/demo-editing.mjs` for the [step 3 review](testing-v0.8.md).

## Layers, drawing, and animation

Every mutating tool below requires the active `documentId`, `expectedRevision`,
and a resumed bridge. Layer/frame operations use native undo transactions just
like pixel edits. Inspection now also reports `activeLayerId` and `activeFrame`;
changing the active UI layer/frame alone does not change the document revision.
Changing the pixel selection mask does.

### Layers

- `create_layer` accepts `type: "image"` (default) or `"group"`, a `name`, and
  optional `parentId`. Omitted/null parent means the root. It returns
  `createdLayerId` so agents do not need to identify a new layer by name.
- Layer order is **bottom to top**, recursively in inspection output.
  Omit `afterLayerId` when creating to append on top; use an explicit null to
  insert at the bottom. Moving requires a sibling ID or null and never reparents
  a layer. Insertion below a background layer is refused.
- `update_layer` accepts any combination of `name`, `visible`, `editable`, and
  image `opacity` (0–255) or `blendMode` (names above). The whole update is one undo step. A locked layer can
  be explicitly unlocked, but **only in a separate request** before other
  property edits. Locked ancestors cannot be bypassed. Group/background opacity
  and blend mode changes are not exposed.
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
  single atomic undo step. A one-point stroke draws one pixel. For custom bitmap
  footprints use `draw_brush_stroke`; pressure and smoothing are not added.
- `flood_fill`: use seed `x,y`, `tolerance` (0–255, default 0), and `contiguous`
  (default true). It samples **only the target cel**, with transparent pixels
  filling the rest of its canvas, **not the visible multi-layer composite**.
  Non-contiguous mode replaces all matching pixels in that cel. Native color
  matching compares channels and treats fully transparent colors as equivalent.
- All use explicit `layerId`, zero-based `frame`, and a `color` object containing
  `r,g,b,a`. Colors replace pixels rather than alpha-blending; alpha 0 erases.
  Existing pixels outside the shape/region are preserved, including cropped cels.
  Selection masks are ignored **by default**, retaining previous behavior.
  `respectSelection: true` requires a visible nonempty mask and clips painting
  to its selected pixels (also available for `set_pixels`). For contiguous flood
  fill the mask is a traversal barrier; non-contiguous fill only replaces selected
  matches. An unselected seed is a no-op in either mode. All supplied pixel/point
  coordinates still validate even if outside the selection. Drawing requires an
  editable, transparent RGBA image layer and an unlinked, independent-image cel.
  Geometry/fill/stroke requests
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

## Cel transforms and selection-based editing

### Cel properties, whole-image transforms, and unlinking

`libresprite_update_cel` requires explicit `layerId`/`frame` and at least one
of `x`, `y`, or `opacity`. Positions are signed native-file coordinates,
**−32,768 through 32,767**; opacity is 0–255. The update is one native undo
transaction, without changing any image pixels. Moving content outside the canvas
does **not** discard it. Render/export only shows the canvas intersection.

`libresprite_transform_cel` takes one `operation`:

- `flip_horizontal` / `flip_vertical`: native raster flips.
- `rotate_cw` / `rotate_ccw`: exact 90° integer pixel permutations.
- `rotate_180`: an exact 180° permutation.

These transform the **stored cel image**, including transparent padding and
off-canvas pixels, not the entire sprite canvas or the selected region. Quarter
turns swap image width/height; the cel's **top-left position and opacity stay
fixed**, rather than centering it. No interpolation, palette remapping, or
automatic clipping occurs. Inspect cel bounds before choosing an operation:
a new missing-cel drawing patch may initially span the canvas, while a subsequent
native patch trims transparent edges. Whole-image transforms currently require
cel dimensions of at most 1,024×1,024.

Properties and transforms work in RGBA, indexed, and grayscale modes. They
refuse groups, background layers, locked layers/ancestors, missing cels, and
native linked cels. Image transforms additionally refuse unusual separate cels
sharing one image object. Identical properties/symmetric image transforms are
no-ops that preserve revision/history and GUI selection. Changed requests
select the explicit target layer/frame for visible feedback.

`libresprite_unlink_cel` explicitly clones one native linked cel's image/data,
preserving pixels, position, opacity, and user data. Other linked frames are
unchanged, and native undo restores the link. Already-independent cels are
no-ops; missing/locked/background targets are refused. All these mutations need
the active document, current revision, and resumed bridge.

Large off-canvas coordinates can make a small canvas patch require a huge
temporary union image. The bridge now refuses a union over **32 MiB** (or one
that exceeds total sprite image working data) **before** native allocation, not
only after a transaction has run. Bring a far-away cel nearer before editing its
pixels through canvas-based tools; refusals never discard off-canvas content.

### Visible document-wide masks

`libresprite_set_selection` takes `shape: "rectangle" | "ellipse"` (default
rectangle), inclusive `x1,y1,x2,y2` canvas endpoints (reversed corners allowed),
and `mode: "replace" | "add" | "subtract" | "intersect"` (default replace).
Shapes use native integer rasterization. Combination uses the **actual bitmap**,
not just bounding rectangles, and clips the result to the canvas. Hidden/
deselected masks count as empty; subtract/intersect with no visible mask remains
empty. Empty results clear the visible selection.

`libresprite_modify_selection` accepts `action: "all" | "none" | "invert"`.
All selects the canvas; none clears the active selection; invert selects the
complement inside the canvas. Inverting no visible selection selects all.

Selections are **document-wide**, shared across frames/layers. They do not
silently switch GUI frame/layer and do not edit image pixels or saved/modified
state. Changes still use native selection undo transactions and advance revision;
identical masks do not consume history or clear redo. Revisions fingerprint mask
bits, not just their bounding box/pixel count, so manual mask changes invalidate
stale operations too. Selection is a live editing state, not a promised persistent
selection in saved native files. Undo history after reopening is not retained.

Inspection includes `selection` with `visible`, `x`, `y`, `width`, `height`, and
`selectedPixels`. A hidden native mask may still have bounds/count for reselecting;
only a **visible** mask can authorize selected pixel operations. Mask bitmaps are
limited to 1,048,576 pixels. Failed transactions restore even retained hidden
mask bits/visibility/transformation state along with GUI layer/frame selection.

### Selection feedback and pixel operations

`libresprite_render_selection` requires `documentId`/`frame`, optional `scale`
(1–16), `mode: "overlay" | "mask"` (default overlay), and `opacity` (0–255,
default 96). Overlay highlights selected pixels cyan over the native composite;
opacity 0 is the ordinary frame unchanged. Mask mode is opaque white selected
pixels and transparent elsewhere. With no visible selection, it returns the
ordinary frame or empty mask. It is read-only, works paused/inactive, and is
bounded to 1,048,576 output pixels. Ordinary render/export never burns the mask
overlay into sprite pixels.

`libresprite_fill_selection` replaces the selected pixels of an explicit RGBA
image `layerId`/`frame` with `color`; alpha 0 erases. It does not blend colors or
sample the layer composite. The mask and all unselected/off-canvas pixels are
preserved. A missing cel can be created if pixels actually change. Identical
pixels are a no-op. **Absent or hidden selection is `NO_SELECTION`, never a
whole-cel clearing fallback.**

`libresprite_translate_selection` takes `layerId`/`frame`, integer `dx`/`dy`
(−1,023 to 1,023), and optional `copy` (default false):

- Move clears selected source pixels; copy leaves them alone.
- Both snapshot raw source pixels before writing, so overlapping moves/copies
  are safe. Destination selected pixels **replace** colors, including transparent
  source pixels; copying a selected transparent hole erases the destination there.
- The selection bitmap moves too. One native undo step restores **pixels and
  mask together**. A blank-pixel move that only changes the mask preserves saved
  state. Zero displacement is a no-op.
- Source mask and destination bounds must be wholly inside the canvas. Outside
  masks/destinations are refused (`SELECTION_OUTSIDE_CANVAS` / `OUTSIDE_CANVAS`)
  rather than clipping or silently losing pixels.

These selected pixel operations require the active document/current revision/
resumed bridge. They select changed target layer/frame, are RGBA-only for now,
and refuse locked/background/linked/shared-image targets. For indexed/grayscale
sprites, whole-cel transforms/properties remain available. Indexed selection-aware
painting uses `set_indexed_pixels`/`draw_brush_stroke`; selected-region moves/
rotations and automatic palette remapping remain unsupported there.

```json
{
  "documentId": 3, "expectedRevision": 18, "layerId": 5, "frame": 0,
  "dx": 4, "dy": 0, "copy": true
}
```

First set/render a selection, then use its fresh revision for this copy request.
Render the result and continue from the newly returned revision.

## Palettes and animation tags

These mutations require the active document, current revision, and resumed bridge,
and use one native undo transaction per request. They leave GUI layer/frame
selection alone. Save `.ase` regularly to preserve this editable metadata.

### Palette keyframes

`libresprite_set_palette` requires `frame` and one or both of:

- `entries`: 1–256 unique `{ "index": n, "color": { "r", "g", "b", "a" } }`
  pairs. Indices must be inside the **final** palette size; entries replace RGBA
  swatches, not blend them. Unspecified entries are retained.
- `size`: 1–256 colors. New entries use native palette resize defaults (opaque
  black); supply explicit colors if you want a particular ramp.

The effective palette at a frame may be inherited from an earlier keyframe.
If colors/size actually change, the bridge edits an exact existing key or creates
one **at the requested frame**. It never changes an earlier inherited keyframe
implicitly. The new palette applies through the frame before the next keyframe.
Identical effective colors/size are a **no-op**, not a redundant keyframe, and
do not consume history or clear redo.

For RGBA sprites, these are **swatches**: existing RGBA pixels do not change.
For indexed sprites, editing an entry recolors all pixels using that index in
the affected frame interval, including locked layers, just like native palette
editing. Index bytes are not remapped. A shrink refuses any excluded transparent
index or cel pixel index, including hidden layers/groups and off-canvas pixels.
Use a separate remapping workflow in the editor if index consolidation is needed.

```json
{
  "documentId": 3, "expectedRevision": 12, "frame": 0, "size": 4,
  "entries": [
    { "index": 0, "color": { "r": 0, "g": 0, "b": 0, "a": 0 } },
    { "index": 1, "color": { "r": 220, "g": 50, "b": 60, "a": 255 } }
  ]
}
```

`libresprite_remove_palette` removes an **exact** keyframe at `frame > 0`;
that interval then inherits the preceding palette. Frame-zero base palettes
cannot be removed. Indexed removal is refused if the preceding palette would
exclude any affected cel/transparent index. Removal and sparse edits are undoable,
including repeated undo/redo of added or removed keys.

Grayscale palettes are a fixed ramp and are not editable through these tools.
Editing existing palettes larger than 256 entries is also refused. Inspection
still supports up to 4,096 entries per palette and 256 palette keyframes, with
frame indices and packed RGBA values (`r | g<<8 | b<<16 | a<<24`). Native frame
insertion/removal **still refuses multi-palette sprites**; remove nonzero keys
explicitly before structural frame edits, or use duration-only edits.

### Native tags

- `libresprite_create_tag` takes `name` (1–120 UTF-8 bytes), inclusive zero-based
  `from`/`to`, optional `direction: "forward" | "reverse" | "pingpong"`
  (default forward), and optional RGBA label `color` (default opaque black).
  Label colors must have **`a: 255`**; native tag files do not preserve alpha.
  It returns `createdTagId`; inspection includes `tagId` on every tag.
- `libresprite_update_tag` takes a `tagId` and at least one name/range/direction/
  color property. The final range must be inside the sprite and `from <= to`.
  All fields validate before one atomic transaction; identical values are a no-op.
- `libresprite_remove_tag` deletes only the tag, not its frames or pixels.
  Native undo restores the same tag ID within the editor session.

There are at most **128 tags**. Overlaps and duplicate names are allowed;
explicit IDs disambiguate them. IDs belong to a document/editor session, not to
the file on disk—inspect for fresh IDs after reopening. Inspection/sheet manifests
report numeric directions (`0` forward, `1` reverse, `2` pingpong); mutation tools
accept the readable names above. Existing native insertion/deletion commands
continue to adjust tag ranges.

## Asset browsing, animation previews, and export

### Browse without opening tabs

`libresprite_list_assets` lists **one directory** inside the configured asset
root. `path` defaults to `"."`; `offset` defaults to 0 and `limit` to 50 (1–100).
Directories appear first, then `.png`, `.ase`, and `.aseprite` files, each group
sorted by bytewise name order. Paths in results are root-relative. File entries
include their byte size and format; all symlinks, special files, and other
extensions are skipped. Extension matching is currently case-sensitive.

Follow `nextOffset` until it is null; `total` counts supported entries, not all
files. Pagination is not a filesystem snapshot: if files change between calls,
restart at offset 0. A directory with more than **4,096 total entries** is
refused before returning a partial listing. Browse a smaller subdirectory rather
than expecting recursive traversal.

`libresprite_preview_asset` takes a trusted root-relative file `path`, optional
`frame` (default 0), and `scale` (1–16, default 1). It decodes the file with native
codecs, renders a PNG, and disposes the detached document **without opening a
tab**. It returns dimensions, frame count, frame duration, and resolved path,
but **no document ID or revision**. Use `libresprite_open` when you want to edit
that asset. There is no persistent thumbnail cache. Like native open, explicit
in-root symlink aliases can resolve to an in-root asset; escapes are refused.

Both tools work while paused, but still respect the GUI `BUSY` boundary.
Thumbnail decoding loads native data rather than providing a hostile-input
sandbox or a reduced-memory decoder. Only preview trusted files.

### Contact sheets

`libresprite_contact_sheet` returns PNG image content plus a `sheet` manifest,
without writing files. Required: `documentId`. Optional layout settings:

| Setting | Behavior |
| --- | --- |
| `frames` | Omit for all; otherwise 1–256 unique source indices in your chosen order |
| `columns` | Default `ceil(sqrt(frame count))`; 1–16, no more than the selected count |
| `scale` | Nearest-neighbor enlargement, 1–16 (default 1) |
| `padding` | 0–16 **output pixels** between cells and on every outer edge (default 0) |

Each tile is the full visible native frame composite. No trimming, packing,
extrusion, labels, checkerboard, or layer-visibility changes are applied. Padding
and unused final-row cells are transparent. Output is bounded to **1,048,576
pixels**, including all padding and unused cells. Reduce frames/scale/padding if
the limit is exceeded. This read-only preview works for inactive documents too.

For a 32×32 four-frame sprite, this produces a 517×130 preview:

```json
{ "documentId": 3, "frames": [0, 1, 2, 3], "columns": 4, "scale": 4, "padding": 1 }
```

The returned `sheet.schema` is **`libresprite-sheet-v1`**, a project-specific
format, not an Aseprite-compatible export manifest. It reports output dimensions,
source dimensions, columns/rows, scale/padding, and an ordered `frames` array.
Each entry has `frame` (source index), `x`, `y`, `width`, `height` (output-pixel
rectangle), and `durationMs`. Tag `from`/`to` ranges always refer to **source
frame indices**, not tile positions, even for subset/reordered sheets.

### Onion skins

`libresprite_render_onion_skin` takes `documentId` and `frame`, with optional
`scale`, `previous`/`next` (0–8, defaults 1), `mode: "tint" | "merge"` (default
tint), `position: "behind" | "front"` (default behind), `opacity` (default 128),
and `opacityStep` (default 32). Opacity values are 0–255; each additional frame of
distance subtracts the step, clamped to 0–255.

- Tint uses native red ghosts for previous frames and blue ghosts for next frames.
  Merge uses original colors. Frames clip at sprite ends; tags never wrap playback.
- Optional `layerId` restricts **ghosts only** to that image layer or group.
  The current frame is still the full visible composite.
- Native composition/order is preserved. Behind ghosts may be hidden by opaque
  current-frame layers. Front ghosts can overlay/tint background layers at
  reduced opacity. Use an image/group filter to focus on moving elements.
- The result is read-only PNG image content with revision/settings metadata.
  No selection, current frame, document pixels/history, or editor onion-skin
  preference is changed. It works while paused and for inactive documents.

### Export PNGs safely

`libresprite_export_png` writes one composited `frame` with optional `scale`.
`libresprite_export_sprite_sheet` uses the same layout options and rendering as
contact sheets. Both require the **active** `documentId`, current
`expectedRevision`, a resumed bridge, and a root-relative `.png` `path`.

PNG bytes are encoded first, written to a private unique sibling, then published
atomically. Existing destinations are refused unless **`overwrite: true`** is
explicitly supplied. No-overwrite publication uses a hard link; overwrite uses
rename. Symlink destinations, directories, and path escapes are refused. This
is atomic publication, not a promise of power-loss durability or protection
against other hostile processes running as your OS user.

Export returns file path/byte count/revision metadata, **not image content**;
use the corresponding preview tool to inspect before exporting. Sprite-sheet
export includes its manifest **in the result**; it writes only the PNG, not a
second JSON sidecar. Clients may save that manifest separately, but such a pair
is not published as an atomic bundle.

Exports do not change the document's filename, saved/modified state, selection,
revision, or undo history. **Undo does not remove exported files.** Continue
using native `.ase` saves to preserve editable layers and animation. On an
uncertain timeout/disconnect, check the output and inspect rather than retrying
an export blindly.

### Animated GIF and APNG

`libresprite_export_animation` publishes one animated file, using the same
root-relative path, active-document/revision/session/pause, overwrite, and atomic
publication safeguards as PNG export. Specify `format: "gif"` with a `.gif`
path or `format: "apng"` with a `.apng` path. No document state, filename,
saved state, undo history, or GIF options/preferences are changed. Exported files
are not undoable. The result is metadata, not MCP animated-image content.

Optional settings:

| Setting | Behavior |
| --- | --- |
| `frames` | 1–256 source indices in supplied order; repeats are allowed |
| `tagId` | Export one tag using its inclusive range and native direction |
| `scale` | Nearest-neighbor 1–16 (default 1) |
| `loop` | `true` (default) plays forever; `false` plays once |
| `overwrite` | Defaults false; explicit true permits atomic replacement |

Omit both `frames` and `tagId` for all source frames in forward order. They are
**mutually exclusive**. Tag pingpong order omits duplicated endpoints:
`0,1,2,1` for range 0–2, or a single step for a one-frame tag. At most 510 steps
are generated from a 256-frame tag. Each step uses its source frame's duration.
For a nonlooping pingpong export, the final descending step is emitted once,
without adding the initial endpoint again.

```json
{
  "documentId": 3, "expectedRevision": 14,
  "path": "animations/walk.apng", "format": "apng",
  "tagId": 27, "scale": 4, "loop": true
}
```

The destination directory must already exist. The result reports `format`,
`loop`, output dimensions/scale, path/byte count, revision, and an ordered
`animationFrames` array. Each entry has source `frame`, `durationMs`, and
`encodedDurationMs`; repeated/pingpong steps are explicit in the array.

- **GIF:** the native encoder processes a detached flattened RGBA sprite and
  quantizes each frame to at most 256 colors (including transparency). Alpha below
  128 becomes transparent; alpha 128 or greater becomes opaque. No dithering is
  requested. GIF delay fields are centiseconds, so duration rounds **down** to
  the nearest 10 ms (`157 → 150`). Durations below 10 ms are refused with
  `UNSUPPORTED_TIMING`, avoiding viewer-dependent zero-delay playback. Use APNG
  for exact colors, partial alpha, or shorter timing. Viewers can still clamp
  very short GIF delays; encoded timing is not a playback-rate guarantee.
- **APNG:** native frame composites are encoded with the existing RGBA PNG
  encoder and assembled into full-canvas animation chunks. It preserves rendered
  RGBA bytes and exact 1–65,535 ms delays (denominator 1,000). Every frame uses
  SOURCE blending and NONE disposal, so transparent pixels replace older content
  rather than leaving ghost trails. No trimming, interlacing, or frame-delta
  optimization is performed. Viewers still decide actual playback scheduling.

Animation export limits: **1,048,576 output pixels per frame**, **8,388,608
output pixels summed across emitted steps**, and **32 MiB encoded-file bytes**.
All frames count toward the pixel budget, even repeated or blank frames. Reduce
frames or scale if refused. The native GIF encoder may briefly use a private
root-level `.libresprite-gif-*` scratch file; final publication remains atomic,
and failure cleans up scratch/publication files without touching the destination.

The editor/bridge open and thumbnail tools still accept only native sprites
and ordinary `.png` assets. `.gif`/`.apng` exports are not listed or opened by
those tools yet; inspect the source with contact/onion previews and view exported
animations in a compatible image/browser viewer. APNG round-trip editing is not
supported—save `.ase` to retain the editable sprite.

## Manual editing, disconnects, and safety

- **Pause before editing manually.** Native pause blocks agent operations; it
  does not disable your mouse/keyboard or lock the document against you. There
  is a dedicated AI Pause/Resume control in bridge-enabled editor status bars;
  local pauses cannot be remotely overridden. Disconnect also pauses operations.
- Mutations target only the **active GUI document**, with explicit document,
  layer, and frame identifiers. The bridge never silently switches documents
  for an edit. Create/open visibly select the new document.
  `activate_document` is the explicit, guarded exception for switching tabs;
  focus and closing still require the active document.
- An edit, save, export, undo, or redo requires the latest revision. Revisions are
  derived from metadata, native history, actual image bytes, and selection bitmap
  bits/visibility. A manual edit
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
- At most a 1024×1024 canvas, 1,048,576 preview/export pixels per image, 256 source
  frames, 128 tags, 256 palette keyframes, 128 layers **including nested
  groups/children**, 32 open documents, and 32 MiB of image working data / input
  file size. Animated export has a separate 8,388,608-total-pixel/32-MiB budget.
- Pixel batches: 1–16,384 pixels, transparent RGBA (`set_pixels`) or indexed
  (`set_indexed_pixels`) image layers; indexed painting supplies exact indices.
  Background/locked layers and linked/shared-image cels are refused. Colors
  replace pixels, duplicates use the last supplied color, and selection masks
  are ignored unless `respectSelection: true` explicitly enables them.
- Canvas edits require transparent layers; destructive crop requires explicit
  permission to discard bounds and refuses hidden selections/cross-layer aliases.
  Bitmap brush footprints are ≤32×32, binary mask strings ≤262,144 pixels,
  and brush/polygon work is bounded to 8,388,608 visits/tests.
- Palette index remapping, color-mode conversion, pressure/smoothed brush engines,
  image scaling, merge/flatten, packed/trimmed sprite sheets, animated-asset browsing, and APNG
  editing/round-trip are not exposed yet. Native `.ase`, full-canvas PNG sheets,
  GIF, and lossless RGBA APNG exports are supported.
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
All ten layer/frame/drawing mutations are checked against session/pause/revision gates, and
an oversized frame copy must roll back its data, saved state, and selection.
Linked-cel and background restrictions have explicit regression cases too.
`scripts/bridge_preview_cases.py` adds directory pagination/limits/escapes,
detached asset loading, pixel-exact sheet tiles and padding, native ghost
colors/opacity/layer filtering/clipping, PNG/sheet publication, and unchanged
selection/revision/saved state/history across read-only operations and exports.
`scripts/bridge_metadata_cases.py` covers sparse palette keys and removal,
repeated undo/redo, indexed/hidden-group index safety, tag IDs/properties/limits,
GIF alpha/quantized timing, and APNG full-canvas pixels/chunks/delays/order/loops.
`scripts/animation_checks.py` decodes exported animations independently of
LibreSprite. The Python suite also compiles the GUI-independent APNG assembler
with a C++17 compiler and zlib and tests malformed input, multi-IDAT PNGs,
frame/duration/dimension limits, and the encoded-byte ceiling without a GUI.
`scripts/bridge_selection_cases.py` adds nonsquare whole-cel transform pixel
checks in all three color modes, signed/off-canvas positions and opacity,
explicit unlink/undo/rollback, bitmap combinations and saved-state-preserving
selection undo, selection-aware drawing/fill barriers, overlap-safe pixel+mask
moves/copies, transparent replacement, all new mutation safety gates, and
pre-allocation patch/preview limits.
`scripts/bridge_navigation_cases.py` covers explicit switching/previous-active
guards, atomic frame/layer validation, hidden/locked/group review focus,
pixel/mask/history/revision preservation, saved-only closing, replay/reopen, and
unchanged saved files/other documents. The manual user-pause test is described in
[testing-v0.6.md](testing-v0.6.md), with a real MCP demo that holds a connection
for testing the button and refuses to override a local pause.
`scripts/bridge_animation_cases.py` covers raw cel copying, frame ranges/tags/
timing/link identities, atomic batches and selected-mask transforms, including
undo after layer recreation. `scripts/bridge_editing_cases.py` adds exact all-mode
canvas preserve/crop/mask/link restoration, independent subtree copies,
ID-preserving reparenting after folder recreation, blends, polygon/bitmap masks,
custom brush replacement/selection/erasure/clipping, indexed palettes/raw bytes/
save/reopen, and prevalidated work/memory/lock/cycle refusals. Focused flags are
`--navigation-only`, `--animation-only`, and `--editing-only`; real MCP demos and
manual checklists are available for [step 2](testing-v0.7.md) and
[step 3](testing-v0.8.md).
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
directory. It also exports a frame and sheet, compares sheet preview/export bytes,
previews the saved asset without opening a tab, and writes an onion-skin PNG.
It adds editable swatches and a native tag, exercises tag undo/redo, and exports
looping GIF/APNG files plus separate demo-owned metadata JSON files. The demo
saves returned metadata as its own separate sidecars (not an atomic bundle).
It also copies selected sparkle pixels with pixel+mask undo/redo, writes
`mushroom-selection.png` feedback, fills selected pixels, transforms a cel, and
updates another cel's opacity before the exact native save/reopen check.
Agent editing is paused at the end; you can still use LibreSprite's
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

Directory browsing, detached loading, native onion options, sheet assembly, and
PNG encoding reuse the same native operation path. Document previews and exports
hold `DocumentReader` on the UI thread; export validates the revision under that
lock without opening an undo transaction or marking the document saved. The
shared PNG encoder uses nearest-neighbor sampling; sheet tiles include native
compositing rather than copying raw cels. Asset previews never register their
temporary documents or create persistent revision records.

Palette and tag changes reuse native undo commands, not arbitrary scripting.
`SetPalette` is used only at an exact keyframe; `AddPalette` handles inherited
colors so earlier frames are not changed silently. Two upstream palette command
fixes rewind the snapshot's input stream on add/redo and explicitly restore
palette removal on undo rather than virtually redispatching removal again.
GIF export uses a detached flattened sprite and explicit noninteractive GIF
options; its native codec doesn't see or mutate the editor's document settings.
The APNG assembler in `app/automation/apng.*` is GUI-independent and reuses native
PNG image data rather than adding a separate image compression dependency.

Cel position/opacity and unlinking use native `SetCelPosition`, `SetCelOpacity`,
and `UnlinkCel` commands. Whole-image transforms prepare an independent image
off-document and reuse `ReplaceImage` for native undo/redo. Selection masks use
`SetMask` in `DoesntModifyDocument` transactions; selected pixel translations
prepare a stable off-document snapshot and commit `PatchCel` plus `SetMask` in
one transaction. Before `PatchCel` can crop/grow a far-away cel, its union image
and total image working data are checked to avoid an unbounded intermediate
allocation. A failed operation restores retained hidden mask/visibility and
transformation state, in addition to the active layer/frame.

Two upstream fixes from the layer/frame milestone remain in this build:

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

On the development Apple Silicon Mac, the native build, fourteen Python helper/metadata
tests, nine TypeScript/MCP tests, the baseline CLI smoke test, and the real GUI
bridge test pass. The visible four-frame mushroom animation demonstration also
passed end to end through MCP stdio, including grouped layers, independent cels,
pixel-identical previews before undo/after redo, and exact frames/timing after a
native save/reopen. Asset/preview/PNG tools also pass the real MCP demo, including
byte-identical contact-sheet/export PNGs, detached thumbnails, and native onion
previews while paused. Palette/tag/GIF/APNG tools pass expanded real-GUI and
real-MCP tests; independent decoding of both animated demo exports confirms
all four frames are pixel-exact with expected timing/looping. Cel/selection
operations pass expanded disposable-GUI regressions and the real MCP animation
demo, including copied pixels and mask undo/redo, cel transforms/opacity, native
save/reopen, and unchanged pause/session/revision safeguards. Direct chat-tool
launch/connect/create/draw/render/undo/redo/save/export is also verified in a
separate agent-owned paused window, with an independently pixel-checked export.
Linux support is
implemented but has not been tested here.
