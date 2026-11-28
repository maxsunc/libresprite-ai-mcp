# Set up any local MCP agent

LibreSprite AI MCP speaks **standard MCP over stdio**, not a Pi-specific API.
Use an agent that can start a local stdio process. To see rendered previews, its
client **and model** must support MCP image results. An HTTP-only/cloud client
cannot connect directly; there is no HTTP/SSE service or remote installer.
An agent without MCP needs its own adapter. Configuration support below does
not claim that every named client/version has been tested end to end.

## 1. Get the editor and server

This is still a **source alpha**: there are no public binary downloads or npm/npx
installer. The modified native editor is required; stock LibreSprite cannot be
attached. Setup configures a built checkout or an existing trusted review package;
it does not download dependencies, compile the editor, publish binaries, or bypass
signing/license restrictions. **Review packages must be rebuilt from this source
change** to include `--setup` and the shared guide resources. Retained older
packages are not upgraded; use their manual configuration templates instead.

- **Source:** follow [building.md](building.md) or [windows.md](windows.md), then
  run `npm ci`, `npm run build`, and build the native editor. Node.js 20+ is required.
- **Windows x64 review package:** keep the entire extracted folder together.
  Node is bundled; no npm, compiler or administrator access is needed to run it.
- **Apple Silicon review package:** keep the folder together and install Node.js
  20+. See [packaging.md](packaging.md) for macOS minimum/signing restrictions.
- **Linux:** local transport exists, but the full native workflow is not validated
  and no Linux package is provided. Intel Mac/Windows ARM64 packages are not provided.

## 2. Run the setup wizard

From a **built source checkout**:

```sh
npm run setup
```

Windows **review package**, from a terminal:

```bat
"C:\Tools\LibreSprite-AI\start-mcp.cmd" --setup
```

macOS **review package**:

```sh
bash "/path/to/package/mcp/start-mcp.sh" --setup
```

Choose a client and artwork folder. The wizard prints configuration with the
absolute Node executable actually running setup, the server path, and explicit
artwork/editor/endpoint settings. Windows packages therefore use bundled Node;
macOS/source users avoid a GUI client's missing shell PATH. Keep this installation
in place; **rerun setup after relocating it**. Changed settings require manual
review if an older `libresprite` entry already exists.

Setup runs read-only diagnostics, never executes the editor and **never connects
to its bridge**, even if another agent is already editing. Missing artwork/runtime
directories are warnings: the editor creates them later. Errors block settings and
skill installation; fix the reported build/path/permission problem and rerun.
Native dependencies are checked only to the extent supported by the existing
doctor; a successful setup is not a complete GUI/DLL validation.

After successful checks, enter your client's JSON settings path to install, or
leave it blank for a preview only. Writing requires a separate **yes** confirmation.
Setup never guesses a personal settings file, changes project trust, auto-approves
tools, or restarts/reloads a client.

### Non-interactive setup / configuration preview

```sh
npm --silent run setup -- --client cursor --asset-root "/absolute/path/to/artwork"
```

Use `npm --silent` (or invoke `node dist/index.js --setup` directly) when piping
the preview to a file: normal npm script banners are not part of JSON/TOML.
This only prints config to stdout and checks/status to stderr. No settings,
artwork, sockets, skills, or preference directories are created. Diagnostic errors
still return a preview but exit nonzero. `--help` lists the options.

Explicit JSON installation (back up your own settings as usual):

```sh
npm run setup -- --client cursor --asset-root "/absolute/path/to/artwork" --config "/absolute/path/to/.cursor/mcp.json" --write
```

For packages, append these same options after `--setup` on their launcher.
Use absolute paths, or `~/...` (expanded by setup); relative paths resolve against
the terminal's current directory, not the installation directory.

### Client profiles and settings locations

