# LibreSprite AI MCP

A local MCP server and modified [LibreSprite](https://github.com/LibreSprite/LibreSprite)
editor that let AI agents inspect, draw, edit, and animate sprites **in a visible
application**, with native undo and rendered PNG feedback.

**Source alpha — v0.13.0.** This is an independent development project, not an
official LibreSprite release. A stock LibreSprite installation does not contain
this bridge. Review-package builders are available for Apple Silicon macOS and
Windows x64. No public binary releases are published; Windows packages remain
private-review-only pending a third-party license/corresponding-source audit.

## Current scope

The reproducible native baseline and live bridge/MCP integration are implemented,
including layer management, drawing primitives, cel transforms, selections,
palettes/tags, animation previews, asset browsing, and PNG/sprite-sheet/GIF/APNG
export. This is an early development
integration, not yet a full artist workflow.

The native editor and live integration have been verified on **Apple Silicon
macOS**, including undo/redo, multi-frame animations, native-file round trips,
and independently decoded exports. Linux transport is implemented but the full
editor workflow has not been validated here. **Experimental Windows x64 support**
now includes a native named-pipe bridge, build instructions and a standalone
private-review ZIP builder with bundled Node.js; see [the Windows guide](docs/windows.md).
Windows validation includes successful real-editor calls to **all 70 MCP tools**,
the full native regression suite, and portable-package relocation to Unicode/spaced
paths without MSYS2 on the runtime PATH. A full manual mouse/keyboard/pen review,
code signing and third-party redistribution/license audit remain outstanding.
CI jobs are provided, but automated tests do not certify every GUI workflow.

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

For Windows, follow [the UCRT64 build and portable-package guide](docs/windows.md).
For macOS, you need Node.js 20+, Python 3, a C++ compiler, and the native dependencies
in [the macOS build guide](docs/building.md). Start from a checkout:

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
[client configuration templates](examples/mcp/README.md) into your existing
settings and replace the placeholder path. Windows packages include their own
Node runtime; see the [Pi example below](#use-with-pi) or the
[Windows stdio template](examples/mcp/windows-stdio.json).
Use `libresprite_launch`, then `libresprite_connect`, then explicitly resume
with `libresprite_set_paused` before editing. A normal editor launched without
automation flags remains disconnected from agents.

The default asset root is the checkout's ignored `assets/` directory. Start with
copies of artwork, not your only originals. The server may be configured with
`LIBRESPRITE_ASSET_ROOT`, `LIBRESPRITE_SOCKET`, and `LIBRESPRITE_EXECUTABLE`; see
the live guide for details. Your client/model needs to support MCP image results
to see previews.

### Use with Pi

Pi can start the MCP server automatically and let the agent launch and use the
editor. With Pi's built-in MCP support:

1. Merge the entry below into `~/.pi/agent/mcp.json` (on Windows,
   `%USERPROFILE%\.pi\agent\mcp.json`) for all projects, or `.pi/mcp.json` for
   one trusted project. Preserve any existing servers/settings.
2. Replace `C:/Tools/LibreSprite-AI` with the extracted Windows package folder,
   and `C:/Art/Sprites` with a folder for disposable artwork. These are example
   paths, not required install locations.

   ```json
   {
     "mcpServers": {
       "libresprite": {
         "command": "C:/Tools/LibreSprite-AI/mcp/runtime/node.exe",
         "args": ["C:/Tools/LibreSprite-AI/mcp/dist/index.js"],
         "env": {
           "LIBRESPRITE_ASSET_ROOT": "C:/Art/Sprites"
         },
         "exposure": "deferred",
         "description": "Create, inspect, draw and animate pixel art in a visible LibreSprite editor, with native undo and PNG feedback."
       }
     }
   }
   ```

   For a source build on any supported platform, use `"command": "node"` and
   `"args": ["/absolute/path/to/libresprite-ai-mcp/dist/index.js"]` instead.
   Set `LIBRESPRITE_ASSET_ROOT` to a suitable absolute path for your platform.
3. Run `/reload` in Pi, then `/mcp` to check the connection. From a terminal,
   `pi mcp list` should report `libresprite: connected, 70 tools`. With
   `deferred` exposure, Pi discovers tools when needed rather than loading all
   70 definitions into every prompt.
4. Ask the agent, for example:

   > Use the LibreSprite MCP to launch the editor if needed, connect, and
   > explicitly resume agent editing. Create a 16×16 slime sprite using the
   > native drawing tools, render a preview, and save it as `slime.ase` inside
   > the configured asset root.

Pi starts the stdio server, **not the editor**, when it connects. The agent calls
`libresprite_launch`, `libresprite_connect`, then `libresprite_set_paused`
(`paused: false`) when instructed to edit. If a bridge-enabled editor is already
running, connect instead of launching another. An ordinary manually launched
window cannot be attached retroactively. A pause made in the editor must be
released there, not by the agent.

These steps use Pi's built-in MCP support. An extension that replaces `/mcp`
may use a different configuration; remove that replacement to use these steps.
Start with copies of artwork: the agent can edit and save inside its asset root.

## Windows x64 portable review package

The Windows package keeps `LibreSprite-AI.exe`, its DLLs/resources, and a
production MCP server with bundled Node.js together. No separate Node, MSYS2,
compiler or administrator access is needed **to run the package**. An external
AI/MCP client and model are still required. Normal manual editing does not
require an MCP client.

After completing the [Windows build prerequisites](docs/windows.md#building-from-source)
and building the editor/server, create a private-review folder and ZIP with:

```sh
npm run package:windows
```

Output goes under `build/packages/`; existing output is refused. Extract the
whole package, keep its files together, and run `doctor.cmd` for read-only setup
diagnostics. Use the [Pi setup above](#use-with-pi) or another
[stdio client](examples/mcp/windows-stdio.json) to enable agent editing.
Preferences/recovery use `%APPDATA%\LibreSprite AI`, separate from stock
LibreSprite. Assets default to `%USERPROFILE%\Pictures\LibreSprite AI MCP`
unless `LIBRESPRITE_ASSET_ROOT` is set.

**Windows 11 x64 is the initial target.** The package is unsigned and may trigger
SmartScreen. No installer or public Windows download is provided. Do not publicly
redistribute generated binaries until the third-party license and corresponding
source audit is complete; bundled notices alone do not satisfy that work. See
[the Windows guide](docs/windows.md) for build, relocation, testing and release limits.

## Apple Silicon review package

**v0.13.0 review:** Cooperative editing remains experimental. Readiness/waiting,
safe view-only panning and guarded prepare/apply corrections let manual edits
coexist without blindly overwriting them. See
[cooperative editing](docs/cooperative-editing.md) and
[the v0.13 checklist](docs/testing-v0.13.md). Approved v0.9/v0.12 packages are not rebuilt.

After installing the [build prerequisites](docs/building.md) and `npm ci`, run:

```sh
npm run package:macos
```

This rebuilds current source and creates a new folder and ZIP under
`build/packages/`, with **LibreSprite AI.app**, bundled native libraries/resources,
a production MCP folder, setup diagnostics, checksums, notices, and corresponding
project/FreeType/LZ4 source. It never installs or replaces an app, changes client
configuration, or includes private artwork. Existing output is refused.

The package runs outside the checkout **without Homebrew**; MCP needs external
Node.js 20+. Keep the folder together, run `bash /path/to/package/mcp/doctor.sh`,
and configure the client to run `bash /path/to/package/mcp/start-mcp.sh`.
The app has isolated preferences/recovery storage. Package minimum macOS is
computed from all bundled libraries (the current local build requires **26.0+**).
It is ad-hoc signed, **not Developer ID signed or notarized**.
The separate **v0.12.0 package** includes the matching **67-tool** MCP server and
current inspection, correction and pixel-region features. The earlier approved
v0.9.0 package is retained unchanged; existing windows are not upgraded in place.
See [packaging/setup](docs/packaging.md) and
[the v0.12 package checklist](docs/testing-package-v0.12.md).

## Editing features and tests

Available now: document creation/opening, inspection, rendered PNG feedback,
undoable RGBA pixels/shapes/strokes/fills, layers/groups, independent animation
frames and timing, undo/redo, and native save.
Cel position/opacity, flips/quarter-turns, explicit unlinking, native selection
masks, selection-aware drawing, and overlap-safe selection moves/copies are supported.
Whole-cel copy between existing layers/frames, ordered frame-range duplication,
tag-safe frame reordering, atomic cel/timing batches, and selected-region
flips/rotations across explicit frames are also available.
Canvas resize preserves off-canvas pixels; explicit guarded cropping is undoable
across all frames/layers. Independent layer/group copies, cycle-safe reparenting,
native blend modes, polygon/bitmap masks, custom bitmap brushes, and exact
indexed-color painting are now included.

Read-only asset thumbnails, contact sheets/onion skins, and atomic PNG/sprite-sheet
exports are also available, along with undoable palette/tag editing and animated
GIF/APNG export. See the
[live bridge guide](docs/live-bridge.md) for setup, all **70 tools**, and limitations.

Read-only frame differences highlight added/removed/modified rendered pixels
and report exact counts, bounds, and occupancy centroids. Isolated layer/group
previews, scoped differences/contact sheets and explicit renderer-only hidden
content inspection are also available. Loop/timing diagnostics report actual tag
playback order, cumulative exposures, frame/transition measurements and GIF delay
limitations without changing the animation. See
[animation inspection](docs/animation-inspection.md). The approved v0.9.0 package
has not been rebuilt; these source features require a new development editor.
Use `node scripts/demo-inspection.mjs` for a separate generated review animation
and saved inspection PNG/JSON results; it leaves its editor paused and open.

Atomic animation correction now supports explicit multi-frame/layer RGBA or indexed
pixel batches and per-frame masked-region moves/copies, with dry-run change summaries
and one native Undo step. GUI selection/focus, other pixels and animation metadata
are preserved. See [correction semantics](docs/animation-correction.md).
This v0.11.0 milestone is awaiting user review; no personal artwork is edited by tests.
Use `node scripts/demo-correction.mjs` for an independent generated before/after
animation with dry-run summaries and two undoable correction steps; review with
[the v0.11 checklist](docs/testing-v0.11.md).

Exact native cel pixel reads expose RGBA, grayscale-alpha and indexed values
in bounded rectangles, including off-canvas data, without rendering or changing
the document. Read-only mask extraction finds raw alpha/value matches and explicit
seeded connected components without changing the GUI selection. See
[pixel regions](docs/pixel-regions.md). Atomic region/PNG stamping reuses native
sprite parts across explicit frames/layers with replace, nontransparent-copy or
alpha-blend modes, source snapshots and one Undo step.
Use `node scripts/demo-pixel-regions.mjs` for a separate generated review editor
and [the v0.12 checklist](docs/testing-v0.12.md) for native/MCP testing.

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
  mutations. Use Pause for exclusive manual control; ordinary gestures use
  [cooperative waiting/conflicts](docs/cooperative-editing.md). A local pause persists through
  reconnect and must be released using the editor's Resume button.
- Direct writes require the active document and its current revision; prepared
  corrections additionally use immutable dependency tokens for safe disjoint rebasing. After a timeout
  or uncertain result, reconnect and inspect rather than blindly retrying.
- Native edits are undoable. Saves/exports publish atomically with overwrite
  refused unless explicitly requested.
- All document edits wait/refuse unfinished target-view drawing, transforms or
  playback. Only proven viewport pans may coexist with reads/corrections.
  Crops refuse pixel/mask loss unless explicitly authorized.
- File access stays inside the configured asset root. The bridge is a local
  private Unix socket (macOS/Linux) or same-user named pipe (Windows), not a public
  network service.
- Current bounds include 1024×1024 canvases, 256 frames, and 128 layers. Some
  operations are RGBA-only; GIF quantizes color/alpha and delay, while APNG
  preserves rendered RGBA and millisecond timing.

These safeguards are not a hostile-input sandbox or a replacement for backups.
Read [the exact operation semantics and limits](docs/live-bridge.md) before
editing important artwork.

## Review status and release limits

The v0.9.0 Apple Silicon package was user-tested and approved on 2026-10-09.
Downloadable binary releases and Developer ID signing/notarization remain separate
decisions; no binary release has been published.
Linux full-editor validation remains outstanding; the new Windows port is an
experimental, separate review effort with [its own limits](docs/windows.md).

The v0.6.0 user-control, v0.7.0 animation, and v0.8.0 editing milestones were
reviewed and approved. Run
`node scripts/demo-editing.mjs` for a separate editor with generated RGBA/indexed
sprites and saved before/after crop files. One native Undo restores the canvas,
discarded pixels on all frames/layers, and selection together. See
[the step 3 test checklist](docs/testing-v0.8.md). The approved packaging milestone
has its own [review checklist](docs/testing-v0.9.md). The earlier
[step 1](docs/testing-v0.6.md) and
[step 2](docs/testing-v0.7.md) checklists and demos remain available.

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
