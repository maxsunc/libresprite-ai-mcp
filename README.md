# LibreSprite AI MCP

A local MCP server and modified [LibreSprite](https://github.com/LibreSprite/LibreSprite)
editor that let AI agents inspect, draw, edit, and animate sprites **in a visible
application**, with native undo and rendered PNG feedback.

**Source alpha — v0.7.0.** This is an independent development project, not an
official LibreSprite release. It requires building the custom editor; a stock
LibreSprite installation does not contain this bridge. No prebuilt app bundle
is currently provided.

## Current scope

The reproducible native baseline and live bridge/MCP integration are implemented,
including layer management, drawing primitives, cel transforms, selections,
palettes/tags, animation previews, asset browsing, and PNG/sprite-sheet/GIF/APNG
export. This is an early development
integration, not yet a full artist workflow.

The native editor and live integration have been verified on **Apple Silicon
macOS**, including undo/redo, multi-frame animations, native-file round trips,
and independently decoded exports. Linux transport is implemented but the full
editor workflow has not been validated here. Windows transport is not implemented.
CI checks the MCP server and GUI-independent helpers; it does not certify native
GUI behavior on every platform.

- `vendor/libresprite/`: pinned LibreSprite source, including its dependency submodules.
- `vendor/libresprite.upstream.json`: upstream revision and dependency provenance.
- `scripts/`: source import, verification, build, and launch helpers.
- `src/`: TypeScript MCP stdio server and serialized native-bridge client.
- `docs/live-bridge.md`: tools, connection workflow, safety, and current limits.
- `docs/building.md`: prerequisites and baseline verification steps.
- `examples/mcp/`: portable client configuration templates.
- `build/`: ignored local build outputs.

The baseline is the upstream `v1.2` tag at
`5cb089be32f56b4ae559ae51f0c5666049f41bca`, not a moving branch.

## Build and run

You need Node.js 20+, Python 3, a C++ compiler, and the native dependencies in
[the macOS build guide](docs/building.md). Start from a checkout:

```sh
git clone https://github.com/maxsunc/libresprite-ai-mcp.git
cd libresprite-ai-mcp
npm ci
npm run build
bash scripts/build-libresprite.sh
```

To run the editor without agent access:

```sh
bash scripts/run-libresprite.sh
```

The helpers do not install an application into `/Applications` or require `sudo`.
They operate on the local development build.

## Live MCP integration

Configure your MCP client to run
`node /absolute/path/to/libresprite-ai-mcp/dist/index.js`; merge one of the
[generic stdio or OpenCode V2 templates](examples/mcp/README.md) into your existing
settings and replace the placeholder path.
Use `libresprite_launch`, then `libresprite_connect`, then explicitly resume
with `libresprite_set_paused` before editing. A normal editor launched without
automation flags remains disconnected from agents.

The default asset root is the checkout's ignored `assets/` directory. Start with
copies of artwork, not your only originals. The server may be configured with
`LIBRESPRITE_ASSET_ROOT`, `LIBRESPRITE_SOCKET`, and `LIBRESPRITE_EXECUTABLE`; see
the live guide for details. Your client/model needs to support MCP image results
to see previews.

Available now: document creation/opening, inspection, rendered PNG feedback,
undoable RGBA pixels/shapes/strokes/fills, layers/groups, independent animation
frames and timing, undo/redo, and native save.
Cel position/opacity, flips/quarter-turns, explicit unlinking, native selection
masks, selection-aware drawing, and overlap-safe selection moves/copies are supported.
Whole-cel copy between existing layers/frames, ordered frame-range duplication,
tag-safe frame reordering, atomic cel/timing batches, and selected-region
flips/rotations across explicit frames are also available.

Read-only asset thumbnails, contact sheets/onion skins, and atomic PNG/sprite-sheet
exports are also available, along with undoable palette/tag editing and animated
GIF/APNG export. See the
[live bridge guide](docs/live-bridge.md) for setup, all **51 tools**, and limitations.

The opt-in editor now has a persistent **AI status / Pause / Resume** button in
the bottom-right status bar. A pause made there cannot be remotely overridden.
Explicit document activation, frame/layer focus, and saved-only document closing
support everyday navigation without silently switching the target of an edit.

```sh
npm test
python3 -m unittest discover -s tests -v
python3 scripts/smoke-test-libresprite.py
python3 scripts/test-live-bridge.py
```

The integration test launches its own disposable GUI instance. A visible MCP
demo is available with `node scripts/demo-live.mjs` after both builds.
Use `node scripts/demo-live.mjs --animation` for a four-frame, grouped-layer demo
with cel transforms, selection copy/fill feedback, editable swatches/tags, and animated exports.
Native updates require a newly launched editor. Save existing work first; the
tools never automatically close or kill a window that might hold unsaved work.

## Editing safeguards and limits

- Agent editing starts paused and pauses on disconnect; explicitly resume before
  mutations and pause before manual work. A local user pause persists through
  reconnect and must be released using the editor's Resume button.
- Writes require the active document and its current revision. After a timeout
  or uncertain result, reconnect and inspect rather than blindly retrying.
- Native edits are undoable. Saves/exports publish atomically with overwrite
  refused unless explicitly requested.
- File access stays inside the configured asset root. The bridge is a local
  private Unix socket, not a public network service.
- Current bounds include 1024×1024 canvases, 256 frames, and 128 layers. Some
  operations are RGBA-only; GIF quantizes color/alpha and delay, while APNG
  preserves rendered RGBA and millisecond timing.

These safeguards are not a hostile-input sandbox or a replacement for backups.
Read [the exact operation semantics and limits](docs/live-bridge.md) before
editing important artwork.

## Next priorities

1. Remaining editing gaps: canvas operations, richer selections/layers/brushes.
2. Easier installation and reproducible Apple Silicon application packaging.
3. Automated native builds/regressions and validated Linux support.

The v0.6.0 user-control/navigation milestone was reviewed and approved. The
v0.7.0 animation-workflow milestone is next for manual review. Run
`node scripts/demo-animation.mjs` for a separate editor with a generated saved
five-frame animation and a connected pause-button monitor. One native Undo
removes the entire final multi-frame cel batch. See
[the step 2 test checklist](docs/testing-v0.7.md). Subsequent milestones should
wait until this review is approved. The earlier
[step 1 checklist](docs/testing-v0.6.md) and demo remain available.

See [the development milestones](CHANGELOG.md) for what is already implemented.
Bug reports and focused contributions are welcome through the
[GitHub issues](https://github.com/maxsunc/libresprite-ai-mcp/issues).
Include the bridge version, platform, reproduction steps, and errors, and omit
private artwork, local paths, and credentials. Use a disposable sprite for tests.

## Source and licensing

Project-authored integration code is **GPL-2.0-only**, with the full text in
[`LICENSE`](LICENSE). LibreSprite and its libraries retain their upstream
copyright and license notices. See [credits and third-party notices](CREDITS.md),
[our native modifications](docs/native-changes.md), and
[the licensing overview](LICENSE.md). Distributing modified editor binaries
requires corresponding source/build information and applicable dependency
notices; giving credit alone is not sufficient.

The working artwork, runtime files, build outputs, and personal client
configuration are not included. Using this editor does not automatically
GPL-license independently created artwork; assets need their own rights review.

The imported source contains ordinary files, not a nested Git repository or an
application-level Git submodule. After cloning this repository,
no upstream submodule initialization is required to build it. The retained
upstream `.gitmodules` file is informational.

`python3 scripts/vendor-libresprite.py --verify` checks the imported baseline
against a pinned upstream checkout in the ignored `.cache/` directory. That
command downloads the checkout if necessary and intentionally reports future
native changes as differences. The importer refuses to overwrite existing source.
The baseline and native bridge changes are separate commits. Project-authored
integration code uses GPLv2-only; existing upstream component licenses remain
intact.
