# Apple Silicon packaging and setup

v0.9.0 packaging was **user-tested and approved on 2026-10-09**, but this is not a
published, notarized app release. Native-CI/Linux work was skipped at the user's
request. Existing macOS/Ubuntu MCP/helper CI is unchanged. Binary publication and
Developer ID signing/notarization require separate authorization.

Examples below show the approved v0.9.0 package layout. The builder uses the
current source version for new output names. v0.10.0 inspection features require
a newly built editor/MCP pair; the existing local v0.9.0 package was not replaced.

## Build a package

On native Apple Silicon macOS, install the prerequisites in [building.md](building.md),
Node.js 20+, Python 3, and run `npm ci`. Then:

```sh
npm run package:macos
# Or choose a NEW output directory:
python3 scripts/package-macos.py --output "build/packages/my-review"
```

The helper always rebuilds TypeScript and the native editor. It requires the
macOS command-line tools (`otool`, `lipo`, `install_name_tool`, `strip`, `codesign`,
`sips`, `iconutil`, `ditto`) and Homebrew-built native dependencies. It installs
nothing and never closes/restarts existing editors. It refuses an existing output
directory, ZIP, or checksum file rather than replacing them. It uses an isolated
staging directory and installs **production-only** npm packages from the lockfile
with lifecycle scripts disabled. Network access is needed for npm and matching
FreeType/LZ4 source (checksum-verified, cached under ignored `.cache/packaging-source/`).

Outputs under `build/packages/` (ignored/private until explicitly published):

```text
libresprite-ai-mcp-0.9.0-macos-arm64/
  LibreSprite AI.app/
    Contents/MacOS/libresprite
    Contents/Frameworks/         # complete non-system dynamic library closure
    Contents/Resources/data/     # native editor resources
    Contents/Resources/Licenses/
    Contents/Resources/package-manifest.json
  mcp/                          # compiled server + production node_modules
    start-mcp.sh
    doctor.sh
  sources/                      # exact project snapshot, FreeType/LZ4, recipes/manifest
  docs/
  examples/                     # source-build client templates; adapt command below
  START-HERE.md
  checksums.json
  verify-package.py
libresprite-ai-mcp-0.9.0-macos-arm64.zip
libresprite-ai-mcp-0.9.0-macos-arm64.zip.sha256
```

Libraries are copied independently, rewritten to `@loader_path` references,
stripped of debug data, and ad-hoc signed. System frameworks/libraries are not
copied. No external search-path fallback is retained. Homebrew's `sdl2-compat`
loads SDL3 dynamically, so the packager explicitly includes SDL3 and its local
`libSDL3.dylib` alias. Unknown provenance, unreviewed dependency licenses, missing
libraries/licenses, basename collisions, wrong architectures, and unresolved
dependencies fail the build.

The bundle declares the **maximum minimum macOS version across all Mach-O files**,
not just the editor. Current Homebrew libraries on this machine require **macOS
26.0 or newer**. This is not a claim of support on earlier macOS releases or Intel.
Building against an appropriately older dependency set may lower that minimum;
changing `Info.plist` alone cannot. Reproducibility here means a repeatable,
auditable process with pinned source/lockfile, exact installed dependency recipes,
hashes, and toolchain metadata—not bit-identical output across different SDKs or
moving Homebrew versions. The installed recipes are used, not current formula API
versions. Native build flags map this checkout's source paths to relative paths.

## Use outside the checkout

Extract/keep the whole folder in a location you control. Double-click the app for
ordinary editing (no bridge). The distinct bundle identifier is
`io.github.maxsunc.libresprite-ai-mcp`; preferences, palettes, recovery sessions,
and user resources live under `~/Library/Application Support/LibreSprite AI MCP/`.
The unbundled development build retains its upstream preference directory.
No document associations are registered and stock LibreSprite is not replaced.

MCP configuration: run `bash` with one argument:
`/absolute/path/to/package/mcp/start-mcp.sh`. If the client does not inherit your
Terminal PATH, set `LIBRESPRITE_NODE` to an absolute Node.js executable. Node.js
is deliberately not bundled; no npm install is needed to run the packaged server.
The existing source-build examples use `node dist/index.js`; replace that command
with the launcher above for this package. Merge settings; do not replace personal
configuration. If moving only the app to `/Applications`, explicitly set
`LIBRESPRITE_EXECUTABLE=/Applications/LibreSprite AI.app/Contents/MacOS/libresprite`.
Keep MCP outside the `.app` so neither runtime files nor configuration invalidate
its signature.

