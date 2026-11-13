# Windows x64 — experimental private review

The modified editor and its MCP server now have a native Windows implementation.
The first target is **Windows 11 x64**; Windows ARM64, older Windows versions,
installers and code signing are not part of this port. This is an independent
LibreSprite fork, not an official Windows LibreSprite release.

The bridge uses a local Windows named pipe, **not TCP or a firewall exception**.
Its protected ACL grants access only to the current Windows user; remote clients
are rejected and another editor cannot replace an occupied pipe name. Editing
still starts paused. Disconnect pauses the editor without closing it or losing
unsaved artwork. macOS/Linux keep their existing Unix-socket transport.

## Using a portable review package

1. Extract the entire ZIP to a writable local folder. Keep `data/`, the DLLs and
   `mcp/` beside `LibreSprite-AI.exe`; do not copy just the executable.
2. Open `LibreSprite-AI.exe` for ordinary manual editing. This does **not** enable
   AI access. For AI editing, let the MCP client's `libresprite_launch` tool
   launch a **new** bridge-enabled editor, then call `libresprite_connect` and
   explicitly resume with `libresprite_set_paused`.
3. Configure your MCP client using the bundled runtime, with absolute paths:

   ```json
   {
     "mcpServers": {
       "libresprite": {
         "command": "C:\\Tools\\LibreSprite-AI\\mcp\\runtime\\node.exe",
         "args": ["C:\\Tools\\LibreSprite-AI\\mcp\\dist\\index.js"]
       }
     }
   }
   ```

   Replace the example location with your extracted folder. Merge the server
   entry into your client's configuration; do not replace unrelated settings.
   OpenCode uses its existing `mcp.servers` shape with a command array containing
   those same two paths. Pi users can follow the
   [README's setup, verification and first-edit prompt](../README.md#use-with-pi).
   `start-mcp.cmd` is a convenience stdio launcher; prefer the direct `node.exe`
   entry above for clients that don't execute `.cmd` files.
4. Run `doctor.cmd` in a terminal for read-only diagnostics. `doctor.cmd --connect`
   explicitly connects to a running bridge, then disconnects (which pauses it).

Users do not need to install Node, a compiler or MSYS2, or run as administrator.
**The Node runtime is bundled; an external AI/MCP client and model are still required.** The package is unsigned, so Windows
may show a SmartScreen warning. Only run a build/source you trust.

Packaged assets default to `%USERPROFILE%\Pictures\LibreSprite AI MCP`.
Windows preferences and recovery use `%APPDATA%\LibreSprite AI`, separate from
stock LibreSprite. Test helpers use a disposable `LIBRESPRITE_USER_DIR` instead.
Do not enable LibreSprite's upstream portable-profile option if you want settings
outside the extracted application folder.

`LIBRESPRITE_EXECUTABLE` and `LIBRESPRITE_ASSET_ROOT` still override defaults.
`LIBRESPRITE_SOCKET` on Windows is a pipe name such as
`\\.\pipe\libresprite-ai-review`, **not a file path**. The suffix must contain
1–100 ASCII letters/digits/underscores/hyphens. Default names are stable for the
same checkout/package location and user; separate locations get separate names.
When manually launching with `--automation-socket`, use the same name/root as the
MCP server. Run the client and editor as the same user, normally without elevation.

## Building from source

Build dependencies are only required on the developer's machine. Install
[MSYS2](https://www.msys2.org/), update it following its instructions, and use the
**UCRT64** shell, not Git Bash, MSYS or the old 32-bit MinGW toolchain. Install:

```sh
pacman -S --needed \
  mingw-w64-ucrt-x86_64-gcc \
  mingw-w64-ucrt-x86_64-cmake \
  mingw-w64-ucrt-x86_64-ninja \
  mingw-w64-ucrt-x86_64-pkgconf \
  mingw-w64-ucrt-x86_64-curl \
  mingw-w64-ucrt-x86_64-freetype \
  mingw-w64-ucrt-x86_64-giflib \
  mingw-w64-ucrt-x86_64-libjpeg-turbo \
  mingw-w64-ucrt-x86_64-libpng \
  mingw-w64-ucrt-x86_64-pixman \
  mingw-w64-ucrt-x86_64-SDL2 \
  mingw-w64-ucrt-x86_64-SDL2_image \
  mingw-w64-ucrt-x86_64-tinyxml2 \
  mingw-w64-ucrt-x86_64-zlib \
  mingw-w64-ucrt-x86_64-libarchive
```

Install native Windows Node.js 20+ x64 and Python 3 (not Windows Store aliases),
and ensure `node`, `npm` and `python` are on PATH. Then, from the checkout in UCRT64:

```sh
npm ci
npm run build
bash scripts/build-libresprite.sh
npm test
python -m unittest discover -s tests -p test_platform.py -v
python -m unittest discover -s tests -p test_windows_packaging.py -v
python scripts/smoke-test-libresprite.py
node scripts/test-windows-mcp.mjs
```

The last command opens a NEW real editor with disposable artwork/settings, tests
MCP launch/connection, pause, drawing, rendered PNG feedback, stale-revision
conflicts, undo/redo, Unicode/spaced paths, save/reopen/overwrite protection,
root/junction/device/alternate-stream isolation, PNG/GIF/APNG export and reconnect
pause behavior, then terminates only that test-owned editor. Do not interrupt it
with manual gestures. Native helper tests also check the pipe ACL, duplicate-name
refusal, nonblocking backpressure and reconnect. Set `LIBRESPRITE_TEST_HEADLESS=1`
for SDL dummy-driver CI checks; those do not certify visible GUI interaction.
The full native regression suite now also supports Windows named pipes:

```sh
python scripts/test-live-bridge.py
```

It opens a separate disposable editor and exercises pixel-exact RGBA/indexed/
grayscale workflows, repeated Undo/Redo, all editing/inspection features,
resource limits and negative safety cases. Allow several minutes. Windows OS
mouse/keyboard gesture injection is not covered by this runner.

For successful calls to **every advertised MCP tool**, against the standalone
package rather than mocks, run:

```sh
node scripts/test-windows-mcp.mjs 'build/packages/libresprite-ai-0.13.0-windows-x64' --all-tools
```

This also checks MCP PNG image content, writes per-tool coverage to
`build/windows-tools-report.json`, and retains generated native sprites, PNGs,
sprite sheets, GIF and APNG under a new `build/windows-tools-results-*` folder.
The test fails if any advertised tool has no successful real-editor call. It
never uses personal artwork or terminates pre-existing editor processes. Successful
coverage is not a claim that every parameter combination or manual mouse/keyboard/
pen workflow has been tested.

## Building the standalone ZIP

After the native and TypeScript builds, run from UCRT64:

```sh
python scripts/package-windows.py --private-review
```

Or from PowerShell, specify `--prefix C:\msys64\ucrt64`. The builder copies a
native Windows x64 Node runtime from PATH (override with `--node`), checks PE
architecture, recursively bundles non-system imported DLLs and SDL3 when required
by SDL2-compat, includes resources, production MCP dependencies, license notices,
MSYS2 package metadata, the project's source snapshot and checksums. It fetches
the exact Node version's LICENSE; use `--node-license` for an offline local copy.
It does not install anything or edit client configuration. Existing output is
never replaced; choose a fresh `--output` path for another build.

The extracted folder and ZIP are written under `build/packages/`. Test relocation
and the bundled runtime (the test removes MSYS2 from the editor's DLL search PATH):

```sh
node scripts/test-windows-mcp.mjs 'C:/some moved folder/LibreSprite-AI'
```

Optional developer integrity check (requires Python):

```sh
python 'C:/some moved folder/LibreSprite-AI/verify-package.py'
```

**Private review only, not a public binary release.** Corresponding third-party
sources and the compatibility of all MSYS2 DLL licenses with this GPL-2.0-only
fork must be audited before distributing binaries publicly. In particular, modern
MSYS2 dependencies can introduce libraries/licenses beyond this project's macOS
package policy. Bundled notices/metadata and this project's source snapshot are
not a substitute for that audit or all required corresponding sources. Code
signing and a complete visible-GUI regression pass are also release work.
