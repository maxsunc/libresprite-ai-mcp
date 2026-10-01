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
| `libresprite_undo` / `libresprite_redo` | One native undo transaction |
| `libresprite_save` | Atomic native-file save inside the root |

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
- At most 1,048,576 canvas/preview pixels, 256 frames, 128 layers, 32 open
  documents, and 32 MiB of image working data / input file size.
- Pixel batches: 1–16,384 pixels, transparent **RGBA image layers only**.
  Background/locked layers and linked cels are refused. Colors replace pixels,
  duplicates use the last supplied color, and selection masks are not applied.
- Existing layers/frames/palettes/tags can be inspected and rendered, but tools
  to create/manage them are not yet implemented. No brush/stroke/fill APIs,
  asset browser, contact sheets, onion-skin previews, or animation export yet.
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
deduplication, pause/reconnect, and path boundaries. Do not interact with that
test window while it runs. The tests do not establish cross-platform GUI
correctness or unlimited hostile-input resilience.

For a small end-to-end MCP demonstration that leaves its own editor open:

```sh
node scripts/demo-live.mjs
```

It uses the real MCP stdio protocol, creates a new demo sprite, draws it in
several visible batches, exercises undo/redo, saves it, and returns a rendered
PNG under `.runtime/`. It pauses the editor before disconnecting. Each run uses
a distinct socket and asset directory; it never changes another window.

## Native implementation notes

The app starts `app/automation/bridge.cpp` only with `--automation-socket` and
`--automation-root`. A native 16 ms UI timer performs bounded nonblocking socket
I/O and processes at most one request per tick. Short pixel batches are built
off-document, validated in full, then applied under `ContextWriter` using
`Transaction`, `PatchCel`, and `AddCel`. The existing renderer composites
frames; enlarged previews use nearest-neighbor copying into a PNG surface.

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
tests, eight TypeScript/MCP tests, the baseline CLI smoke test, and the real GUI
bridge test pass. The visible mushroom demonstration also passed end to end
through MCP stdio, including pixel-identical previews before undo/after redo
and a native save. Linux support is implemented but has not been tested here.
