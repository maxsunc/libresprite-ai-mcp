# Apple Silicon package refresh / v0.12.0 review

The user authorized a separate package rebuild and source commit/push on
2026-10-12. The approved v0.9.0 package remains intact. v0.12.0 bundles the
current editor/production MCP server and **67 tools**, not just the newer server
with an older app. This is a local, ad-hoc-signed review package; not an installed,
published, Developer ID signed or notarized release. User approval of this new
package is separate from automated verification. Native-CI/Linux work stays out
of scope. Requirements remain Apple Silicon macOS **26.0+**, external Node.js 20+
for MCP, and Python 3 for the optional file verifier.

## Build and relocation

```sh
npm test
python3 -m unittest discover -s tests -v
npm run package:macos
```

New outputs (ignored, not committed/pushed as binaries):

- `build/packages/libresprite-ai-mcp-0.12.0-macos-arm64/`
- `build/packages/libresprite-ai-mcp-0.12.0-macos-arm64.zip`
- `build/packages/libresprite-ai-mcp-0.12.0-macos-arm64.zip.sha256`

The builder refuses to overwrite these or earlier packages. Extract the ZIP to a
NEW location **outside the checkout, with spaces in the path**. Keep the folder
together. Set `PACKAGE` below to its absolute extracted location.

```sh
# Run from the directory containing the original ZIP/checksum:
shasum -a 256 -c libresprite-ai-mcp-0.12.0-macos-arm64.zip.sha256
# PACKAGE points to the relocated/extracted folder:
python3 "$PACKAGE/verify-package.py"
codesign --verify --deep --strict "$PACKAGE/LibreSprite AI.app"
bash "$PACKAGE/mcp/doctor.sh"
```

Default diagnostics must not launch/connect/resume, create files or modify the
package; absent runtime paths are warnings. A valid ad-hoc signature is a warning,
not publisher authentication. Review the manifest/plist minimum macOS version,
bundled `@loader_path` dependencies and runtime SDL3 alias; no Homebrew or checkout
library fallback should remain. The manifest records source hashes/commit/dirty
state and corresponding source/notices, excluding artwork/runtime/personal config.
Verify the v0.9.0 folder and ZIP integrity separately; don't replace them.

## Test the actual packaged executable and production launcher

These tests each create their own editor/socket/generated assets. Never point
them at a user editor or asset root. The tests need the source checkout's test
dependencies, but the packaged editor/server must load their executable,
resources, native libraries and production npm dependencies from the relocated
folder. Clear `LIBRESPRITE_EXECUTABLE` when testing the packaged launcher so a
development override cannot accidentally select the wrong app.

```sh
LIBRESPRITE_EXECUTABLE="$PACKAGE/LibreSprite AI.app/Contents/MacOS/libresprite" \
  python3 scripts/smoke-test-libresprite.py
LIBRESPRITE_EXECUTABLE="$PACKAGE/LibreSprite AI.app/Contents/MacOS/libresprite" \
  python3 scripts/test-live-bridge.py
env -u LIBRESPRITE_EXECUTABLE LIBRESPRITE_MCP_ROOT="$PACKAGE/mcp" \
  node scripts/demo-inspection.mjs
env -u LIBRESPRITE_EXECUTABLE LIBRESPRITE_MCP_ROOT="$PACKAGE/mcp" \
  node scripts/demo-correction.mjs
env -u LIBRESPRITE_EXECUTABLE LIBRESPRITE_MCP_ROOT="$PACKAGE/mcp" \
  node scripts/demo-pixel-regions.mjs
```

The real-MCP demos deliberately leave NEW generated editors **paused/open and
disconnected** with endpoint/PID/IDs recorded in `.runtime/…/review.json`.
They do not restart existing editors. The full Python GUI suite closes only its
own disposable editor. Recheck package hashes/signatures after the tests.

## Review checklist

1. Launch the relocated app without MCP. Check menus/resources/icon load and no
   bridge is enabled. Preferences/recovery remain in the package-specific
   `~/Library/Application Support/LibreSprite AI MCP/` namespace, not stock
   LibreSprite's. No file association or installation is performed.
2. Confirm the production launcher selects the sibling app, reports bridge
   v0.12.0 and 67 tools, and starts paused. Explicitly resume only that generated
   editor; pause before any manual work. Existing editors/artwork stay untouched.
3. Review inspection PNGs and JSON: isolated/scoped/hidden previews, exact frame
   differences, pingpong order/timing and GIF timing diagnostics preserve live
   flags, GUI mask/focus, save state and history while paused.
4. Review correction before/after/Undo sheets: one Undo per pixel/region batch,
   dry-run/apply count/bounds agreement, hidden-layer/GUI-mask/timing preservation.
5. Review raw pixel rows, source mask and stamped part previews. The seeded mask
   excludes the disconnected study pixel; PNG and native sources agree. One Undo
   removes all three frame stamps; one Redo restores them. See
   [the feature checklist](testing-v0.12.md) for details.
6. In packaging mode the pixel-region demo also tests both correction tools then
   undoes them, runs paused scoped diff/timing diagnostics, and exports PNG,
   sprite sheet, GIF and APNG. Verify generated output and unchanged source/GUI
   state. The full GUI suite additionally tests refusals and native save/reopen.
7. Verify disconnect leaves the editor paused/open. Do not overwrite personal MCP
   settings: use a separate test client/entry. Existing clients/windows retain
   their old catalogs/bridges until explicitly refreshed/launched.
8. Verify the source archive/notices and absence of private artwork/configuration.
   Retain corresponding source and license materials with any distributed copy.
   A local launch does not establish downloaded-ZIP Gatekeeper acceptance, support
   for older macOS/Intel, notarization or binary-release publication.

See [packaging/setup](packaging.md) for prerequisites, loader/source/license
semantics, runtime defaults and Gatekeeper guidance. Installing the app, migrating
client configuration or uploading a binary release requires a separate request.
