# Packaging / v0.9.0 review

Steps 1–3 and the packaging milestone were user-approved. Packaging was tested
and approved on **2026-10-09**; this checklist remains available for regression
review. This milestone packages Apple Silicon macOS only. **Native-CI/Linux work
was skipped, not implemented.**
No app is installed, no existing editor is restarted, and no private artwork or
personal client configuration is included in the package.

## Review checklist

1. Copy/extract the entire package folder to a location **outside the checkout**,
   including a path with spaces. Verify `checksums.json` and the ad-hoc signature.
   Confirm the package's minimum macOS version matches your Mac (current build:
   26.0+, Apple Silicon). Do not change the plist to bypass OS requirements.
2. Double-click `LibreSprite AI.app` without MCP. Confirm menus/resources/icon
   load, no AI bridge is enabled, and it doesn't replace stock LibreSprite.
   Preferences/recovery should use `~/Library/Application Support/LibreSprite AI MCP/`.
3. Run `bash /path/to/package/mcp/doctor.sh`. Confirm no files are created by
   diagnostics, missing endpoint/directories are warnings, and Node/permissions/
   resource errors include actionable detail. Node.js 20+ is a runtime prerequisite.
4. Configure a **separate** MCP entry or test client with
   `bash /path/to/package/mcp/start-mcp.sh`. Do not replace your working entry.
   Use a short private socket path and a fresh generated-only asset directory.
5. Launch a new editor through MCP, connect, and verify v0.9.0 and paused state.
   Explicitly resume, create a disposable sprite, paint pixels, add layers/frames,
   change timing, and verify native Undo/Redo. Save `.ase`, export PNG/GIF/APNG,
   reopen, and compare rendered content/timing.
6. Pause in the editor and confirm remote resume is refused until local Resume.
   Disconnect the client: the editor must pause and remain open. Existing editors
   and original artwork must stay untouched. Default diagnostics must not connect.
7. Test an unavailable executable, overlong socket, unsafe socket parent, and
   existing endpoint: fail clearly; do not silently replace/relaunch/retry.
8. Verify the package source archive, dependency versions/notices, and absence of
   artwork/logs/personal config. Check that native loading has no Homebrew or
   checkout dependency (the builder audits static linkage; review checks runtime
   SDL3 loading too).

To reproduce automated local checks:

```sh
npm test
python3 -m unittest discover -s tests -v
npm run package:macos
```

To point existing disposable native tests and the visible MCP crystal demo at a
**relocated** package (do not use an existing user socket):

```sh
LIBRESPRITE_EXECUTABLE="/path/to/package/LibreSprite AI.app/Contents/MacOS/libresprite" \
  python3 scripts/smoke-test-libresprite.py
LIBRESPRITE_EXECUTABLE="/path/to/package/LibreSprite AI.app/Contents/MacOS/libresprite" \
  python3 scripts/test-live-bridge.py
LIBRESPRITE_MCP_ROOT="/path/to/package/mcp" node scripts/demo-editing.mjs
```

The demo uses the actual packaged launcher/production server and a fresh private
socket/generated-only root. It exports an extra APNG in packaging mode, then
leaves generated RGBA/indexed crystals **paused** for review. Ctrl+C disconnects
and leaves the editor open. It never edits existing artwork or personal config.

Full source-native GUI tests remain available, but adding a new CI/platform
milestone is deliberately outside this request. Ad-hoc signing is not notarization;
a local launch test does not prove Gatekeeper acceptance of a downloaded ZIP or
support on another OS version. Source commit/push was authorized after review;
binary publication and signing/notarization require separate authorization.
