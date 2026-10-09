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
  const server = new McpServer({ name: "libresprite-ai-mcp", version: "0.8.0" });
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
  const celTarget = { ...target, layerId: documentId, frame };
  const paintTarget = { ...celTarget, respectSelection: z.boolean().default(false) };
  const coordinate = z.number().int().min(0).max(1023);
  const point = z.object({ x: coordinate, y: coordinate });
  const color = z.object({ r: channel, g: channel, b: channel, a: channel });
  const scale = z.number().int().min(1).max(16).default(1);
  const sheet = { frames: z.array(frame).min(1).max(256).optional(), columns: z.number().int().min(1).max(16).optional(), scale, padding: z.number().int().min(0).max(16).default(0) };
  const direction = z.enum(["forward", "reverse", "pingpong"]);
  const tagColor = z.object({ r: channel, g: channel, b: channel, a: z.literal(255) });
  const transform = z.enum(["flip_horizontal", "flip_vertical", "rotate_cw", "rotate_ccw", "rotate_180"]);
  const signedCoordinate = z.number().int().min(-32768).max(32767);
  const frames = z.array(frame).min(1).max(256);
  const dimension = z.number().int().min(1).max(1024);
  const maskMode = z.enum(["replace", "add", "subtract", "intersect"]).default("replace");
  const bits = z.string().min(1).max(262144).regex(/^[01]+$/);
  const blendMode = z.enum(["normal", "multiply", "screen", "overlay", "darken", "lighten", "color_dodge", "color_burn", "hard_light", "soft_light", "difference", "exclusion", "hue", "saturation", "color", "luminosity"]);

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
    description: "Connect/reconnect and inspect session ID, connection/pause state, editor control text, local user-pause latch, and asset root. Does not resume editing. A local pause persists through reconnect and must be released with the editor's Resume button. Reconnect after a timeout and inspect instead of blindly repeating an edit.",
    inputSchema: {}, annotations: { readOnlyHint: true, openWorldHint: false },
  }, () => call("status"));
  server.registerTool("libresprite_set_paused", {
    description: "Pause or explicitly resume agent operations, including navigation/closing. Pause before manual editing. Disconnect pauses too. Cannot override a pause set with the editor button (USER_PAUSED); the person must click Resume there. Resume refuses drawing/playback/dialogs; pausing remains available. Reads work while paused.",
    inputSchema: { paused: z.boolean() }, annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("set_paused", params));
  server.registerTool("libresprite_list_documents", {
    description: "List documents, IDs, dimensions, frame counts, and the active document in this connected editor only.",
    inputSchema: {}, annotations: { readOnlyHint: true, openWorldHint: false },
  }, () => call("list_documents"));
  server.registerTool("libresprite_activate_document", {
    description: "Explicitly switch to an already-open sprite in this editor. Requires target documentId/current expectedRevision and expectedActiveDocumentId from list_documents (null when Home/no sprite is active); refuses if the user changed active document. Requires resumed bridge and idle GUI/target views. Does not edit pixels, saved state, mask, or undo history; restores the target view's frame/layer. Already-active target is a no-op. Never implicitly resumes.",
    inputSchema: { ...target, expectedActiveDocumentId: documentId.nullable() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("activate_document", params));
  server.registerTool("libresprite_set_active_site", {
    description: "Focus a layer and/or zero-based frame for review in the ACTIVE sprite without editing pixels, selection mask, saved state, revision, or undo history. Requires current revision, resumed bridge, and idle GUI. Validate all supplied targets before changing either. Hidden/locked/group layers can be focused but are not unlocked/shown/painted. Omitted layer/frame stays unchanged. Requires at least one of layerId/frame. To switch sprites use activate_document explicitly first.",
    inputSchema: { ...target, layerId: documentId.optional(), frame: frame.optional() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("set_active_site", params));
  server.registerTool("libresprite_close_document", {
    description: "Explicitly close the ACTIVE, saved, unmodified sprite and ALL its cloned views; never quit the editor. Requires current revision, confirm:true, resumed bridge, and idle target views. Modified or never-saved sprites are refused (UNSAVED_CHANGES); save a native file first. No Save/Discard dialog or force/discard option. Closing is NOT undoable and releases that document's undo history/IDs; files remain unchanged. Result reports closedDocumentId and the new activeDocumentId (possibly null). Inspect the list after an uncertain result; never retry blindly.",
    inputSchema: { ...target, confirm: z.literal(true) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("close_document", params));
  server.registerTool("libresprite_inspect", {
    description: "Inspect revision, layers/cels (cel/celData/image IDs, flags, optional nonempty text/color userData), zero-based frames/durations, palettes/tags, transparentIndex, document-wide selection bounds/count/visibility, active GUI frame/layer, saved state and undo availability. IDs are session-local; version fields are native telemetry. Use the revision for edits. Does not select/activate the document; works paused/inactive.",
    inputSchema: { documentId }, annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("inspect", params));
  server.registerTool("libresprite_render", {
    description: "Return an actual composited PNG image plus metadata for a zero-based frame. Nearest-neighbor scale preserves pixel edges. At most 1,048,576 output pixels. Includes revision; no file is written.",
    inputSchema: { documentId, frame, scale: z.number().int().min(1).max(16).default(1) }, annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("render", params));
  server.registerTool("libresprite_list_assets", {
    description: "Browse one directory inside the connected editor's asset root without opening documents. Returns directories and PNG/.ase/.aseprite files, directories first then bytewise name order, with root-relative paths and file sizes. Nonrecursive; symlinks/special files/other formats are skipped. Offset pagination (1-100 per page); directories above 4096 total entries are refused. Available while paused; directory changes may shift offsets.",
    inputSchema: { path: relativePath.default("."), offset: z.number().int().min(0).max(4096).default(0), limit: z.number().int().min(1).max(100).default(50) },
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("list_assets", params));
  server.registerTool("libresprite_preview_asset", {
    description: "Decode/render a trusted root-relative PNG/.ase/.aseprite to a PNG image without opening an editor tab or changing selection/preferences. Detached asset metadata has no documentId/revision: call libresprite_open to edit. Frame defaults 0; nearest-neighbor scale; 1,048,576 output pixels. Available while paused. Uses upstream codecs, not a hostile-input sandbox; no persistent thumbnail cache.",
    inputSchema: { path: relativePath, frame: frame.default(0), scale },
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("preview_asset", params));
  server.registerTool("libresprite_contact_sheet", {
    description: "Read-only PNG contact sheet of composited animation frames; does not write files or change GUI selection. Omit frames for all; explicit unique zero-based indices preserve supplied order. columns defaults ceil(sqrt(frame count)), max16 and no more than selected frames. scale is nearest-neighbor; padding (0-16) is OUTPUT pixels between cells and on all outer edges. Transparent padding/unused slots. Returns sheet frame rectangles/timings and SOURCE-index tag ranges; max 1,048,576 sheet pixels. Available while paused, including inactive documents.",
    inputSchema: { documentId, ...sheet }, annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("contact_sheet", params));
  server.registerTool("libresprite_render_onion_skin", {
    description: "Read-only native onion-skin PNG; no document/selection/onion-preference changes. Current frame is the full visible composite. Optional layerId limits GHOSTS only to an image layer or group. previous/next (0-8) clip at sprite ends, never wrap tags. tint colors previous red/next blue; merge uses original colors. position behind/front follows native rendering (opaque layers may hide behind ghosts; front can tint background layers). Opacity decreases by opacityStep per distance beyond the nearest frame, clamped 0-255. Available while paused; max1,048,576 output pixels.",
    inputSchema: { documentId, frame, scale, previous: z.number().int().min(0).max(8).default(1), next: z.number().int().min(0).max(8).default(1), mode: z.enum(["tint", "merge"]).default("tint"), position: z.enum(["behind", "front"]).default("behind"), opacity: channel.default(128), opacityStep: channel.default(32), layerId: documentId.optional() },
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("render_onion_skin", params));
  server.registerTool("libresprite_export_png", {
    description: "Atomically publish one composited frame as a root-relative .png with nearest-neighbor scale. Requires ACTIVE document/current revision/resumed bridge. Overwrite must be explicitly true; refuses symlinks/directories/escapes. Does not mark the native document saved, change its filename, or add undo history (exported files are not undone). At most1,048,576 output pixels. Returns export path/size/revision, not image content. No automatic retries after uncertain outcomes.",
    inputSchema: { ...target, path: relativePath, frame, scale, overwrite: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("export_png", params));
  server.registerTool("libresprite_export_sprite_sheet", {
    description: "Atomically export one PNG sprite sheet inside the asset root; same layout/limits as contact_sheet. Returns a libresprite-sheet-v1 manifest (frame rectangles/timing, source-index tags) IN the tool result; no separate JSON file is written, no trimming/packing/extrusion. Requires active document, current revision, resumed bridge. Overwrite opt-in; no document/history/saved-state changes. File publication is not undoable; inspect after uncertain outcomes instead of blindly retrying.",
    inputSchema: { ...target, path: relativePath, ...sheet, overwrite: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("export_sprite_sheet", params));
  server.registerTool("libresprite_set_palette", {
    description: "Undoable frame-specific palette entries and/or resize (1-256 colors) for RGBA/indexed sprites. Entries are unique index+RGBA color pairs within final size. A changed inherited palette creates a keyframe at frame, affecting frames until the next keyframe, never earlier frames. RGBA swatches do NOT recolor RGBA pixels; indexed entries recolor indexed pixels without remapping. Shrink refuses any excluded transparent/pixel index, including hidden/off-canvas cels. Grayscale/future >256-entry palettes unsupported. Identical effective colors/size are a no-op, not a redundant keyframe. Requires active document/current revision/resumed bridge; does not change GUI frame selection. Multi-palette structural frame edits remain refused.",
    inputSchema: { ...target, frame, size: z.number().int().min(1).max(256).optional(), entries: z.array(z.object({ index: z.number().int().min(0).max(255), color })).min(1).max(256).optional() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("set_palette", params));
  server.registerTool("libresprite_remove_palette", {
    description: "Undoably remove an EXACT palette keyframe at frame>0, causing its interval to inherit the preceding palette. Frame-zero base palette cannot be removed. Indexed pixels are not remapped; refuse if any affected pixel/transparent index would be outside inherited palette size. Does not switch GUI frame. Requires active document/current revision/resumed bridge.",
    inputSchema: { ...target, frame }, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("remove_palette", params));
  server.registerTool("libresprite_create_tag", {
    description: "Create an undoable native animation tag with inclusive zero-based from/to range, name, direction (forward/reverse/pingpong; default forward), optional opaque RGBA label color (default black). Returns createdTagId; inspect returns tagId for all tags. At most128 tags; duplicate names/overlaps allowed, IDs disambiguate. No selection changes. Requires active document/current revision/resumed bridge.",
    inputSchema: { ...target, name: z.string().min(1).max(120), from: frame, to: frame, direction: direction.default("forward"), color: tagColor.optional() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("create_tag", params));
  server.registerTool("libresprite_update_tag", {
    description: "Atomically update any provided native tag name/from/to/direction/opaque label color in one undo step. At least one property required; final inclusive range must be valid. Identical values preserve revision/history. tagId belongs to this document/session (inspect again after reopen). No selection changes; active/current-revision/resumed guards apply.",
    inputSchema: { ...target, tagId: documentId, name: z.string().min(1).max(120).optional(), from: frame.optional(), to: frame.optional(), direction: direction.optional(), color: tagColor.optional() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("update_tag", params));
  server.registerTool("libresprite_remove_tag", {
    description: "Undoably delete one native animation tag by explicit tagId. Does not delete frames/pixels or change selection. Requires active document/current revision/resumed bridge; missing/stale tag IDs are refused.",
    inputSchema: { ...target, tagId: documentId }, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("remove_tag", params));
  server.registerTool("libresprite_export_animation", {
    description: "Atomically export GIF (.gif path) or lossless RGBA APNG (.apng path) inside asset root. Requires active document/current revision/resumed bridge; overwrite opt-in. Omit frames/tagId for all frames forward. frames is 1-256 ordered source indices (repeats allowed), OR tagId expands native forward/reverse/pingpong (endpoints not duplicated; <=510 steps). scale nearest-neighbor1-16, loop true=forever/false=once. Native GIF quantizes to <=256 colors/frame, alpha<128 transparent/otherwise opaque; duration floors to10ms units, <10ms refused. APNG preserves native rendered RGBA and1-65535ms durations (full-canvas SOURCE frames). Limits1,048,576 pixels/frame,8,388,608 total pixels,32MiB output. Returns ordered source/encoded timing metadata, not animated image content. No document/selection/preferences/history/saved-state changes; undo doesn't remove files; never blindly retry uncertain exports.",
    inputSchema: { ...target, path: relativePath, format: z.enum(["gif", "apng"]), frames: z.array(frame).min(1).max(256).optional(), tagId: documentId.optional(), scale, loop: z.boolean().default(true), overwrite: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("export_animation", params));
  server.registerTool("libresprite_update_cel", {
    description: "Atomically set an existing cel's x/y position and/or opacity in one native undo step. Positions are signed native-file coordinates (-32768..32767); off-canvas pixels are retained, not clipped. Opacity0-255. Works in RGBA/indexed/grayscale; refuses locked ancestors/background layers/linked cels (unlink explicitly first). No implicit cel creation; no-op preserves history/UI selection. Changed requests select the target layer/frame. Requires active document/current revision/resumed bridge.",
    inputSchema: { ...celTarget, x: z.number().int().min(-32768).max(32767).optional(), y: z.number().int().min(-32768).max(32767).optional(), opacity: channel.optional() },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("update_cel", params));
  server.registerTool("libresprite_transform_cel", {
    description: "Undoably flip or exactly rotate the WHOLE cel image, including off-canvas pixels. Flips use native raster primitives; rotations are lossless integer pixel permutations, no smoothing/remapping. Quarter-turns swap image width/height; cel top-left x/y and opacity stay fixed (not canvas-centered). Ignores selection masks. Supports RGBA/indexed/grayscale and <=1024x1024 cel images. Refuses locked/background/linked/shared-image targets; no implicit missing-cel creation. Symmetric no-ops preserve revision/history/UI selection. Changed requests select target layer/frame; active/revision/resumed guards apply.",
    inputSchema: { ...celTarget, operation: z.enum(["flip_horizontal", "flip_vertical", "rotate_cw", "rotate_ccw", "rotate_180"]) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("transform_cel", params));
  server.registerTool("libresprite_unlink_cel", {
    description: "Explicitly make one native linked cel independent by cloning its image/data in one undo step. Preserves position/opacity/pixels/user data; other linked frames are unchanged. Undo restores the original link. Supports all color modes; refuses locked/background targets or missing cels. Already-unlinked is a no-op, not a new undo step. Changed requests select the target layer/frame; requires active/current revision/resumed bridge.",
    inputSchema: celTarget, annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("unlink_cel", params));
  server.registerTool("libresprite_set_selection", {
    description: "Undoable visible DOCUMENT-WIDE selection mask from inclusive rectangle/ellipse endpoints inside canvas (reversed endpoints allowed). mode replace(default)/add/subtract/intersect combines pixel masks; hidden/deselected mask counts as empty. Result is clipped to canvas and empty results clear selection. Does not change pixels, saved/modified state, active frame/layer, or global preferences; does advance revision/history. Identical visible mask is a no-op. Shared by all frames/layers; requires active document/current revision/resumed bridge. Render_selection shows actual mask/overlay.",
    inputSchema: { ...target, shape: z.enum(["rectangle", "ellipse"]).default("rectangle"), mode: z.enum(["replace", "add", "subtract", "intersect"]).default("replace"), x1: coordinate, y1: coordinate, x2: coordinate, y2: coordinate },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("set_selection", params));
  server.registerTool("libresprite_modify_selection", {
    description: "Undoably select all canvas pixels, clear selection (none), or invert selected pixels within canvas. Inverting no visible selection selects all; no implicit pixel edits. Document-wide mask, independent of frame/layer, not serialized as persistent native-file selection. Preserves saved/modified state and GUI frame/layer; updates revision/history unless unchanged. Requires active document/current revision/resumed bridge.",
    inputSchema: { ...target, action: z.enum(["all", "none", "invert"]) },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("modify_selection", params));
  server.registerTool("libresprite_render_selection", {
    description: "Read-only PNG of visible document-wide selection. mode overlay(default) highlights selected canvas pixels cyan at opacity(default96) over the native frame composite; mode mask returns opaque white selected pixels/transparent others. No selection means ordinary composite or empty mask. scale nearest-neighbor1-16, <=1,048,576 output pixels; returns selection/revision metadata. No UI/pixels/history/preferences changes; works paused and for inactive documents.",
    inputSchema: { documentId, frame, scale, mode: z.enum(["overlay", "mask"]).default("overlay"), opacity: channel.default(96) },
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, (params) => call("render_selection", params));
  server.registerTool("libresprite_fill_selection", {
    description: "Undoably replace pixels with RGBA color only inside the VISIBLE selection on explicit layer/frame. Alpha0 erases; no alpha blending/composite sampling. Missing cel can be created by changed pixels. Refuses absent/hidden selection (NO_SELECTION), not a whole-cel fallback; refuses indexed/grayscale, linked/shared-image/background/locked targets. Preserves mask, all unselected/off-canvas cel pixels, and other frames. Identical pixels are a no-op. Changed edits select target layer/frame; active/revision/resumed guards apply.",
    inputSchema: { ...celTarget, color }, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("fill_selection", params));
  server.registerTool("libresprite_translate_selection", {
    description: "Move or copy (copy:true) VISIBLE selected RGBA pixels within ONE explicit layer/frame by integer dx/dy, moving the document-wide mask with them. Snapshots raw cel pixels before edits, so overlaps are safe. Destination selected pixels REPLACE colors, including transparent source pixels; no blending. Refuses a mask/destination outside canvas instead of clipping, no hidden/no-selection fallback. One undo step restores pixels AND mask; blank-pixel mask-only moves preserve saved state. Refuses non-RGBA/background/locked/linked/shared-image targets. dx/dy0 is a no-op. Selects changed target layer/frame; active/revision/resumed guards apply.",
    inputSchema: { ...celTarget, dx: z.number().int().min(-1023).max(1023), dy: z.number().int().min(-1023).max(1023), copy: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("translate_selection", params));
  server.registerTool("libresprite_create", {
    description: "Create and visibly select a transparent sprite with one layer/frame, colorMode rgba(default) or indexed (256-entry initial native palette, transparent index0). Set explicit swatches with set_palette before indexed painting. Existing documents stay open; creation is not an undo step. Requires resumed/idle bridge.",
    inputSchema: { width: dimension, height: dimension, name: z.string().min(1).max(120).default("AI Sprite"), colorMode: z.enum(["rgba", "indexed"]).default("rgba") }, annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("create", params));
  server.registerTool("libresprite_open", {
    description: "Open and visibly select a PNG/.ase/.aseprite inside the configured asset root. Relative path only; symlink escapes are refused. Requires resumed bridge. Unsupported modern Aseprite chunks may not round-trip losslessly.",
    inputSchema: { path: relativePath }, annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("open", params));
  server.registerTool("libresprite_set_pixels", {
    description: "Apply an atomic, undoable RGBA pixel batch to an explicit layer/frame in the ACTIVE document. Coordinates are canvas pixels, colors replace pixels (not alpha-blended), duplicates use the last color. Requires current revision and resumed bridge. Refuses locked/background layers and linked/shared-image cels. Selection is ignored by default; respectSelection:true requires a visible mask and skips unselected pixels (all input still validates). Render after editing to inspect the result.",
    inputSchema: { ...paintTarget, label: z.string().min(1).max(120).default("AI pixel edit"), pixels: z.array(z.object({ x: z.number().int().min(0).max(1023), y: z.number().int().min(0).max(1023), r: channel, g: channel, b: channel, a: channel })).min(1).max(16384) }, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("set_pixels", params));
  server.registerTool("libresprite_create_layer", {
    description: "Create/select an undoable empty image layer or group in the active document. parentId null/omitted means root; otherwise an editable group. Omit afterLayerId to append on top, or use null for the bottom. Never inserts below a background. Returns createdLayerId. Requires resumed bridge/current revision.",
    inputSchema: { ...target, name: z.string().min(1).max(120), type: z.enum(["image", "group"]).default("image"), parentId: documentId.nullable().optional(), afterLayerId: documentId.nullable().optional() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("create_layer", params));
  server.registerTool("libresprite_update_layer", {
    description: "Undoably change layer name/visibility/editable flag, transparent image-layer opacity, or one of 16 native blendMode names. Group/background opacity/blend changes unsupported. Locked layers refuse properties until explicitly unlocked separately; locked ancestors always refuse. One undo step; no-op consumes no history. Requires active/current revision/resumed idle bridge.",
    inputSchema: { ...target, layerId: documentId, name: z.string().min(1).max(120).optional(), visible: z.boolean().optional(), editable: z.boolean().optional(), opacity: channel.optional(), blendMode: blendMode.optional() },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("update_layer", params));
  server.registerTool("libresprite_move_layer", {
    description: "Undoably restack a layer AFTER a different sibling in the SAME group. Order is bottom-to-top: afterLayerId null puts it at the bottom. Does not reparent layers or move background layers. Requires active document, resumed bridge, and current revision.",
    inputSchema: { ...target, layerId: documentId, afterLayerId: documentId.nullable() },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("move_layer", params));
  server.registerTool("libresprite_remove_layer", {
    description: "Undoably delete a layer and its cels on ALL frames. A nonempty group additionally requires recursive:true and deletes its whole subtree. Refuses locked/background descendants and removal of the last image layer. Requires current revision and resumed bridge.",
    inputSchema: { ...target, layerId: documentId, recursive: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("remove_layer", params));
  server.registerTool("libresprite_add_frame", {
    description: "Undoably insert/select a frame at zero-based index (0 through current frame count). Omit copyFrom for blank; otherwise copy that PRE-insertion frame across all image layers with independent, unlinked cels. durationMs defaults to 100 for blank or source duration for copies. Following frame indices shift; inspect again. Refuses locked layers and per-frame palettes. Existing tags are adjusted natively.",
    inputSchema: { ...target, index: frame, copyFrom: frame.optional(), durationMs: z.number().int().min(1).max(65535).optional() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("add_frame", params));
  server.registerTool("libresprite_remove_frame", {
    description: "Undoably remove a zero-based frame and all its cels; later indices shift and tag ranges update. Refuses the last frame, locked layers, and per-frame palettes. Requires active document/current revision/resumed bridge. Inspect again before editing another frame.",
    inputSchema: { ...target, frame }, annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("remove_frame", params));
  server.registerTool("libresprite_set_frame_duration", {
    description: "Undoably set/select one frame's duration in milliseconds (1-65535, matching native-file storage). Requires active document, resumed bridge, and current revision. Identical duration is a no-op.",
    inputSchema: { ...target, frame, durationMs: z.number().int().min(1).max(65535) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("set_frame_duration", params));
  server.registerTool("libresprite_resize_canvas", {
    description: "Undoably change canvas width/height (1..1024) without scaling, cropping, or deleting cel pixels. Optional integer offsetX/Y (-1023..1023, defaults0) shift all unique linked cel data and full selection together; no implicit centering. Off-canvas data is retained even on shrink. RGBA/indexed/grayscale; transparent layers only, locked layers/ancestors or out-of-native-range shifts refused. Frame timing, tags, palettes, links and focus stay intact. One undo step; identical request is a no-op. Requires active document/current revision/resumed/idle views.",
    inputSchema: { ...target, width: dimension, height: dimension, offsetX: z.number().int().min(-1023).max(1023).default(0), offsetY: z.number().int().min(-1023).max(1023).default(0) },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("resize_canvas", params));
  server.registerTool("libresprite_crop_canvas", {
    description: "Destructively crop ALL frames/layers to an explicit in-canvas x/y/width/height rectangle, then move its origin to0,0. Does not scale. Any cel bounds (including off-canvas/transparent data) or mask bounds outside the rectangle requires discardOutside:true; otherwise WOULD_DISCARD_PIXELS. Crops raw images, removes wholly-outside cels, clips visible selection, preserves opacity/user data/remaining links/timing/tags/palettes. Transparent RGBA/indexed/grayscale only; background/locked targets, cross-layer shared cel data/images, and retained hidden selections refused. ONE undo step restores all discarded data and mask. Requires revision/resumed/active/idle views; bounded scratch.",
    inputSchema: { ...target, x: coordinate, y: coordinate, width: dimension, height: dimension, discardOutside: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("crop_canvas", params));
  server.registerTool("libresprite_duplicate_layer", {
    description: "Duplicate an image layer or whole nested group subtree across ALL frames as one native undo step. Source layerId; optional name, parentId (null=root, omitted=same parent), afterLayerId (null=bottom, omitted=after source in same parent or destination top). Copies flags/opacity/blend/user data, raw off-canvas cels/positions/opacities/user data. ALL copied cels are independent, including formerly linked sources. Hidden/locked sources can be read, copied locks retained; destination ancestors must be editable. Background sources/below-background placement/128-layer or 32 MiB overflow refused. New IDs; source/timing/tags/palettes/mask unchanged. Focuses new layer. Requires active/current revision/resumed/idle views.",
    inputSchema: { ...target, layerId: documentId, name: z.string().min(1).max(120).optional(), parentId: documentId.nullable().optional(), afterLayerId: documentId.nullable().optional() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("duplicate_layer", params));
  server.registerTool("libresprite_reparent_layer", {
    description: "Move a layer/group subtree into explicit parentId (null=root); optional afterLayerId (null=bottom, omitted=keep position in same parent or destination top). Preserves all layer/cel/image IDs, data, links and properties; resulting compositing may change with new group visibility/order. ONE undo step. Refuses hierarchy cycles (LAYER_CYCLE), locked/movement-locked/background targets or locked source/destination ancestors, and below-background placement. Same parent/position is a no-op. Focus stays on existing layer/frame. Requires active/current revision/resumed/idle views.",
    inputSchema: { ...target, layerId: documentId, parentId: documentId.nullable(), afterLayerId: documentId.nullable().optional() },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("reparent_layer", params));
  server.registerTool("libresprite_set_polygon_selection", {
    description: "Undoably create a document-wide visible pixel polygon mask from 3..128 vertices inside canvas (>=3 distinct). Even-odd pixel-center fill plus inclusive native one-pixel boundary lines, including self intersections; no antialiasing. mode replace/add/subtract/intersect combines with current visible mask within canvas; hidden mask counts as empty. Empty clears; identical is no-op. Mask-only history/revision change, not saved/modified state or pixels/focus. Bounded to 8,388,608 pixel-edge tests. All color modes. Requires active/current revision/resumed/idle views.",
    inputSchema: { ...target, vertices: z.array(point).min(3).max(128), mode: maskMode },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("set_polygon_selection", params));
  server.registerTool("libresprite_set_bitmap_selection", {
    description: "Undoable document-wide mask from explicit x/y/width/height and row-major bits string of exactly width*height '0'/'1' digits (<=262,144). Rectangle must fit canvas. Sparse/disconnected/holes allowed; all0 clears in replace mode. mode replace/add/subtract/intersect combines within canvas with visible mask; hidden counts as empty. Preserves saved state/pixels/focus; identical is no-op. All color modes. Requires active/current revision/resumed/idle views.",
    inputSchema: { ...target, x: coordinate, y: coordinate, width: dimension, height: dimension, bits, mode: maskMode },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("set_bitmap_selection", params));
  server.registerTool("libresprite_draw_brush_stroke", {
    description: "Stamp an explicit bitmap brush along a native one-pixel connected path (1..1024 points) in ONE atomic undo step. brush width/height1..32, bits exact row-major binary string with >=1 set bit, optional anchorX/Y default floor(width/2),floor(height/2). RGBA requires color; indexed requires exact index; exactly one, no conversion. Colors/indices replace, transparent erases. Refuses clipping unless clipToCanvas:true, >8,388,608 stamp-pixel visits, locked/background/linked/shared-image targets. respectSelection:true requires visible mask and restricts stamps. Does not change UI brush/preferences. No-op preserves history; focuses changed target. Current revision/resumed/active/idle required.",
    inputSchema: { ...paintTarget, points: z.array(point).min(1).max(1024), brush: z.object({ width: z.number().int().min(1).max(32), height: z.number().int().min(1).max(32), bits: bits.max(1024), anchorX: z.number().int().min(0).max(31).optional(), anchorY: z.number().int().min(0).max(31).optional() }), color: color.optional(), index: channel.optional(), clipToCanvas: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("draw_brush_stroke", params));
  server.registerTool("libresprite_set_indexed_pixels", {
    description: "Atomic exact indexed painting on explicit layer/frame in an INDEXED sprite. pixels1..16384 each x/y/index0..255; index must exist in that frame's palette or equal transparentIndex from inspect (erases). Duplicates use last index. No RGBA conversion, remapping, palette mutation or blending. Missing cel can be created. respectSelection:true requires visible mask, skips unselected pixels but validates ALL input. Refuses locked/background/linked/shared-image targets. Off-canvas/unselected pixels retained; unchanged is no-op; ONE undo step. Requires active/current revision/resumed/idle views; focuses changed target.",
    inputSchema: { ...paintTarget, pixels: z.array(z.object({ x: coordinate, y: coordinate, index: channel })).min(1).max(16384) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("set_indexed_pixels", params));
  server.registerTool("libresprite_copy_cel", {
    description: "Copy a whole source cel to an existing destination layerId/frame in the SAME active sprite, as one native undo step. No clipboard or frame creation. SourceLayerId/sourceFrame must have an image cel (hidden/locked/linked sources can be read). Destination must be editable/transparent/unlinked/unshared. Existing destination refuses unless overwrite:true; replacement includes transparent pixels, full off-canvas data, position, opacity, and cel user data. Always independent, ignores selections/continuous preference. RGBA/indexed/grayscale; indexed requires equal palettes (no remapping). Same source/destination is a no-op. Requires revision/resumed/idle bridge; focuses destination on success.",
    inputSchema: { ...celTarget, sourceLayerId: documentId, sourceFrame: frame, overwrite: z.boolean().default(false) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("copy_cel", params));
  server.registerTool("libresprite_duplicate_frames", {
    description: "Atomically insert independent copies of explicit unique source frames at index (0..frameCount, append allowed). frames order controls inserted order; all sources refer to PRE-edit indices and are snapshotted before insertion, including overlap. Copies every image layer including hidden/nested/background, blank cels, raw off-canvas pixels/position/opacity/user data and durations. One native undo step; original links preserved, copies never linked. Later indices shift; native tag insertion rules apply (copies inside a tag extend it; no new tags). Refuses locked layers/ancestors, palette keyframes, >256 frames, or >32 MiB working data. Focuses first inserted frame. Revision/resumed/active guards apply.",
    inputSchema: { ...target, frames, index: z.number().int().min(0).max(256) },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, (params) => call("duplicate_frames", params));
  server.registerTool("libresprite_reorder_frames", {
    description: "Atomically reorder ALL existing frames using order: a complete unique permutation of old indices, where order[newIndex] = oldIndex. Preserves cels/images/linked relationships, off-canvas pixels, opacity, user data and pose durations; one native undo step. Keeps active pose focused at its new index. Tags move with their original member frames; refuses TAG_SPLIT if a tag would become disjoint. No automatic palette/keyframe remapping (multiple palettes refused); locked layers/ancestors refused. Identity order is a no-op. Requires active document/current revision/resumed idle bridge.",
    inputSchema: { ...target, order: frames },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("reorder_frames", params));
  server.registerTool("libresprite_edit_cels", {
    description: "Atomic explicit multi-frame/layer cel batch: edits (1..256) each identify layerId/frame and x/y/opacity and/or exact whole-cel operation. Validate ALL targets/properties and prepare transforms before any change; any error changes nothing; whole batch is ONE native undo step. Existing transparent editable/unlinked cels only; whole transforms also refuse shared images. No implicit create/unlink/selection handling; RGBA/indexed/grayscale, top-left/off-canvas data preserved. Duplicate layer/frame pairs refused. All unchanged is a no-op. Current GUI focus stays unchanged. Requires revision/resumed/active/idle bridge; bounded scratch/working data.",
    inputSchema: { ...target, edits: z.array(z.object({ layerId: documentId, frame, x: signedCoordinate.optional(), y: signedCoordinate.optional(), opacity: channel.optional(), operation: transform.optional() })).min(1).max(256) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("edit_cels", params));
  server.registerTool("libresprite_set_frame_durations", {
    description: "Atomically set explicit frame/durationMs pairs (1..256 unique frames, 1..65535 ms) as ONE native undo step. Validate all pairs before changing any timing. Leaves pixels/cels/tags/selection/focus unchanged. Duplicate frames refused; identical timings are a no-op. Works with palette keyframes. Requires active document/current revision/resumed idle bridge.",
    inputSchema: { ...target, durations: z.array(z.object({ frame, durationMs: z.number().int().min(1).max(65535) })).min(1).max(256) },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("set_frame_durations", params));
  server.registerTool("libresprite_transform_selection", {
    description: "Exact flip/rotation of VISIBLE selected pixels on one layer across explicit unique frames, in ONE native undo step including transformed mask. RGBA only, editable/transparent/unlinked/unshared targets; missing cels can participate as transparent. No visible selection => NO_SELECTION, NEVER whole-cel fallback. Uses selection bounding-box top-left as anchor; quarter turns swap width/height and refuse clipping. Snapshot original pixels, clear only old selected mask bits, then replace transformed destination bits (transparent overwrites too); holes/unrelated/off-canvas pixels stay untouched. Mask transforms once for all frames. Validates all targets/aggregate crop bounds before changes. Focuses first requested frame on success. Revision/resume/active/idle guards apply.",
    inputSchema: { ...target, layerId: documentId, frames, operation: transform },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("transform_selection", params));
  server.registerTool("libresprite_draw_shape", {
    description: "Draw a native pixel-aligned line, rectangle, or ellipse as ONE undoable edit on an explicit layer/frame. Endpoints are inclusive, inside canvas; rectangle/ellipse corners may be reversed. Lines/outlines are one pixel wide; filled defaults false (invalid for line). Replaces RGBA colors (alpha0 erases). Ignores selection by default; respectSelection:true requires a visible mask and clips drawing to selected pixels. Refuses linked/shared-image/background/locked targets. No-op preserves history; render afterwards.",
    inputSchema: { ...paintTarget, shape: z.enum(["line", "rectangle", "ellipse"]), x1: coordinate, y1: coordinate, x2: coordinate, y2: coordinate, color, filled: z.boolean().default(false), label: z.string().min(1).max(120).default("AI shape") },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("draw_shape", params));
  server.registerTool("libresprite_draw_stroke", {
    description: "Draw a connected one-pixel polyline with 1-1024 canvas points as one atomic native undo step. Native line rasterization, inclusive endpoints, RGBA replacement (alpha0 erases). Ignores selection by default; respectSelection:true requires a visible mask and clips the stroke. Refuses locked/background/linked/shared-image targets. No pressure, brush width, or smoothing yet. Render afterwards.",
    inputSchema: { ...paintTarget, points: z.array(point).min(1).max(1024), color, label: z.string().min(1).max(120).default("AI stroke") },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("draw_stroke", params));
  server.registerTool("libresprite_flood_fill", {
    description: "Flood fill the TARGET CEL's canvas, not the composite. Native matching uses per-RGBA-channel tolerance0-255 and equates fully transparent colors. contiguous:true fills connected region; false replaces all matches. Selection ignored by default; respectSelection:true requires a visible mask and restricts traversal/matches to selected pixels; an unselected seed is a no-op. RGBA replacement, current revision/resumed bridge; refuses linked/shared-image/background/locked targets. Empty cel's transparent canvas can be filled. One undo step unless unchanged.",
    inputSchema: { ...paintTarget, x: coordinate, y: coordinate, color, tolerance: channel.default(0), contiguous: z.boolean().default(true), label: z.string().min(1).max(120).default("AI flood fill") },
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  }, (params) => call("flood_fill", params));
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
