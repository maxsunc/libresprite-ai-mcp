# Pixel regions / v0.12.0 review

This milestone adds exact raw-cel reads, read-only bitmap/component extraction,
and atomic native-region/PNG stamping. Semantics and limits are in
[pixel regions](pixel-regions.md). No original artwork, existing editor windows,
approved packages, native CI/platform work or client configuration are changed.

```sh
npm test
python3 -m unittest discover -s tests -v
bash scripts/build-libresprite.sh
python3 scripts/test-live-bridge.py --pixels-only
python3 scripts/test-live-bridge.py --masks-only
python3 scripts/test-live-bridge.py --stamps-only
python3 scripts/test-live-bridge.py
node scripts/demo-pixel-regions.mjs
```

The GUI tests each start a NEW disposable editor and check independent native
fixture bytes/PNG pixels, read-only preservation and native Undo/Redo. They never
attach to another editor. `--pixels-only` exercises all three related features.
The real-MCP demo leaves its separate GENERATED sprite open, paused/disconnected,
with saved source/target sprites, before/after contacts, raw values, extracted
mask and dry-run/apply summaries under `.runtime/regions-…/`. `review.json` records
the endpoint, IDs and source hash. Refresh the MCP catalog for **67 tools** and
use fresh IDs/revisions. Old editors retain their old native bridge.

Review the generated demo:

1. Confirm it is paused and your existing editors/artwork are untouched.
2. Check `source-pixels.json`: complete row runs decode to the stored part's exact
   RGBA values, independent of visibility or palette rendering.
3. Check `source-mask.png`/JSON: the white component matches the intended part;
   the disconnected study pixel is excluded. The GUI selection remains elsewhere.
4. Compare `before-contact.png`/`after-contact.png`: the same source part is stamped
   onto three target frames at distinct positions; backdrop/source layers stay
   unchanged. Dry-run and applied counts/bounds must match.
5. Before manual edits, Undo ONCE removes all three stamps together; Redo ONCE
   restores them. Files on disk are not rewritten by Undo. Hidden/locked source
   flags, sparse GUI mask, focus, durations and tag must remain unchanged.
6. For asset tests, use generated PNGs only. Choose paste modes explicitly,
   preserve the returned source hash between dry run/apply when appropriate, and
   do not weaken color-mode/palette/clipping/linked guards to make a request fit.
