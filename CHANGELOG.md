# Development milestones

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
