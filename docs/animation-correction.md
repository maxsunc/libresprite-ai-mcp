# Atomic animation correction — v0.11.0

These tools apply **explicit corrections**, not automatic animation generation.
Inspect frames/layers with [animation inspection](animation-inspection.md), identify
the exact regions/pixels to change, dry-run if useful, apply, then render/inspect
again. No rigging, tweening, smoothing or automatic motion inference is added.

Both tools require the active sprite, current `expectedRevision`, a resumed bridge
and idle editor/target views. IDs are session-local and frames are zero-based.
Pause before manual work; local user pauses cannot be overridden. Dry runs have
the **same guards** as edits, even though they do not mutate anything.

## Pixel corrections

`libresprite_edit_pixels` accepts `documentId`, `expectedRevision`, optional
`dryRun` (false), `label`, and `edits` (1–256 unique layer/frame targets):

```json
{
  "documentId": 1,
  "expectedRevision": 10,
  "dryRun": true,
  "edits": [
    { "layerId": 2, "frame": 0, "pixels": [{ "x": 4, "y": 8, "r": 40, "g": 180, "b": 100, "a": 255 }] },
    { "layerId": 2, "frame": 1, "pixels": [{ "x": 5, "y": 9, "r": 0, "g": 0, "b": 0, "a": 0 }] }
  ]
}
```

RGBA pixels replace raw values, not alpha-blended composite colors. Alpha zero is
canonical transparent zero (erase). Indexed sprites instead require pixels shaped
`{x,y,index}`; indices must exist in **that frame's** palette or equal its transparent
index. No index/RGBA conversion or palette mutation occurs. Grayscale pixel painting
is refused. A batch accepts at most **16,384 total input pixels**; every entry must
have at least one. Within an entry, duplicate coordinates use the last value, but
all inputs are validated, even ones subsequently overwritten.

Only listed coordinates change. Missing cels are created only when changed values
require image data; empty erasures do not create blank cels. Identical replacements
are no-ops. There is no implicit GUI selection clipping: the explicit pixel list
is the scope, and the current mask is preserved.

## Per-frame masked-region moves/copies

`libresprite_translate_regions` accepts the same outer arguments. Every entry in
`edits` supplies its own `layerId`, `frame`, `mask`, `dx`, `dy`, and optional `copy`:

```json
{
  "documentId": 1,
  "expectedRevision": 10,
  "edits": [
    { "layerId": 2, "frame": 0, "mask": { "x": 4, "y": 8, "width": 2, "height": 2, "bits": "1001" }, "dx": 1, "dy": 0 },
    { "layerId": 2, "frame": 1, "mask": { "x": 5, "y": 9, "width": 3, "height": 1, "bits": "101" }, "dx": -1, "dy": 1, "copy": true }
  ]
}
```

- `bits` is row-major binary text, exactly width × height, with at least one `1`.
  Width/height are 1–1024; at most 262,144 bits per mask and 1,048,576 in aggregate.
- `dx`/`dy` are integer canvas translations, −1023…1023; `copy` defaults false.
- The **whole supplied source and destination rectangles** must fit the canvas,
  including zero-bit padding. Clipping, including transparent-mask clipping, is refused.
- Move clears only source `1` bits, then pastes original raw samples at translated
  `1` bits; copy omits clearing. Overlaps read the original cel, not already-written
  patch data. Selected transparent pixels replace/erase destination colors too.
- Holes and pixels outside the union of source/destination selected bits are
  untouched. The source and destination are within the **same explicit cel**, not
  different frames/documents. Each frame may use different masks/offsets.
- RGBA, indexed and grayscale raw values are retained without interpolation,
  blending, palette conversion or remapping. A missing cel is transparent/no-op;
  zero translation is a no-op. The GUI mask is never used, changed or moved.

## Atomicity, metadata and limits

Every target must be a transparent, editable image layer with editable ancestors.
Locked/background/group targets, linked cels and shared images are refused; unlink
or make independent copies **explicitly** first. Duplicate layer/frame entries are
refused, including duplicates that would otherwise be no-ops. Hidden editable
layers can be corrected but are not shown/unlocked or silently focused.

All targets/coordinates/values are validated and all patches prepared before any
commands run. Invalid later entries cannot partially apply earlier ones. Changed
batches use **one native Undo step**, which restores every affected cel. Unchanged
batches and dry runs preserve revision, saved state and the redo branch. Timing,
tags, palettes, cel opacity/user data, GUI frame/layer focus and document-wide mask
remain unchanged. Unrelated/off-canvas raw pixels are retained; native PatchCel
trimming can remove transparent padding or wholly empty cels.

Results include `dryRun`, `changedPixels`, `wouldEditCels`, `editedCels` and ordered
`changes` (target IDs, raw changed pixel counts and unscaled minimal bounds).
Dry-run `editedCels` is zero; `wouldEditCels` predicts the actual count. A later
apply must still use a fresh/current revision. Metadata summaries are not PNG
previews or composite-visible differences: hidden content and indexed/alpha effects
can make raw changes invisible in the full render.

Aggregate patch scratch and worst-case sprite image growth are each capped at
32 MiB, checked **before allocation**. A later shrinking target cannot subsidize an
earlier growth beyond the bound. Far-off-canvas union growth and native-file cel
dimensions are checked too. Protocol request size remains 1 MiB; large inputs may
need separate batches (separate Undo steps). Never blindly retry uncertain edits.

The approved v0.9.0 package and already-running editors remain unchanged. Rebuild
both source components, refresh the MCP catalog for **64 tools**, and launch a new
development window. Use generated fixtures for review, not original artwork.
