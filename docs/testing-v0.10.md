# Animation inspection / v0.10.0 review

This milestone adds only **read-only** frame differences, isolated previews and
loop/timing diagnostics. Animation correction and native-CI/Linux work are not
included. The approved v0.9.0 package and existing editor windows are unchanged.

## Separate generated review editor

```sh
npm run build
bash scripts/build-libresprite.sh
node scripts/demo-inspection.mjs
```

The demo starts a **new** visible editor with a unique private socket/asset root.
It generates a moving pixel-art arrow over a backdrop, a hidden study layer,
three deliberately uneven frame durations and a pingpong tag. It saves only its
own generated sprite and PNG/JSON review outputs under `.runtime/inspection-…/`.
It then pauses and disconnects, leaving its editor open with no background edits.
`review.json` records the fresh process/socket/asset/document/layer/tag IDs.

## Review

1. Confirm the new editor says paused/waiting and all existing windows/artwork
   are untouched. Scrub its three frames and play the tagged animation manually.
2. Open `composite.png` and `isolated.png`: the latter contains the arrow only,
   on transparency, without its unrelated backdrop. Check `hidden-study.png`:
   it shows hidden content while the layer remains hidden in the editor.
3. Open `frame-diff.png`: green is added, red removed, yellow modified; unchanged
   pixels are transparent. `scoped-diff.png` compares only the arrow group.
   Inspect the corresponding JSON for exact unscaled counts/bounds.
4. Open `scoped-contact.png` and its JSON: frames `[2,0,1]` should be in that order,
   with returned rectangles/durations matching each tile.
5. Inspect `animation-analysis.json`: pingpong order is `[0,1,2,1]`, cumulative
   time matches each exposure, and loop closure is frame 1 → 0. GIF warns about
   the intentionally sub-10ms frame and rounded millisecond duration. These are
   measurements, not automatic corrections or quality scores.
6. Before manually changing anything, reconnect to this **demo's** endpoint if
   desired, leave it paused, and repeat inspection calls. Revision, mask, selected
   frame/layer, visibility, saved state and undo/redo must remain unchanged.
   Finish manual playback/drawing/dialogs before bridge inspection.

Native updates require a new editor; refresh the MCP server/catalog for **62 tools**.
Do not discard unsaved work to upgrade. IDs are local to this editor session.
The demo never connects to working artwork or another editor's endpoint.

## Automated regression

```sh
npm test
python3 -m unittest discover -s tests -v
python3 scripts/smoke-test-libresprite.py
python3 scripts/test-live-bridge.py --inspection-only
python3 scripts/test-live-bridge.py
```

Tests use disposable generated sprites and independently decoded PNG comparisons.
They cover color/alpha classifications, native indexed/grayscale/blends/backgrounds,
hidden ancestors/subtrees, paused/inactive reads, single/repeated/tagged playback,
510-step pingpong expansion, GIF timing, resource limits and preserved save/mask/redo
state. The full suite also checks the pre-existing native editing/Undo/export tools.
