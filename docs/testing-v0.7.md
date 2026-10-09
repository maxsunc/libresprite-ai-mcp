# Step 2 / v0.7.0 manual review

Step 1 was approved. This milestone adds independent cel copies, frame-range
duplication/reordering, atomic cel/timing batches, and selected-region transforms.
**Stop after this review; subsequent editing/packaging/platform milestones need
separate approval.**

## Separate test editor

```sh
npm run build
bash scripts/build-libresprite.sh
node scripts/demo-animation.mjs
```

The real MCP demo launches a **new** editor using a private `.runtime/anim-…/`
socket/asset root. It generates a five-frame blue-arrow animation, gold accents,
and a hidden cross-layer copy-test layer. It exercises all six new tools and
saves independent `before-batch.ase`, `after-batch.ase`, `review.gif`, and
`review-contact.png` files. It never opens your working artwork or attaches to
existing windows. Development windows still use ordinary LibreSprite preferences
and recovery locations; personal MCP configuration remains unchanged.

The final native undo step changes position/opacity of **six cels across three
frames**, not six separate undo steps. After setup the demo is connected/paused
and only monitors status. It makes **no further sprite/navigation changes**.

## Try it

1. Keep the agent paused. Scrub all five frames and play the animation. Durations
   are 90/140/110/180/220 ms. Alternating arrow direction shows selected flips.
2. Use native **Undo once**: the entire final multi-frame motion/opacity batch
   should disappear at once; all five frames/layers should still exist.
3. **Redo once** restores the motion/opacity batch. Repeat while scrubbing to check
   other frames. `before-batch.ase` remains an unchanged earlier version.
4. Paint a small test mark and check native undo/redo still works normally.
5. Test status-bar Resume/Pause. A local pause must still refuse remote resume;
   the demo reports that refusal. The monitor never paints even when enabled.
6. View the GIF/contact export if useful; these are generated test assets, not
   project artwork. Ctrl+C disconnects/pauses but leaves your test GUI open.

## Optional chat/tool review

Refresh the MCP server/catalog and connect to a **new v0.7.0 test editor** to use
the 51-tool catalog. Old editors retain their older bridge. Do not discard unsaved
originals to upgrade. The demo owns its separate socket connection until Ctrl+C;
its printed `review.json` records the root/socket/document IDs for a separate
review connection after the monitor disconnects.

- Copy a source cel to an existing empty layer/frame. It should be independent;
  edit the copy and confirm the original is unchanged. Replacing an existing cel
  requires `overwrite: true`. No system clipboard or cross-document copy yet.
- Duplicate frames `[2,0]` at index 1. Source indices are pre-edit; inserted
  order/timing should match frame 2 then frame 0, with one undo step.
- Reorder using a full old-index permutation. Pose durations should move with
  poses, and links remain intact. A permutation that splits a tag refuses with
  `TAG_SPLIT` instead of silently changing its membership.
- Submit a multi-cel edit with a valid first target and invalid later target.
  It should change **nothing**. A valid batch should be one undo step.
- Select a nonsquare region, rotate it on explicit frames, and check that its
  top-left stays fixed and the mask rotates too. Undo restores all affected
  frames and the mask together. A rotation leaving the canvas must refuse;
  absent/hidden selections must never fall back to whole-cel edits.

## Automated checks

```sh
npm test
python3 -m unittest discover -s tests -v
python3 scripts/smoke-test-libresprite.py
python3 scripts/test-live-bridge.py --animation-only
python3 scripts/test-live-bridge.py
```

The focused suite checks exact rendered/native cel bytes, off-canvas/index/gray
data, opacity/user data, independent copies, native background/nested/link
handling, tags/timing, sparse masks/transparent overlap, no-op/validation guards,
single-step repeated undo/redo, palette/limit refusal, save/reopen, and preservation
after native layer deletion/restoration. It saves/closes only its own disposable
generated documents and never attaches to the user editor.
Native revision-helper unit tests also cover the background recovery writer's
initial 0→1 version bookkeeping without suppressing real property or higher-version
changes. Raw inspection version telemetry can change during recovery even when
the document's persistent state and revision remain unchanged.
