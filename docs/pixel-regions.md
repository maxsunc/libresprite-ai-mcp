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
