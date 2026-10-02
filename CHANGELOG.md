# Development milestones

## 0.4.0 — Palettes, animation tags, and GIF/APNG export

- 34 MCP tools: added sparse palette editing/resizing, palette-keyframe removal,
  animation-tag creation/atomic properties/deletion, and GIF/APNG export.
- Palette edits use exact frame keys; changed inherited colors create a keyframe
  without changing earlier frames. Indexed shrink/removal validates all affected
  cel indices, including hidden nested/off-canvas pixels. Identical palette/tag
  requests preserve history; grayscale palette edits remain unsupported.
- Inspection reports tag IDs; tags preserve native frame-range maintenance and
  undo/redo. Export can expand forward/reverse/pingpong tags or ordered frames.
- GIF uses the native encoder on a detached rendered sprite, with binary alpha,
  native palette quantization, and reported centisecond timing. APNG uses native
  RGBA PNG frames and a GUI-independent chunk assembler for lossless color/alpha
  and exact millisecond delays. Both publish one file atomically, guard active
  document/session/revision/pause, and preserve document and preference state.
- Fixes upstream palette snapshot rewind on redo and removal undo redispatch.
- Adds independent GIF/APNG decoding checks, native APNG malformed-input/limit
  tests, and expanded disposable-GUI/real-MCP animated-export demos.

## 0.3.0 — Asset browsing, animation previews, and PNG export

- 28 MCP tools: added root-restricted directory browsing, detached asset
  thumbnails, contact sheets, native onion-skin previews, PNG frame export,
  and PNG sprite-sheet export.
- Read-only previews work while paused, leave GUI documents/selection/preferences
  unchanged, and support inactive documents. Asset thumbnails do not open tabs
  or return misleading temporary document IDs/revisions.
- Sheets have ordered/subset frames, transparent padding, nearest-neighbor
  scaling, and a returned `libresprite-sheet-v1` layout/timing manifest.
- Export one PNG per request with atomic publication, no-overwrite by default,
  explicit active-document/session/revision/pause checks, and no saved-state or
  history changes. Sheet metadata is returned, not published as a second file.
- Adds native GUI pixel/metadata/path/limit regressions and extends the real MCP
  animation demo with browsing, thumbnails, contact/onion previews, and exports.

## 0.2.0 — Layers, frames, and drawing

- 22 MCP tools: added image layers/groups, atomic properties, sibling restacking,
  guarded subtree removal, blank/independent frame insertion, frame deletion and
  timing, native shapes, connected one-pixel strokes, and flood filling.
- Reports native version/capabilities and active layer/frame selection.
- Drawing no-ops preserve undo history; oversized transaction data rolls back.
- Preserves native tag-range adjustments and refuses unsafe per-frame palette
  structural edits rather than silently corrupting them.
- Fixes upstream index-zero duration access and nested layer/cel traversal.
- Makes timeline rendering, brush previews, and deletion selection safe for groups;
  refuses painting directly into a group and honors native auto-show-timeline
  preferences when adding layers/frames.
- Adds grouped animation save/reopen regressions and a visible MCP animation demo.

## 0.1.0 — First live editing slice

- Pinned complete LibreSprite v1.2 source and reproducible Apple Silicon build.
- Opt-in private Unix socket; native operations on the UI thread.
- MCP stdio server: create/open/inspect/render, atomic pixel edits, undo/redo,
  native save, pause/reconnect, session/revision and asset-root protections.
- Pixel-exact baseline/real-GUI tests and a visible mushroom demonstration.
