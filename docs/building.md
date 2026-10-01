# Building the LibreSprite baseline

## Upstream snapshot

Source lives at `vendor/libresprite/` and is pinned to LibreSprite `v1.2`, commit
`5cb089be32f56b4ae559ae51f0c5666049f41bca`. Dependency submodules have been imported
as ordinary source directories at their pinned revisions. Provenance is recorded
in `vendor/libresprite.upstream.json`.

All upstream source and license notices are retained, with one intentional
exclusion: `src/config.h.gch`, a generated, compiler-specific precompiled header
that upstream tracks. It must not be reused across machines or compilers.
The upstream Git attributes normalize text line endings; source verification
allows CRLF/LF differences so that a fresh clone verifies on other machines.

## macOS prerequisites

Install Apple's Command Line Tools if they are not already installed:

```sh
xcode-select --install
```

Install the native build dependencies using Homebrew:

```sh
brew install cmake ninja pkgconf sdl2 sdl2_image tinyxml2 freetype pixman libarchive giflib libpng jpeg-turbo
```

The build helper uses the current macOS SDK and host architecture, including
Apple Silicon (`arm64`). It does not use the outdated x86-only SDK instructions
in the upstream installation document.

V8 is optional and disabled for this baseline. The bundled Duktape JavaScript
engine remains enabled, so scripting is available without installing V8 or
depending on the local Node.js ABI. No Lua runtime is added.

The CMake policy floor is supplied on the command line to accommodate legacy
upstream CMake files with modern CMake, without editing the vendored build files.

## Build and launch

From the repository root:

```sh
bash scripts/build-libresprite.sh
bash scripts/run-libresprite.sh
```

The executable and its runtime assets are generated under
`build/libresprite/bin/`. Keep the `data/` directory beside the executable.
Build outputs are ignored by Git. Re-running the build uses incremental
compilation; deleting the build directory is not necessary for normal development.

The scripts do not install or replace an application in `/Applications`.
The unmodified editor may use LibreSprite's normal user preferences and recovery
directories when launched, so it should not be treated as an isolated sandbox.

### Optional build settings

- `LIBRESPRITE_BUILD_DIR`: alternate output directory.
- `LIBRESPRITE_BUILD_TYPE`: defaults to `RelWithDebInfo`.
- `LIBRESPRITE_BUILD_JOBS`: defaults to four parallel compilation jobs.
- Extra arguments to the build script are passed to CMake configuration.

For example:

```sh
LIBRESPRITE_BUILD_TYPE=Debug bash scripts/build-libresprite.sh
```

## Verification

Start with a command-line smoke test:

```sh
bash scripts/run-libresprite.sh --version
bash scripts/run-libresprite.sh --help
```

The `v1.2` tag's source still defines its version string as `1.2-dev`; that output
does not mean the checkout is following the development branch.

Then launch the visible application and check that a small sprite can be drawn,
undone/redone, saved as `.ase`, closed, and reopened. Confirm that layers and
frame durations survive saving. Build success alone does not establish editing
or animation correctness.

Run the automated, dependency-free smoke test:

```sh
python3 scripts/smoke-test-libresprite.py
```

It uses SDL's dummy video driver and a generated transparent 16x16 PNG to check
the executable, CLI options, a pixel-exact PNG -> ASE -> PNG round trip, and
sprite-sheet image/JSON export. It also executes a small JavaScript script to
check the bundled scripting engine. Temporary fixtures are created under the ignored
`build/` directory and cleaned up after the test. It does not exercise GUI
interaction, the undo stack, or multiple animation frames.

The Python helper tests can run even before the application has been compiled:

```sh
python3 -m unittest discover -s tests -v
```

Verify the imported source before native changes are made:

```sh
python3 scripts/vendor-libresprite.py --verify
```

The first verification on a new machine needs network access to retrieve the
reference checkout. Building the already-imported source does not require it.

## Initial baseline results

The imported source built successfully on an Apple Silicon Mac using Apple
Clang 21, CMake 4.4.3, Ninja 1.13.2, and the current Command Line Tools SDK.
Homebrew's `sdl2` package resolves to `sdl2-compat` 2.32.72 on this machine.

Verified:

- All 1,594 imported files match the pinned upstream source/dependencies,
  apart from the explicitly excluded precompiled header.
- The native executable is Mach-O `arm64`.
- CLI version/help, JavaScript execution, lossless native-file round trip,
  and sprite-sheet image/metadata exports pass the smoke test.
- Seven Python helper tests pass.

The compiler emits upstream deprecation warnings and the linker reports
duplicate library arguments, but neither prevents the build. No native source
patches were needed for this baseline. The user also launched and manually
tested the visible editor successfully. Multi-frame animation and the future
automation bridge require their own validation. The subsequent live bridge
milestone and its tests are documented in [the live guide](live-bridge.md).
