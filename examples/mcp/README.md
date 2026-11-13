# MCP client configuration examples

Build the native editor and run `npm ci` and `npm run build` first; see the
[build guide](../../docs/building.md) and [live workflow](../../docs/live-bridge.md).
These templates contain no credentials or machine-specific home directories.
Windows portable-package users can skip the source-build prerequisites and use
the bundled Node runtime as described below.

Replace `/absolute/path/to/libresprite-ai-mcp` with the absolute path to your
checkout. The server finds its editor, runtime directory, and asset root relative
to its own installation, not the client's working directory. `node` must be
available in the client's environment; use its absolute path if necessary.

## Generic stdio clients

[`stdio.json`](stdio.json) uses the common `mcpServers` format. Client-specific
configuration locations and schemas vary: merge the server entry into the
appropriate file rather than replacing your entire configuration.

## Windows portable package

[`windows-stdio.json`](windows-stdio.json) points directly at the bundled Windows
Node runtime and server. Replace `C:\\Tools\\LibreSprite-AI` with the extracted
folder's absolute path; no separately installed Node is needed. See
[the Windows guide](../../docs/windows.md) for build/review limits and startup.

## Pi

Use Pi's built-in MCP support and merge a `mcpServers.libresprite` entry into
`~/.pi/agent/mcp.json` for all projects, or `.pi/mcp.json` for one trusted project.
Use [`stdio.json`](stdio.json) for a source build or
[`windows-stdio.json`](windows-stdio.json) for the Windows portable package.
Replace the placeholder paths; optionally add `env.LIBRESPRITE_ASSET_ROOT` to
scope artwork to a folder of your choice.

Set `"exposure": "deferred"` on the server entry so Pi discovers tools when
needed. Run `/reload`, then `/mcp`; `pi mcp list` also checks the connection from
a terminal. A connected current server advertises **70 tools**. Pi starts the
MCP server automatically, but the agent must explicitly launch/connect/resume the
editor before editing. See the [README's complete Pi setup and example prompt](../../README.md#use-with-pi).

An extension replacing Pi's `/mcp` command overrides the built-in configuration;
remove that replacement to use these instructions. Keep personal `.pi/mcp.json`
files out of version control, especially if they contain credentials for other
servers.

## OpenCode V2

[`opencode.json`](opencode.json) uses V2's `mcp.servers` structure. Merge that
entry into your project or global `opencode.json(c)`, preserving other settings.
The server connects automatically; configuring it does **not** automatically
launch or resume the editor.

Alternatively, from the checkout, add the project-local server with the CLI:

```sh
opencode mcp add libresprite -- node /absolute/path/to/libresprite-ai-mcp/dist/index.js
opencode mcp list
```

Add `--global` before `--` only if you want this server in every project. Use
`/mcps` to inspect or manage the connection. The template follows the
[OpenCode V2 MCP documentation](https://opencode.ai/v2/docs/mcp-servers).
It does not alter this checkout's existing personal configuration.

## First editing session

1. `libresprite_launch` opens a new bridge-enabled editor, initially paused.
2. Wait for the window, then call `libresprite_connect`.
3. Explicitly resume with `libresprite_set_paused` (`paused: false`).
4. Create/open a sprite; inspect its IDs and revision before editing.
5. Render to verify edits, save a native sprite, and pause before manual work.

Connect to an existing bridge-enabled editor instead of launching another one
when appropriate. Ordinary LibreSprite windows cannot be attached to this bridge.
After rebuilding server/native code, refresh the client tools and use a new
development editor when ready; do not close unsaved work to upgrade automatically.