Packaged defaults (overrides retain their existing meanings):

| Setting | Default |
| --- | --- |
| `LIBRESPRITE_EXECUTABLE` | sibling `LibreSprite AI.app/Contents/MacOS/libresprite` |
| `LIBRESPRITE_ASSET_ROOT` | `~/Pictures/LibreSprite AI MCP/` |
| `LIBRESPRITE_SOCKET` | `os.tmpdir()/lsai-<uid>/b.sock` in a private 0700 directory |
| `LIBRESPRITE_NODE` | `node` on the client's PATH (launcher only) |

Launch creates the socket parent/assets if absent. It refuses unsafe permissions,
overlong socket paths, or existing endpoints; never remove an endpoint without
confirming it is stale and belongs to this instance. Start with copies of artwork.
Use `libresprite_launch` → `libresprite_connect` → explicitly resume, and pause
before manual work. A launched editor stays open when MCP disconnects.

## Diagnostics and integrity

```sh
bash "/path/to/package/mcp/doctor.sh"
# From source (build TypeScript first):
npm run doctor
```

Diagnostics check Node/platform, executable access, resources/manifest/macOS
minimum, ad-hoc signature, native library load commands, socket path/ownership/
mode, and asset-root access. **They never execute the editor**: upstream even
initializes preferences/palettes for `--version`. Mach-O commands are parsed by
the server itself, so diagnostics don't require Xcode/command-line tools.
Absent runtime directories/endpoints are warnings, not
errors. Exit status is nonzero when an error is found. No files are created,
permissions changed, sockets removed, or editing resumed. Diagnostic output
includes local paths; review/redact it before sharing.

Optional `doctor.sh --connect` reads native status and checks the bridge version.
It must not be used while an agent is actively editing: only one connection is
allowed, and closing the diagnostic connection **pauses the editor**. This is an
explicit opt-in side effect, never part of default diagnostics. It doesn't resume
or retry operations. `--doctor` is CLI functionality, not another MCP tool. The
approved v0.9.0 package has 59 tools; see [the live guide](live-bridge.md) for the
current source catalog.

```sh
python3 "/path/to/package/verify-package.py"
codesign --verify --deep --strict "/path/to/package/LibreSprite AI.app"
shasum -a 256 -c "/path/to/libresprite-ai-mcp-0.9.0-macos-arm64.zip.sha256"
```

Run the ZIP checksum from the directory containing the ZIP. The file verifier
checks missing/extra/changed files and safe internal symlinks; it tolerates Finder
metadata. These are integrity checks, not publisher authentication. Downloads may
trigger Gatekeeper: use Privacy & Security → Open Anyway **only for a trusted
package**. Do not disable Gatekeeper globally or strip quarantine recursively.
Developer ID signing/notarization needs a separate release decision and account.

## Source and license materials

The package includes the exact allowlisted current source tree, including
uncommitted milestone changes, with per-file hashes and parent commit/dirty
state in the manifest. Private assets/runtime/configuration/builds are excluded.
`sources/libresprite-ai-mcp-source.tar.gz` retains source, all vendored notices,
and build/package scripts. Extract it, install the documented build prerequisites,
run `npm ci`, and `npm run package:macos` to reproduce the procedure. The archive
includes `SOURCE-SNAPSHOT.json` so source enumeration/provenance also works
without a Git checkout. New source files in an extracted archive must be added
to that explicit allowlist before repackaging.

Full FreeType/LZ4 source and their installed build recipes are included. **FreeType is
distributed under its GPLv2 option**, not its GPLv2-incompatible FTL option.
Highway and zstd select BSD license options; only XZ's 0BSD liblzma is bundled.
LZ4 includes the library's full BSD notice, not only the installed summary license.
All installed dependency notices and Homebrew recipes/provenance are retained.
The production Node dependencies carry source/notices. The app's license folder
also preserves project and imported component licenses, fonts/data, contributors,
and the IJG README. This software is based in part on the work of the Independent
JPEG Group. These materials must accompany redistributed binaries; see
[LICENSE.md](../LICENSE.md) and [CREDITS.md](../CREDITS.md). Publishing a release
still requires a final source/license/privacy review and user authorization.
