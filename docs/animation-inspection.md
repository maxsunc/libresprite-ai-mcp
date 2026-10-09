# Read-only animation inspection — v0.10.0

Inspection helps an agent measure and review motion; it does not animate or
correct artwork automatically. All inspection requests use native rendering under
the document read lock, include the current revision/session, and work while the
bridge is paused or the sprite is inactive. Finish GUI drawing, transforms,
playback and modal dialogs first. No pixels, visibility flags, selected frame/layer,
mask, preferences, saved state, files or undo/redo history are changed.

Rebuild the native editor and TypeScript server, then use a **new** development
window and refreshed MCP catalog. Existing editors and the approved local v0.9.0
package retain their old feature set; do not restart or replace unsaved artwork.

## Frame differences

Call `libresprite_render_frame_diff` with `documentId`, `fromFrame`, `toFrame`,
and optional nearest-neighbor `scale` (1–16, default 1). Frames are zero-based.
For example:

```json
{ "documentId": 1, "fromFrame": 0, "toFrame": 1, "scale": 4 }
```

The returned PNG is transparent except at changed canvas coordinates:

| Category | Meaning | RGBA highlight |
| --- | --- | --- |
| Added | Alpha zero → nonzero | `[40,200,90,255]` (green) |
| Removed | Alpha nonzero → zero | `[240,70,70,255]` (red) |
| Modified | Both visible, different RGB and/or alpha | `[255,200,40,255]` (yellow) |
| Unchanged | Equal RGBA, or both fully transparent | Transparent |

`schema: libresprite-frame-diff-v1` identifies the result. `difference` includes
category counts, `changedPixels`, `unchangedPixels`, `totalPixels`,
`changedFraction` (changed / canvas pixels), and a minimal changed `bounds`
rectangle. Bounds are `{x,y,width,height}` in **unscaled source-canvas pixels**,
or null for no changes. Each of `before`/`after` reports `visiblePixels`, minimal
nonzero-alpha bounds, and the arithmetic `centroid` of occupied pixel coordinates.
Blank frames have null bounds/centroids. Centroids are not tracked landmarks or
alpha-weighted centers of mass.

Differences compare the native **rendered RGBA composite**, not raw cel data.
Visibility, blend modes, cel/layer opacity and frame palettes therefore matter;
hidden changes and off-canvas pixels are not detected. RGB underneath alpha zero
is ignored. Any nonzero alpha counts as occupied. There is no tolerance or
registration/alignment; a one-pixel translation produces removed and added pixels.
Identical and same-frame comparisons produce an empty PNG. PNG scale affects only
the preview, not measurements; output is capped at 1,048,576 pixels.

Compare visible poses with `libresprite_render`, then use the diff to locate
changes. A large difference can be an intentional action pose, not an error.

## Isolated layer/group previews

Call `libresprite_render_layer` with `documentId`, an explicit `layerId`, `frame`,
and optional `scale`/`includeHidden`:

```json
{ "documentId": 1, "layerId": 8, "frame": 2, "scale": 4, "includeHidden": false }
```

This returns a full-canvas PNG containing **only** that image layer or group
subtree on transparency, plus `schema: libresprite-layer-preview-v1`, frame timing
and `analysis` (visible pixel count, bounds, occupancy centroid). Native cel
coordinates, opacity, blends, palette and subtree order are retained; off-canvas
data is clipped only in the preview. Blends are evaluated against the transparent
canvas/selected subtree, **not excluded backdrop layers**, so an isolated layer can
look different from its contribution to the complete sprite.

Default visibility includes ancestor checks: a hidden parent makes a child preview
blank, and hidden descendants are omitted. Explicit `includeHidden: true` ignores
visibility for the selected subtree, including hidden descendants, without
changing any live flags or global preferences. Locked content can be inspected.
Missing cels/empty groups produce transparent images; missing IDs are errors.

`libresprite_render_frame_diff` and `libresprite_contact_sheet` also accept optional
`layerId` and `includeHidden` with exactly these semantics. `includeHidden: true`
requires `layerId`; it never means "show every hidden layer in the whole sprite."
Both results identify their scope with `layerId` (null for the full composite)
and `includeHidden`. Existing unscoped behavior and exports are unchanged. Contact
sheet rectangles, zero-based source frames and durations label each tile in its
returned manifest; no font/text is painted onto the pixel-art preview.

## Verification

```sh
npm test
python3 -m unittest discover -s tests -v
bash scripts/build-libresprite.sh
python3 scripts/test-live-bridge.py --inspection-only
```

The focused suite launches and terminates only its own disposable editor with
generated fixtures. It independently decodes PNGs and checks classifications,
scaling, empty/reversed comparisons, input/output bounds and read-only state
preservation, including a live redo branch. It never attaches to existing editors
or opens personal artwork. Animation correction is a separate future milestone.
