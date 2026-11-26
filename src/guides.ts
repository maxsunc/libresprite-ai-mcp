// GPL-2.0-only. Shared onboarding for any MCP client; no agent-specific APIs.
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

export const SERVER_INSTRUCTIONS = `Use this local, visible LibreSprite editor with one writer per editor. Connect to an existing bridge-enabled editor when available; otherwise call libresprite_launch, wait for the window, then libresprite_connect. Editing starts paused: resume with libresprite_set_paused(paused:false) only with user authorization. Never override a local user pause. Inspect current document/layer IDs and revisions before edits. Render PNG results to verify work; visual review requires an image-capable client/model. Save native artwork inside the configured asset root, using copies and unique filenames. After timeouts/disconnects, reconnect and inspect instead of blindly retrying mutations. A normal manually launched window cannot be attached retroactively. Do not connect a second agent or diagnostic client to an editor owned by another agent. For animation, read the optional MCP resource libresprite://skills/pixel-animation or the shared .agents/skills/pixel-animation/SKILL.md. Deferred/conflict results are not queued edits; inspect/replan. Setup never grants permission to resume.`;

export function guideRoot(root: string): string {
  return existsSync(path.join(root, "package-layout.json")) ? path.dirname(root) : root;
}

export function registerGuides(server: McpServer): void {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  server.registerResource("getting-started", "libresprite://guides/getting-started", {
    description: "Safe first-session workflow for any LibreSprite MCP agent.", mimeType: "text/markdown",
  }, async (uri) => ({ contents: [{ uri: uri.href, mimeType: "text/markdown", text: SERVER_INSTRUCTIONS }] }));
  server.registerResource("pixel-animation", "libresprite://skills/pixel-animation", {
    description: "Optional portable pixel-animation skill: key poses, timing, evidence-based review and bounded correction passes.", mimeType: "text/markdown",
  }, async (uri) => ({ contents: [{ uri: uri.href, mimeType: "text/markdown",
    text: await readFile(path.join(guideRoot(root), ".agents/skills/pixel-animation/SKILL.md"), "utf8") }] }));
}
