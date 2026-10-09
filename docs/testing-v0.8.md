# Step 3 / v0.8.0 manual review

Steps 1, 2, and 3 were user-approved. This milestone adds canvas resize/crop,
independent layer/group copies, reparenting/native blends, polygon/bitmap masks,
custom bitmap brushes, and exact indexed-color painting. This checklist remains
available for regression review. **Packaging was also user-tested and approved
on 2026-10-09; the separate native-CI/Linux milestone was skipped at user request.**

## Separate review editor

```sh
npm run build
bash scripts/build-libresprite.sh
node scripts/demo-editing.mjs
```

The demo uses the real MCP server to launch a **new** editor on a private
`.runtime/edit-…/` socket/asset root. It creates two original generated crystal
sprites (RGBA and indexed), not working project artwork, and exercises every
new tool. It leaves earlier windows and artwork alone. Test editors still use
ordinary LibreSprite preferences/recovery locations; personal MCP configuration
is not changed.

The RGBA sprite has three independent frames, nested scene/crystal layers,
screen-blended highlights, custom star brushes, a hidden independent subtree
copy, and sparse bitmap selection. A lossless resize adds a margin, then the
final crop removes that margin, its gold stars on all frames, and outside mask
bits. The demo first verifies refusal without explicit discard authorization.

Saved files include `rgba-before-crop.ase`, `rgba-after-crop.ase`,
`indexed-crystal.ase`, before/after PNGs, `rgba-contact.png`, `rgba-review.gif`,
and `indexed-crystal.png`. These are private generated review assets. The demo
stays connected/paused and only monitors status; it makes **no further document
edits or navigation** even when resumed. Ctrl+C disconnects but leaves the GUI open.

## Try it

1. Leave the agent paused. On the RGBA tab, scrub/play its three frames and inspect
   the layer hierarchy. The canvas starts at **48×48** after the crop.
2. **Undo once**: the canvas returns to **64×56**; gold stars reappear at the left
   on all three frames, and the full sparse selection returns. This is one native
   transaction, not one Undo per cel/layer/frame. The crop didn't scale the icon.
3. **Redo once**: returns to 48×48 and the clipped selection. Repeat while scrubbing.
   The saved before-crop file is unchanged; native Undo affects the document,
   not already-exported files. Export images do not burn in the selection overlay.
4. Inspect the hidden independent study group: toggle visibility manually, or
   paint on a copied image cel, and verify the original crystal is unchanged.
   Copies include all frames, but are deliberately unlinked.
5. Inspect screen blend/opacity on the highlight layer; change them manually and
   test native undo. Reparented crystal layers remain inside Scene, with normal
   editable image-layer children.
6. Switch to the indexed tab. Its eight swatches and transparent index0 are exact
   indices, not a quantized RGBA sprite. Paint a small mark and test native undo.
7. Test the AI Pause/Resume control. A local pause must still refuse remote resume.

## Optional tool review

Refresh/restart the MCP server/catalog for **59 tools**, and launch a new v0.8.0
editor; old windows retain their previous native bridge. Don't discard unsaved
work to upgrade. The review monitor owns its socket until disconnected; its
`review.json` records the paths/IDs for a separate connection afterwards.

- Resize smaller, then larger, without offsets. All off-canvas pixels return.
  Explicit offsets shift all frames and full mask together, without scaling.
- Crop without `discardOutside:true` when any cel or mask bounds lie outside.
  It must refuse with `WOULD_DISCARD_PIXELS` and change nothing.
- Duplicate a group subtree; copied flags, raw pixels, opacity/blends/user data
  are retained. Every cel is independent, including a linked source.
- Move a group into a descendant: `LAYER_CYCLE`. Locked/movement-locked targets
  and locked destination ancestors refuse; no automatic unlock or background
  conversion occurs.
- Apply polygon/sparse binary masks and use `render_selection` to verify holes.
  Selection-only changes must preserve saved/modified state and Undo normally.
- Paint with a bitmap brush (1..32 footprint), custom anchor, or exact palette
  index. Clipping needs `clipToCanvas:true`; `respectSelection:true` needs a visible
  mask. RGBA/indexed colors replace, not blend/remap; transparent erases.
- Submit a valid indexed pixel followed by an invalid palette index. No partial
  painting is permitted; identical requests consume no history.

## Verification

```sh
npm test
python3 -m unittest discover -s tests -v
python3 scripts/smoke-test-libresprite.py
python3 scripts/test-live-bridge.py --editing-only
python3 scripts/test-live-bridge.py
```

The focused suite checks raw RGBA/indexed/grayscale canvas bytes, linked shifts/
crops/removals, mask restore, loss/lock/background/native-range refusals, independent
subtree properties, cycle-safe ID-preserving reparenting and Undo after folder
reconstruction, native blends, mask geometry/combinations, exact brush replacement/
erasure/selection/anchors/clipping, indexed palette keys/save/reopen and work limits.
It uses only a disposable generated editor and saves/closes only its own documents.

## Deliberate limits

Canvas edits require transparent layers; crop refuses retained hidden masks and
cross-layer image/data aliases instead of silently unlinking. No image scaling,
automatic trim-to-content, merge/flatten, group opacity/blend controls, color-mode
conversion/remapping, pressure/smoothing, or general multi-frame brush painting is
added. Indexed painting is explicit pixels/bitmap brushes; older RGBA-only shape/
fill/selected-region transform tools keep their original restrictions. See the
[exact operation semantics](live-bridge.md) before touching important artwork.
