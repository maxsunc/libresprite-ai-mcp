# Native changes from the pinned LibreSprite source

This is a modified development editor, not the unmodified upstream release.
The imported baseline is LibreSprite v1.2 at
`5cb089be32f56b4ae559ae51f0c5666049f41bca`; the dependency revisions are in
[`vendor/libresprite.upstream.json`](../vendor/libresprite.upstream.json).
The local baseline commit is `d4f91f0`.

The functional changes below were made on **2026-10-01** in milestones 0.1.0
through 0.5.0. Prominent per-file modification notices and this index were added
on **2026-10-08** for publication. Original copyright and license headers are
retained; MIT-licensed document-library files retain their MIT terms.

All paths below are relative to `vendor/libresprite/`.

| Files | Changes |
| --- | --- |
| `src/app/automation/bridge.cpp`, `bridge.h` (new) | Opt-in private Unix-socket bridge; UI-thread native operations; pause, session/revision, path, transaction, and resource guards. |
| `src/app/automation/apng.cpp`, `apng.h` (new) | Bounded, GUI-independent lossless APNG assembly using native PNG frames. |
| `src/app/CMakeLists.txt` | Build and link the bridge, JSON header dependency, and APNG assembler. |
| `src/app/app.cpp`, `app.h` | Own the bridge lifecycle only when explicitly requested. |
| `src/app/app_options.cpp`, `app_options.h` | Add explicit automation socket and asset-root launch options. |
| `src/app/cmd/add_palette.cpp`, `remove_palette.cpp` | Correct native palette snapshot redo and palette-removal undo behavior. |
| `src/app/ui/document_view.cpp`, `timeline.cpp` | Handle groups safely in UI/timeline rendering and preserve valid selection during deletion. |
| `src/app/ui/editor/brush_preview.cpp` | Avoid treating a group layer as an image layer during preview. |
| `src/app/ui/editor/standby_state.cpp`, `tool_loop_impl.cpp` | Guard manual drawing into groups while preserving ordinary image-layer painting. |
| `src/doc/cels_range.cpp`, `cels_range.h` | Traverse nested group cels correctly. |
| `src/doc/layers_range.cpp`, `layers_range.h` | Traverse nested layers correctly. |
| `src/doc/sprite.cpp` | Permit valid frame-zero duration access. |

The baseline import also intentionally omitted upstream's generated
`src/config.h.gch`, a compiler-specific precompiled header. That omission and the
source-import procedure are documented in [the build guide](building.md).

The ordinary editor retains its upstream JavaScript scripting support; this
integration adds neither a Lua runtime nor an arbitrary-script MCP tool.
The bridge uses the existing editor model, undo stack, renderer, commands, and
codecs rather than replacing them with a separate asset-editing engine.

For the exact code changes, compare the baseline and current source:

```sh
git diff d4f91f0..HEAD -- vendor/libresprite
```

See [the changelog](../CHANGELOG.md), [live bridge semantics](live-bridge.md), and
[credits/license index](../CREDITS.md) for milestone details, safeguards, and
retained licenses. The standalone baseline verifier intentionally reports these
native modifications as differences; it is not a test that the current modified
editor must match unmodified upstream byte-for-byte.

## 2026-10-08 — v0.6.0 user control and navigation

`src/app/automation/bridge.cpp` additionally owns a persistent status-bar button
in opt-in windows, with a local pause latch that remote requests cannot override.
It exposes guarded explicit activation, non-editing layer/frame focus, and
saved/unmodified-only document closing through the existing native view/model
lifecycle. The standalone bridge files retain GPL-2.0-only licensing. No new
changes to upstream UI source files are needed for the control.

## 2026-10-08 — v0.7.0 atomic animation workflows

`src/app/automation/bridge.cpp` adds independent raw cel copies, explicit frame
duplication/permutation, atomic cel/timing batches, and selected-mask transforms
across explicit frames. All are guarded UI-thread transactions with prevalidation
and bounded scratch/aggregate crop growth.

New `src/app/automation/reorder_frames.cpp` and `.h` implement a native undo
command that reattaches existing cels according to a validated permutation,
preserving image/cel-data IDs and linked relationships without transient frame
collisions. The command snapshots current objects on each undo/redo so later
layer deletion/restoration cannot leave stale pointers. These new files are
GPL-2.0-only. `src/app/CMakeLists.txt` includes the command in the native build.

New `src/app/automation/revision_metadata.h` canonicalizes the recovery writer's
initial 0→1 layer/image version transition in revision fingerprints, without
modifying the actual native telemetry, properties, pixel data, IDs, or history.
Higher version counters remain significant. This avoids unrelated background
backups spuriously blocking edits with `STALE_REVISION`; native unit tests cover
the canonicalization and retained change detection. This new header is also
GPL-2.0-only.

## 2026-10-08 — v0.8.0 canvas, layers, masks, and painting

`src/app/automation/bridge.cpp` adds bounded all-frame canvas operations,
independent recursive layer copies, layer reparenting/blend properties,
polygon/bitmap masks, explicit bitmap brushes, indexed creation and exact-index
pixel painting. Canvas resize preserves whole images; crop uses native
ReplaceImage/RemoveCel/SetCelPosition/SetSpriteSize/SetMask transactions with
explicit discard authorization. Pixel work still uses native PatchCel, trimming,
and undo; brush path/edges use native integer primitives. All document mutations
now check that every target editor view is idle, not just animation-range edits.

New `src/app/automation/reparent_layer.cpp` and `.h` implement an ID-resolving
native undo command that changes parent/order without cloning or removing
objects. A destination allocation happens before detaching from the source;
undo/redo resolve IDs after later folder deletion/restoration. These new files
are GPL-2.0-only. `src/app/CMakeLists.txt` builds this command. No upstream
document-model or ordinary-editor command behavior is changed for this milestone.

## 2026-10-08 — v0.9.0 packaging isolation

`src/base/fs_osx.mm` and `src/base/fs.h` add a small macOS bundle-identifier
query (retaining their MIT licensing). `src/app/resource_finder.cpp` uses a
separate user-data directory only for `io.github.maxsunc.libresprite-ai-mcp`.
This isolates packaged preferences, palettes, user resources, and recovery from
stock/development LibreSprite. Unbundled native builds retain upstream paths;
there is no new editor command or change to sprite/Undo semantics.
`src/app/automation/bridge.cpp` reports bridge v0.9.0; the native tool set remains
unchanged. Packaging and path-mapping build flags live in project-owned scripts.
