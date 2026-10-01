# LibreSprite AI MCP

A development home for an enhanced LibreSprite editor and an MCP server that
will let AI agents inspect, draw, and animate sprites in the visible application.

## Current scope

The reproducible native baseline and live bridge/MCP integration are implemented,
including layer management, drawing primitives, and basic animation. This is an
early development integration, not yet a full artist workflow.

The baseline has been built on Apple Silicon and passes CLI, scripting,
pixel-exact native-file round-trip, and sprite-sheet export smoke tests.

- `vendor/libresprite/`: pinned LibreSprite source, including its dependency submodules.
- `vendor/libresprite.upstream.json`: upstream revision and dependency provenance.
- `scripts/`: source import, verification, build, and launch helpers.
- `src/`: TypeScript MCP stdio server and serialized native-bridge client.
- `docs/live-bridge.md`: tools, connection workflow, safety, and current limits.
- `docs/building.md`: prerequisites and baseline verification steps.
- `build/`: ignored local build outputs.

The baseline is the upstream `v1.2` tag at
`5cb089be32f56b4ae559ae51f0c5666049f41bca`, not a moving branch.

## Build and run

After installing the prerequisites in [the build guide](docs/building.md):

```sh
bash scripts/build-libresprite.sh
bash scripts/run-libresprite.sh
```

The helpers do not install an application into `/Applications` or require `sudo`.
They operate on the local development build.

## Live MCP integration

```sh
npm ci
npm run build
```

Configure your MCP client to run `node /absolute/path/to/dist/index.js`.
Use `libresprite_launch`, then `libresprite_connect`, then explicitly resume
with `libresprite_set_paused` before editing. A normal editor launched without
automation flags remains disconnected from agents.

Available now: document creation/opening, inspection, rendered PNG feedback,
undoable RGBA pixels/shapes/strokes/fills, layers/groups, independent animation
frames and timing, undo/redo, and native save. See the
[live bridge guide](docs/live-bridge.md) for setup, all **22 tools**, and limitations.

```sh
npm test
python3 scripts/test-live-bridge.py
```

The integration test launches its own disposable GUI instance. A visible MCP
demo is available with `node scripts/demo-live.mjs` after both builds.
Use `node scripts/demo-live.mjs --animation` for a four-frame, grouped-layer demo.
Already-running editor windows must be restarted to pick up native updates.

## Source and licensing

LibreSprite is upstream at <https://github.com/LibreSprite/LibreSprite> and is
distributed under GPLv2. Its license is preserved at
[`vendor/libresprite/LICENSE.txt`](vendor/libresprite/LICENSE.txt). Individual
libraries retain their own license files and notices; the root license does not
replace those notices. This project is not an official LibreSprite release.

The imported source contains ordinary files, not a nested Git repository or an
application-level Git submodule. Once this repository is committed and cloned,
no upstream submodule initialization is required to build it. The retained
upstream `.gitmodules` file is informational.

`python3 scripts/vendor-libresprite.py --verify` checks the imported baseline
against a pinned upstream checkout in the ignored `.cache/` directory. That
command downloads the checkout if necessary and intentionally reports future
native changes as differences. The importer refuses to overwrite existing source.
The baseline and native bridge changes are separate commits. Project-authored
integration code uses GPLv2; see [licensing](LICENSE.md).
