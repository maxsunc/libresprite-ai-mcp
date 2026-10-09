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

## Loop and timing diagnostics

Call `libresprite_analyze_animation` with `documentId` and optional:

- `tagId`: expand a native tag's forward/reverse/pingpong playback order.
- **Or** `frames`: 1–256 ordered zero-based indices; repeats/holds are allowed.
- Neither: all sprite frames in forward order.
- `loop`: true (default) includes the closing last-playback-step → first-step
  comparison; false reports only internal transitions.
- `layerId`/`includeHidden`: the same isolated-rendering scope as above.

```json
{ "documentId": 1, "tagId": 20, "layerId": 8, "loop": true }
```

The JSON-only result has `schema: libresprite-animation-analysis-v1`:

- `steps`: exposure order with `step`, source `frame`, `durationMs`, inclusive
  `startMs`/exclusive `endMs`, and floored `gifDurationMs`. Pingpong does not
  duplicate endpoints; a 256-frame tag has at most 510 playback steps.
- `timing`: step count, total/min/max durations, uniform-duration flag and
  `effectiveFps` (1000 × step count / total milliseconds, not a fixed playback FPS).
- `frames`: one entry per unique source frame, in first-appearance order, with
  duration, nonzero-alpha pixel count, bounds and occupancy centroid.
- `transitions`: consecutive **playback steps**, with source-frame/step IDs,
  `closing` flag and the same exact `difference` measurements as frame diffs.
- `loopBoundary`: the closing transition, or null when `loop: false`.
- `transitionSummary`: internal change mean/max, identical transition count
  (including closure when enabled), closing change count, and closing/internal-mean
  ratio. Undefined means/ratios are null, not Infinity or fabricated zero.
- `gif`: native GIF timing exportability and predicted total encoded duration/loss.
  Delays below 10ms make exportability false and encoded totals null. Otherwise each
  delay is floored to 10ms units. `warnings` identifies affected playback steps:
  `GIF_DELAY_TOO_SHORT` or `GIF_DELAY_QUANTIZED`. This measures timing only, not
  palette quantization, binary-alpha loss, or all export size/path constraints.

A one-frame loop has one zero-change closing comparison; a one-frame non-loop has
no comparisons. Duplicate poses are reported as identical even when their source
indices differ. Tag loops compare the last **expanded playback step**, not blindly
the tag's numeric last frame. Different endpoints are normal in moving cycles;
neither a nonzero boundary difference nor uneven timing is a quality verdict.
Centroid changes are occupancy measurements, not identified feet/joints/motion.

Analysis is capped at 8,388,608 aggregate source-canvas pixels over **unique source
frame analyses + unique directed frame-pair comparisons**. Both are cached, so a
repeated frame sequence does not repeatedly render or scan the same pair. Oversized
requests fail before allocating previews; choose fewer frames or a smaller canvas.
The result reports `analyzedPixels`. Scope isolation does not reduce canvas size;
large blank/hidden sprites still count toward the bound. No scaling/downsampling is
used for diagnostics, and no output file is published.

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

For a visible, generated real-MCP demo and manual review, see
[the v0.10.0 checklist](testing-v0.10.md).
