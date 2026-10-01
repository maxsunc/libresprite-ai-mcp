import { spawn, type ChildProcess } from "node:child_process";
import { closeSync, constants, openSync } from "node:fs";
import { lstat, mkdir, realpath } from "node:fs/promises";
import path from "node:path";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { BridgeClient, BridgeError, type BridgeResult } from "./bridge-client.js";

export interface ServerOptions {
  socketPath: string;
  executable: string;
  assetRoot: string;
}

export function createServer(options: ServerOptions): { server: McpServer; close: () => void } {
  const server = new McpServer({ name: "libresprite-ai-mcp", version: "0.1.0" });
  const bridge = new BridgeClient(options.socketPath);
  // EOF/transport closure is also a disconnect, not just SIGTERM. Closing the
  // local socket makes the native editor pause and lets this process exit.
  server.server.onclose = () => bridge.close();
  let launched: ChildProcess | undefined;
  const documentId = z.number().int().positive().max(2_147_483_647);
  const expectedRevision = z.number().int().positive().max(2_147_483_647);
  const frame = z.number().int().min(0).max(255);
  const channel = z.number().int().min(0).max(255);
  const relativePath = z.string().min(1).max(4096);
  const target = { documentId, expectedRevision };

  async function call(method: string, params: BridgeResult = {}) {
    try {
      const result = await bridge.request(method, params);
      const { pngBase64, ...metadata } = result;
      const content: Array<{ type: "text"; text: string } | { type: "image"; data: string; mimeType: string }> = [
        { type: "text", text: JSON.stringify(metadata, null, 2) },
      ];
      if (typeof pngBase64 === "string") content.push({ type: "image", data: pngBase64, mimeType: "image/png" });
      return { content };
    } catch (error) {
      return failure(error);
    }
  }
  function failure(error: unknown) {
    return {
      isError: true,
      content: [{ type: "text" as const, text: JSON.stringify({ code: error instanceof BridgeError ? error.code : "ERROR", message: error instanceof Error ? error.message : String(error) }) }],
    };
  }

  server.registerTool("libresprite_launch", {
    description: "Launch a NEW visible development editor with the native bridge. Does not attach to or alter ordinary LibreSprite windows. Starts paused. Wait for the window, then call libresprite_connect. Never auto-relaunch after an uncertain edit outcome.",
    inputSchema: {},
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, async () => {
    try {
      if (launched && launched.exitCode === null && launched.signalCode === null) throw new BridgeError("ALREADY_LAUNCHED", "An editor was already launched by this server. Connect to it instead.");
      if (process.platform !== "darwin" && process.platform !== "linux") throw new BridgeError("UNSUPPORTED_PLATFORM", "The first live bridge supports macOS/Linux.");
      const directory = path.dirname(options.socketPath);
      await mkdir(directory, { recursive: true, mode: 0o700 });
      const info = await lstat(directory);
      if (!info.isDirectory() || info.isSymbolicLink() || (info.mode & 0o077) !== 0 || info.uid !== process.getuid?.()) throw new BridgeError("INVALID_SOCKET", "Socket parent must be owned by you with mode 0700.");
      try {
        await lstat(options.socketPath);
        throw new BridgeError("SOCKET_EXISTS", "Endpoint already exists. Connect, or manually remove a confirmed stale endpoint; it will not be replaced.");
      } catch (error) {
        if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) throw error;
      }
      await mkdir(options.assetRoot, { recursive: true });
      const root = await realpath(options.assetRoot);
      // Logs must not follow symlinks or overwrite an existing file. Child stdout
      // must NEVER reach MCP's stdout, which is reserved for JSON-RPC messages.
      const logPath = path.join(directory, `editor-${Date.now()}.log`);
      const log = openSync(logPath, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY, 0o600);
      let child: ChildProcess;
      try {
        child = spawn(options.executable, ["--automation-socket", options.socketPath, "--automation-root", root], {
          stdio: ["ignore", log, log],
          detached: true,
        });
        await new Promise<void>((resolve, reject) => { child.once("spawn", resolve); child.once("error", reject); });
      } finally { closeSync(log); }
      launched = child;
      // Leave the editor and unsaved work open when the MCP server disconnects.
      child.unref();
      return { content: [{ type: "text" as const, text: JSON.stringify({ pid: child.pid, socketPath: options.socketPath, assetRoot: root, logPath, next: "Wait for the visible window, then call libresprite_connect. Bridge starts paused." }, null, 2) }] };
    } catch (error) { return failure(error); }
  });
  server.registerTool("libresprite_connect", {
    description: "Connect/reconnect and inspect session ID, paused state, and asset root. Does not resume editing. Reconnect after a timeout and inspect the document instead of blindly repeating an edit.",
    inputSchema: {}, annotations: { readOnlyHint: true, openWorldHint: false },
  }, () => call("status"));
  server.registerTool("libresprite_set_paused", {
    description: "Pause or explicitly resume agent edits. Pause before manual editing. Disconnect also pauses the bridge. Reads remain available while paused; busy GUI gestures/dialogs are refused.",
    inputSchema: { paused: z.boolean() }, annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("set_paused", params));
  server.registerTool("libresprite_list_documents", {
    description: "List documents, IDs, dimensions, frame counts, and the active document in this connected editor only.",
    inputSchema: {}, annotations: { readOnlyHint: true, openWorldHint: false },
  }, () => call("list_documents"));
  server.registerTool("libresprite_inspect", {
    description: "Inspect document revision, layers/cels, zero-based frames and durations, palettes, tags, and undo state. Use its revision for subsequent edits. IDs are local to this editor session.",
    inputSchema: { documentId }, annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("inspect", params));
  server.registerTool("libresprite_render", {
    description: "Return an actual composited PNG image plus metadata for a zero-based frame. Nearest-neighbor scale preserves pixel edges. At most 1,048,576 output pixels. Includes revision; no file is written.",
    inputSchema: { documentId, frame, scale: z.number().int().min(1).max(16).default(1) }, annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("render", params));
  server.registerTool("libresprite_create", {
    description: "Create and visibly select a new transparent RGBA sprite with one layer/frame. Requires resumed bridge. Existing documents are left open; creation itself is not an undo step.",
    inputSchema: { width: z.number().int().min(1).max(1024), height: z.number().int().min(1).max(1024), name: z.string().min(1).max(120).default("AI Sprite") }, annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("create", params));
  server.registerTool("libresprite_open", {
    description: "Open and visibly select a PNG/.ase/.aseprite inside the configured asset root. Relative path only; symlink escapes are refused. Requires resumed bridge. Unsupported modern Aseprite chunks may not round-trip losslessly.",
    inputSchema: { path: relativePath }, annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("open", params));
  server.registerTool("libresprite_set_pixels", {
    description: "Apply an atomic, undoable RGBA pixel batch to an explicit layer/frame in the ACTIVE document. Coordinates are canvas pixels, colors replace pixels (not alpha-blended), duplicates use the last color. Requires current revision and resumed bridge. Refuses locked/background layers and linked cels. Does not apply the selection mask. Render after editing to inspect the result.",
    inputSchema: { ...target, layerId: documentId, frame, label: z.string().min(1).max(120).default("AI pixel edit"), pixels: z.array(z.object({ x: z.number().int().min(0).max(1023), y: z.number().int().min(0).max(1023), r: channel, g: channel, b: channel, a: channel })).min(1).max(16384) }, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("set_pixels", params));
  for (const operation of ["undo", "redo"] as const) server.registerTool(`libresprite_${operation}`, {
    description: `${operation === "undo" ? "Undo" : "Redo"} one native undo transaction in the active document. Requires its current revision and resumed bridge. May affect manual edits as well as agent edits.`,
    inputSchema: target, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call(operation, params));
  server.registerTool("libresprite_save", {
    description: "Atomically save the active document as .ase/.aseprite inside the asset root. Relative path and current revision required. Existing files are refused unless overwrite is explicitly true. Preserves native layers/frames supported by LibreSprite.",
    inputSchema: { ...target, path: relativePath, overwrite: z.boolean().default(false) }, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("save", params));

  return { server, close: () => bridge.close() };
}
