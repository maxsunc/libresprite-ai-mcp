// GPL-2.0-only. Packaged defaults never write inside the installed application.
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ServerOptions } from "./server.js";

export function resolveOptions(root: string, env: NodeJS.ProcessEnv = process.env): ServerOptions {
  const packaged = existsSync(path.join(root, "package-layout.json"));
  return {
    socketPath: path.resolve(env.LIBRESPRITE_SOCKET ?? (packaged
      ? path.join(os.tmpdir(), `lsai-${process.getuid?.() ?? "user"}`, "b.sock")
      : path.join(root, ".runtime/bridge.sock"))),
    executable: path.resolve(env.LIBRESPRITE_EXECUTABLE ?? (packaged
      ? path.join(root, "../LibreSprite AI.app/Contents/MacOS/libresprite")
      : path.join(root, "build/libresprite/bin/libresprite"))),
    assetRoot: path.resolve(env.LIBRESPRITE_ASSET_ROOT ?? (packaged
      ? path.join(os.homedir(), "Pictures/LibreSprite AI MCP") : path.join(root, "assets"))),
  };
}
