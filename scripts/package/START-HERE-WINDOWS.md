# LibreSprite AI MCP — Windows x64 private review package

Independent modified LibreSprite, not an official LibreSprite release. This
unsigned package is **private-review-only** pending the third-party license and
corresponding-source audit. Do not publicly redistribute it. Windows 11 x64 is
the initial review target. Only run a package whose source/origin you trust.

1. Extract the whole folder into a location you control; keep the executable,
   DLLs, `data/`, `mcp/`, `.agents/`, docs, licenses and sources together.
2. Run `doctor.cmd` in a terminal for read-only diagnostics.
3. Run `start-mcp.cmd --setup` for client/artwork selection, a configuration preview,
   and optional confirmed JSON settings installation. Node is bundled; no external
   Node, MSYS2, npm, compiler or administrator access is needed to run the package.
4. Read [the setup guide](docs/setup.md) for client settings locations, first-sprite
   verification and portable skills. Reload only the client you configured, when
   safe. An external MCP client and image-capable model are still required.

Setup does not launch/connect/resume an editor, install an application or restart
clients. One writer per editor: never connect to another agent's active session.
Opening `LibreSprite-AI.exe` manually is ordinary editing without AI access; let
the agent launch a new bridge-enabled window when ready. Editing starts paused.
Start with disposable artwork copies, respect local Pause, and save native files.

Assets default to `%USERPROFILE%\Pictures\LibreSprite AI MCP`; preferences and
recovery use `%APPDATA%\LibreSprite AI`, separate from stock LibreSprite.
`doctor.cmd --connect` is an explicit diagnostic connection that pauses the editor
on disconnect: **do not use it against an active agent's session**.

See [Windows details](docs/windows.md), [live workflow/safety](docs/live-bridge.md),
[credits](licenses/CREDITS.md), and the included corresponding project source in
`sources/`. Integrity checking with Python is optional:
`python verify-package.py`. Checksums do not authenticate the publisher.
