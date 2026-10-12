# Animation correction / v0.11.0 review

This milestone adds **explicit, atomic corrections**, not automatic motion
generation: multi-frame/layer RGBA/indexed pixel edits and per-frame masked-region
moves/copies. Read [correction semantics](animation-correction.md) before editing.
Native-CI/Linux work, package rebuilding and personal artwork edits are out of scope.
The approved v0.9.0 package and already-running editor windows are unchanged.

## Separate generated review editor

```sh
npm run build
bash scripts/build-libresprite.sh
node scripts/demo-correction.mjs
```

The demo starts a **new** visible editor with a unique private socket/asset root.
It generates a three-frame arrow, deliberately adds stray orange pixels and
vertical jitter, then applies two named correction batches over real MCP. The
source/destination pixels are explicit; the demo does not infer motion. It saves
independent `correction-arrow-before.ase` and `correction-arrow-after.ase`, PNG
contact sheets and JSON change summaries under `.runtime/correction-…/`. It checks
dry runs, no-ops, Undo/Redo and preserved hidden content, then pauses/disconnects
and leaves that editor open. `review.json` records fresh IDs and endpoint paths.

## Review

1. Confirm this new editor says paused/waiting and all existing artwork/windows
   are untouched. Scrub/play the generated three-frame pingpong animation.
2. Compare `before-contact.png`, `pixels-contact.png` and `after-contact.png`:
   the first correction removes stray orange pixels and lightens arrow tips on
   all three frames; the second aligns only frames 1 and 2 vertically. The
   unrelated backdrop remains identical.
3. Inspect `pixel-dry-run.json`/`pixel-applied.json`: predicted/applied changes
   match, with six raw changed pixels across three cels. Inspect the region JSON:
   only two cels are changed, using distinct per-frame offsets and explicit masks.
   Counts are raw cel changes, not artistic-quality scores or tracked landmarks.
4. Before manually editing anything, use native **Undo once**: both corrected
   regions return together to the pixel-cleaned state (`undo-regions-contact.png`).
   **Undo again**: all pixel cleanup returns together to the original state
   (`undo-both-contact.png`). **Redo twice** returns the corrected animation.
   Save paths remain independent; Undo does not rewrite files on disk.
5. Compare `hidden-before.png`/`hidden-after.png` and `mask-before.png`/
   `mask-after.png`: they are identical. The sparse GUI selection deliberately
   lies outside the edited pixels and must remain unchanged. Focus stays on the
   backdrop/frame 1; timing `[90,120,100]`, tag and palettes remain unchanged.
6. Test on generated sprites only. Refresh the source MCP catalog for **64 tools**;
   existing editors have older bridges. Connect only to the review endpoint,
   inspect fresh IDs/revision and explicitly resume before agent edits. Pause
   before manual work; local editor Pause cannot be remotely overridden.

## Automated regression

```sh
npm test
python3 -m unittest discover -s tests -v
python3 scripts/smoke-test-libresprite.py
python3 scripts/test-live-bridge.py --correction-only
python3 scripts/test-live-bridge.py
node scripts/demo-correction.mjs
```

Disposable GUI tests independently decode every affected PNG/native cel. Coverage
includes last-wins duplicates, missing cels, sparse holes/selected transparency,
overlapping moves/copies, RGBA/indexed/grayscale raw values, off-canvas pixels,
cel opacity/user data, native one-step repeated Undo/Redo, unchanged/dry-run save
and redo preservation, invalid later entries, stale/session/pause/inactive guards,
locked ancestors/background/linked refusals, explicit unlink, palette validation,
nonzero transparent-index erasure, total-input/target ceilings, exact change
counts/bounds, aggregate scratch/growth and far-offset bounds. Unit tests compile
the native mask/translation helper and compare randomized sparse operations independently.