| `--client` | Generated format | Typical destination / scope |
| --- | --- | --- |
| `generic` | `mcpServers.libresprite` JSON | Any client using this common shape; choose its settings file |
| `claude-code` | `mcpServers.libresprite` JSON | Target project's `.mcp.json`; approve project MCP configuration in Claude Code |
| `claude-desktop` | `mcpServers.libresprite` JSON | macOS `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows `%APPDATA%/Claude/claude_desktop_config.json` |
| `cursor` | `mcpServers.libresprite` JSON | `~/.cursor/mcp.json` (user) or target project's `.cursor/mcp.json` |
| `gemini` | `mcpServers.libresprite` JSON | `~/.gemini/settings.json` or target project's `.gemini/settings.json` |
| `pi` | `mcpServers.libresprite`, deferred exposure | `~/.pi/agent/mcp.json` or target project's `.pi/mcp.json` |
| `vscode` | `servers.libresprite`, `type: stdio` | Target project's `.vscode/mcp.json`, or VS Code's user-profile MCP configuration |
| `opencode-v2` | `mcp.servers.libresprite`, local command array / `environment` | Project/global `opencode.json`; specifically the V2 format used by this repo's example |
| `codex` | `[mcp_servers.libresprite]` and `.env` TOML tables | `~/.codex/config.toml` or trusted project's `.codex/config.toml`; **preview/manual merge only** |

`~` means your user home, not a literal folder. In Windows terminals that do not
expand `%APPDATA%`, supply the real absolute path. For OpenCode versions with a
different configuration schema, adapt the local command array and environment to
that version's documented MCP location; do not install the V2 profile blindly.
For other agents, use `generic`, then adapt the server entry to the client's schema.
Agent Skills support is independent of MCP support.

Codex preview:

```sh
npm --silent run setup -- --client codex --asset-root "/absolute/path/to/artwork"
```

Merge the **two printed tables** into the chosen TOML file, without duplicating
existing tables. TOML and JSONC are deliberately not rewritten by this helper:
no parser dependency or risky comment-stripping conversion is used.

### Settings-write safeguards

- `--write` always requires an explicit `--config` path; `--config` alone is an
  error, not an implicit write. `--skill-dir` is separate explicit permission.
- Only a `libresprite` server entry is added. Other settings/servers are preserved.
  An identical entry is a no-op; a different entry is refused, not silently replaced.
- Existing strict JSON is reformatted. Comments/JSONC, malformed JSON, invalid
  containers, symlinks and non-regular settings files are refused. Merge the
  generated preview yourself when your client uses those formats.
- Before replacing existing JSON, setup writes an exact-byte
  `<settings>.<unique-id>.bak` backup. Files use mode 0600 where supported;
  **Windows inherits the chosen folder's ACL**, so choose a user-private settings
  folder, not a shared directory. Temporary files are published atomically; new
  destinations are never overwritten. Keep backups private: they may contain
  other servers' credentials.
- A sibling `.libresprite-setup.lock` prevents simultaneous setup writers. A
  changed file detected before publication is refused. **Close settings editors
  and stop other processes from rewriting this file during installation**; this
  is not a transaction with an arbitrary client's own settings writer. Setup does
  not stop a client for you. Remove a leftover lock only after confirming no setup
  process is running. Restore a backup manually while the client is closed.
- Settings and optional skill installation are separate actions, not a combined
  transaction. If skill installation fails, a successful settings merge remains.

Review local paths before sharing setup output. No telemetry, credentials, PATH
changes, app installation, or client auto-restart are involved.

## 3. Verify and make the first sprite

Reload/restart **only the client you just configured, when safe**. Check its MCP
status for `libresprite` and **70 tools**. Pi: `/reload`, then `/mcp`; OpenCode V2:
`/mcps`. Other clients have their own approval/status UI. Seeing tools proves the
server connection, not image support or the native editor workflow.

Give any agent this prompt:

> Use LibreSprite MCP. If this editor is already owned by another agent, stop
> rather than connecting to it. Otherwise connect to an available bridge-enabled
> editor, or launch a new one and wait for its window. I authorize explicitly
> resuming agent editing. Create a new 16×16 slime sprite, render its PNG preview,
> and save it with a unique `.ase` filename inside the configured artwork folder.
> Preserve existing artwork and respect the editor's Pause button.

The server advertises agent-neutral onboarding instructions during MCP initialize.
Clients supporting MCP resources can also read:

- `libresprite://guides/getting-started`
- `libresprite://skills/pixel-animation`

There is still **one writer/bridge client per editor**. Do not give a second
process its own native connection to a busy editor. Reading these two static MCP
resources does not itself connect to the native bridge; a read-only reviewer can
use static guides and supplied image evidence without owning the editor.
Do not run `doctor --connect` on someone else's session.

A normal manually opened window has no bridge and cannot be attached retroactively.
Editing starts paused; a pause made in the editor can only be released there.
Never auto-resume or replay an uncertain mutation. See [live-bridge.md](live-bridge.md).

## 4. Optional shared skills

The canonical animation skill now lives at
[`.agents/skills/pixel-animation/SKILL.md`](../.agents/skills/pixel-animation/SKILL.md),
not `.pi/skills/`. Pi and other clients that discover `.agents/skills/` can load it
from this trusted checkout. Discovery paths vary: **no directory is universal**.
For a client that only discovers its own skills directory, explicitly copy it:

```sh
npm run setup -- --client generic --skill-dir "~/.claude/skills"
# Or use ~/.agents/skills, ~/.pi/agent/skills, or your client's configured directory.
```

This copies only `pixel-animation/SKILL.md` into that directory. An identical skill
is left alone; a different existing skill is refused. Existing installations in
`~/.pi/agent/skills` continue to work; project-local `.pi/skills` copies are no longer
maintained. Remove an old duplicate only after checking that it is not customized.
Packages include the same `.agents/skills/` directory beside their `mcp/` folder.

If your client supports neither skill discovery nor MCP resources, ask it to read
that file using its filesystem tools, or paste the contents into its instructions.
For example: “Read `.agents/skills/pixel-animation/SKILL.md` and use that workflow
to animate a staff slam.” Pi also supports `/skill:pixel-animation` after discovery.
Installing a skill does not configure MCP, supply an image-capable model, or grant
permission to edit. Reviewers remain read-only; the main agent is the sole writer.

### Client format references

- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Cursor MCP](https://cursor.com/docs/context/mcp)
- [Gemini CLI MCP](https://geminicli.com/docs/tools/mcp-server/)
- [VS Code MCP](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
- [Codex MCP](https://developers.openai.com/codex/mcp)
- [OpenCode V2 MCP](https://opencode.ai/v2/docs/mcp-servers)
- [Agent Skills specification](https://agentskills.io/specification)

Profiles, merges, read-only setup, static MCP resources and relocated package paths
are regression-tested with the SDK. Individual external clients and all their model
providers/versions are **not** certified by those tests.
