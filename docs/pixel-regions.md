# Exact native pixel regions — v0.12.0

## Read native pixels

`libresprite_read_pixels` requires `documentId`, `layerId`, zero-based `frame`,
and explicit `x`, `y`, `width`, `height`. This reads ONE image layer's cel, not
a composite or group. Hidden/locked/background/linked layers are readable.
No visibility, opacity, blend, palette conversion or alpha normalization is applied.
It works paused/inactive under the native read lock; finish GUI gestures/playback
and dialogs first. No selection/focus/history/preferences/saved state/files change.

Origins are signed native coordinates (-32768…32767), so off-canvas cel pixels
can be inspected. Dimensions are 1…1024; at most **16,384 samples per request**.
Outside an existing cel, or in a missing cel, samples are zero for RGBA/grayscale
and `transparentIndex` for indexed sprites. Backgrounds do not synthesize a fill:
these are storage reads, not displayed/rendered background colors.

```json
{ "documentId": 1, "layerId": 2, "frame": 0,
  "x": -1, "y": 2, "width": 4, "height": 2, "encoding": "runs" }
```

Results use `schema: libresprite-pixel-read-v1`, include current revision/session,
region/sample count, raw cel bounds/IDs/opacity (null for missing cel), layer opacity/
blend/background, and the effective indexed frame palette when relevant.

- `encoding: runs` (default): `rows[y]` is an array of `[length, value]` pairs.
  Every row reconstructs to exactly width samples; runs never cross rows.
- `encoding: values`: `rows[y][x]` is one unsigned native value.
- `packing: 0xAABBGGRR`: RGBA = `r + g*256 + b*65536 + a*16777216`.
- `packing: 0xAAVV`: grayscale-alpha = `value + alpha*256`.
- `packing: index`: exact index, not the palette's rendered RGBA.

Alpha-zero RGB/gray payloads remain exact. Palette colors use the same unsigned
RGBA packing. Visibility and cel/layer opacity affect rendered previews only;
use `libresprite_render_layer` separately to inspect appearance.

Rebuild the native editor/server and launch a NEW development window for updated
tools. Already-running editors and the approved v0.9.0 package are not replaced.

## Extract an explicit mask

`libresprite_extract_mask` uses the same required image layer/frame and rectangle,
but origins are in-canvas and the WHOLE rectangle must fit. At most **262,144
samples** are examined; clipping is refused. It never borrows or changes the GUI
selection. Raw hidden/locked/linked/background cels can be read while paused/inactive.

- `criterion: nontransparent` (default): stored RGBA/grayscale alpha must be at
  least `minAlpha` (1…255, default 1). Indexed pixels match when their stored index
  differs from `transparentIndex`, regardless of palette alpha. On an indexed
  background all stored cel pixels match. Indexed `minAlpha` other than 1 is refused.
- `criterion: value`: supply an unsigned packed `value` in the sprite's native
  range, with no `minAlpha`. Matching is exact, including alpha-zero payloads and
  transparent padding outside/missing cels. No palette conversion or tolerance.
- Optional absolute `seed: {x,y}` limits matches to that seed's component WITHIN
  the supplied rectangle. `connectivity` is 4 (default) or 8, and requires a seed.
  A seed outside the rectangle is refused; a nonmatching seed returns an empty mask.
- `preview: true` (default) adds an unscaled region-sized PNG: selected pixels
  white, others transparent. `preview: false` returns JSON only.

```json
{ "documentId": 1, "layerId": 2, "frame": 0,
  "x": 0, "y": 0, "width": 16, "height": 16,
  "criterion": "nontransparent", "seed": { "x": 4, "y": 8 }, "connectivity": 4 }
```

The returned `mask` is `{x,y,width,height,bits}` with full row-major binary text,
plus `selectedPixels` and minimal canvas-coordinate `bounds` (null if empty).
Nonempty masks can be passed directly to `translate_regions` or explicitly used
to set a GUI selection in a SEPARATE mutation. Empty masks have all-zero bits:
editing tools requiring nonempty masks will refuse them, not edit the whole cel.
No smoothing, filling holes, landmarks or implicit fallback is performed.

## Atomic region/PNG stamping

`libresprite_stamp_region` requires the active document/current revision, resumed
bridge and idle GUI/views. Supply explicit `source`, **required** `mode`, and
1…256 unique `edits: [{layerId,frame,x,y}]`. One changed batch is one native Undo
step, with all patches prepared before mutation. `dryRun: true` reports exact
counts/bounds/`wouldEditCels`, edits zero cels, and preserves revision/save/redo state.
Labels, change summaries and target guards match [animation correction](animation-correction.md).

Source shapes:

```json
{ "layerId": 2, "frame": 0, "x": -1, "y": 2, "width": 3, "height": 2 }
```

```json
{ "path": "parts/hand.png", "x": 0, "y": 0, "width": 8, "height": 8 }
```

Live sources are in the SAME sprite; signed origins can read off-canvas data and
include transparent padding outside the cropped cel. The source cel must exist
and intersect the source rectangle: missing sources are NOT an erase fallback.
Hidden/locked/linked/background sources are readable without changing their flags.
PNG paths must resolve inside the asset root; the full source rectangle must fit
the decoded PNG. Loading is detached (no tab/history/focus changes), using the
existing trusted native codecs and 32 MiB file/working bounds—not a hostile-file
sandbox. PNGs must decode to one layer/frame. External/cross-document/native-file
sources, arbitrary scripts, automatic conversion and resampling are not supported.

- `mode: replace`: copy every selected raw sample, including transparency and
  invisible alpha-zero payloads; destination colors may be erased.
- `mode: nontransparent`: skip source RGBA/grayscale alpha zero, or the source's
  indexed transparent index. Cel/layer opacity, visibility and background display
  semantics are not baked into samples.
- `mode: blend`: upstream normal per-pixel RGBA/grayscale alpha blending at full
  opacity. Indexed blending is refused; indices are never remapped.
- Optional `maskBits`: full source-sized binary bitmap with at least one selected
  bit; zero-bit holes preserve destination pixels in every mode. It can be taken
  from `extract_mask` when its rectangle matches the stamp source.

Source and destination native color modes must match. Indexed effective palettes
(all entries and size) and transparent indices must match EVERY target frame
exactly, even if only some entries are used; incompatible later targets cannot
partially apply earlier ones. Destinations require transparent editable image
layers/ancestors, unlinked/unshared cels, and whole footprints within the canvas.
No clipping or implicit unlink/unlock occurs. Missing destination cels are created
only for changed nontransparent data; unchanged batches preserve the redo branch.
Existing unrelated/off-canvas pixels, timing/tags/palettes/opacity/user data, GUI
selection and frame/layer focus remain unchanged. Native trimming can remove
transparent padding or wholly empty cels.

The source is snapshotted ONCE before ANY destination changes. Same-cel overlap and
an earlier destination that is also the source cannot affect later copies.
Results include the source specification, `mode` and lowercase 40-character
`sourceHash` (SHA-1 of decoded native region + dimensions/mode/palette interpretation).
Optional `expectedSourceHash` refuses `SOURCE_CHANGED` if a PNG/source changed since
dry run. It guards content consistency, not file authenticity; compression-only
changes need not change the digest. Reinspect revision too; never retry uncertain edits.

Source rectangles have at most 262,144 samples; all destination samples total at
most 1,048,576. Source snapshot, loaded PNG images and patches collectively fit
32 MiB scratch; worst-case destination sprite growth separately fits 32 MiB,
checked before patch allocation/native commands. PNG decoder allocations precede
these bridge checks. The document-wide selection is never used as a fallback.
