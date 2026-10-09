# LibreSprite AI MCP — Apple Silicon review package

An independent modified LibreSprite build, not an official LibreSprite release.
No installer, administrator access, Homebrew, or native compiler is needed to run
the editor. **Node.js 20+ is required for MCP.** See the package manifest for the
minimum macOS version; it is the highest requirement of the bundled libraries.

1. Keep the extracted folder together in a writable location you control.
   Double-click **LibreSprite AI.app** for ordinary editing without agent access.
   The app has its own identifier and preferences/recovery directory at
   `~/Library/Application Support/LibreSprite AI MCP/`; stock LibreSprite is not
   replaced and file associations are not registered.
2. Run `bash "/absolute/path/to/package/mcp/doctor.sh"` in Terminal. No GUI is
   launched and no files are changed. The signature is ad-hoc, **not notarized**;
   a downloaded app may require macOS Privacy & Security → Open Anyway. Only
   approve a package whose source and origin you trust; do not disable Gatekeeper.
3. Configure your MCP client to run `bash` with the single argument
   `/absolute/path/to/package/mcp/start-mcp.sh`. Set `LIBRESPRITE_NODE` to an
   absolute Node executable if the client lacks your shell's PATH. Merge settings
   into your existing configuration; nothing here changes it automatically.
4. Ask the agent to call `libresprite_launch` → `libresprite_connect` → explicitly
   resume. This opens a **new** opt-in window; it does not attach to the ordinary
   window from step 1. Editing starts paused. Pause before manual work; a local
   editor Pause cannot be remotely overridden.

Default MCP assets: `~/Pictures/LibreSprite AI MCP/`. Default socket: the system
temporary directory's private `lsai-<uid>/b.sock`. Launch creates these when
needed. `LIBRESPRITE_ASSET_ROOT`, `LIBRESPRITE_SOCKET`, and
`LIBRESPRITE_EXECUTABLE` override defaults. If you move just the `.app` to
`/Applications`, set `LIBRESPRITE_EXECUTABLE` to its `Contents/MacOS/libresprite`.
No artwork or runtime logs are stored inside the package.

`doctor.sh --connect` is optional: it briefly connects to the configured editor
and reads status/version. **Closing that connection pauses the editor**; it can
also be refused when another client is connected. Default diagnostics never
connect, resume, retry edits, or remove stale sockets.

Optional integrity checks (Python 3 / macOS built-in tools):

```sh
python3 "/absolute/path/to/package/verify-package.py"
codesign --verify --deep --strict "/absolute/path/to/package/LibreSprite AI.app"
```

The ZIP's adjacent `.sha256` file checks the archive as a whole. These checks do
not authenticate a publisher. This review package is not a signed public release.

## Source and notices

Read `docs/packaging.md`, `docs/testing-v0.9.md`, and `docs/live-bridge.md`.
`sources/` contains the exact project source snapshot, build instructions,
dependency provenance/installed Homebrew recipes, and matching FreeType/LZ4 source
(FreeType uses its GPLv2 license option). The app carries full project,
upstream, and library notices in `Contents/Resources/Licenses/`. Highway and zstd
use their BSD options; only XZ's 0BSD liblzma is bundled, not its CLI tools.
The production MCP dependencies include their own source and notices.

This software is based in part on the work of the Independent JPEG Group.
LibreSprite, the original GPL-era Aseprite authors, and dependency contributors
are credited in the included notices. Artwork is separately owned/licensed.
Keep the source/notices alongside any redistributed binary; see `LICENSE.md`
inside the source archive before publishing. No private artwork is included.
