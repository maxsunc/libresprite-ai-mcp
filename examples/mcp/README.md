# MCP client configuration examples

Build the native editor and run `npm ci` and `npm run build` first; see the
[build guide](../../docs/building.md) and [live workflow](../../docs/live-bridge.md).
These templates contain no credentials or machine-specific home directories.

Replace `/absolute/path/to/libresprite-ai-mcp` with the absolute path to your
checkout. The server finds its editor, runtime directory, and asset root relative
to its own installation, not the client's working directory. `node` must be
available in the client's environment; use its absolute path if necessary.

## Generic stdio clients

[`stdio.json`](stdio.json) uses the common `mcpServers` format. Client-specific
configuration locations and schemas vary: merge the server entry into the
appropriate file rather than replacing your entire configuration.

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
