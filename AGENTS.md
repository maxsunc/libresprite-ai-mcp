# LibreSprite AI MCP — agent guide

This project uses standard **local stdio MCP**, not a particular agent SDK.
For setup, client formats, platform limits and skill installation, read
[docs/setup.md](docs/setup.md). Source builds need Node.js 20+ and the modified
native editor; stock LibreSprite is not compatible.

## When using the editor

- Use an image-capable client/model to review rendered PNG tool results.
- Keep one writer per editor. Do not connect to a session owned by another agent.
- Connect to an available bridge-enabled editor, or launch a new one, wait for its
  window, and connect. Resume editing only with the user's authorization.
- Respect the editor's local Pause button. Never auto-resume, kill a window with
  unsaved work, or blindly repeat a mutation after a timeout/disconnect.
- Inspect current document/layer IDs and revisions, verify with renders, and save
  copies under unique names inside the configured artwork root.
- For animation, read [.agents/skills/pixel-animation/SKILL.md](.agents/skills/pixel-animation/SKILL.md).
  Clients without filesystem skill discovery can read MCP resource
  `libresprite://skills/pixel-animation`. MCP also advertises shared onboarding
  instructions and `libresprite://guides/getting-started`.

## When changing this repository

- Use a separate worktree/build when another agent is running this checkout's
  server/editor. Do not rewrite its `dist/`, client settings or running session.
- `npm ci && npm test` builds/tests the TypeScript server. Python helper tests:
  `python -m unittest discover -s tests -v` (some require a native toolchain).
- Default `npm run doctor` and setup are read-only; **do not** use
  `--doctor --connect` against another agent's editor. Live/native tests must use
  their own disposable editor and artwork.
