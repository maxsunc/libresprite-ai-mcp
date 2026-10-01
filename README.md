# LibreSprite AI MCP

A development home for an enhanced LibreSprite editor and an MCP server that
will let AI agents inspect, draw, and animate sprites in the visible application.

## Current scope

The first milestone is a reproducible upstream build. The automation bridge and
MCP server have **not** been implemented yet.

The baseline has been built on Apple Silicon and passes CLI, scripting,
pixel-exact native-file round-trip, and sprite-sheet export smoke tests.

- `vendor/libresprite/`: pinned LibreSprite source, including its dependency submodules.
- `vendor/libresprite.upstream.json`: upstream revision and dependency provenance.
- `scripts/`: source import, verification, build, and launch helpers.
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

## Source and licensing

LibreSprite is upstream at <https://github.com/LibreSprite/LibreSprite> and is
distributed under GPLv2. Its license is preserved at
[`vendor/libresprite/LICENSE.txt`](vendor/libresprite/LICENSE.txt). Individual
libraries retain their own license files and notices; the root license does not
replace those notices. This project is not an official LibreSprite release.

The source snapshot contains ordinary files, not a nested Git repository or an
application-level Git submodule. Once this repository is committed and cloned,
no upstream submodule initialization is required to build it. The retained
upstream `.gitmodules` file is informational.

`python3 scripts/vendor-libresprite.py --verify` checks the imported baseline
against a pinned upstream checkout in the ignored `.cache/` directory. That
command downloads the checkout if necessary and intentionally reports future
native changes as differences. The importer refuses to overwrite existing source.
