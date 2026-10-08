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
