// GPL-2.0-only. Windows pipe names are not filesystem paths.
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";

export function windowsPipeName(root: string): string {
  const id = createHash("sha256").update(`${os.homedir()}\0${root.toLowerCase()}`).digest("hex").slice(0, 24);
  return `\\\\.\\pipe\\libresprite-ai-${id}`;
}

export function validWindowsPipe(value: string): boolean {
  return /^\\\\\.\\pipe\\libresprite-ai-[A-Za-z0-9_-]{1,100}$/.test(value);
}

export function endpointError(endpoint: string, platform: NodeJS.Platform = process.platform): string | undefined {
  if (platform === "win32") return validWindowsPipe(endpoint) ? undefined : "Use a local named pipe: \\\\.\\pipe\\libresprite-ai-<name> (1–100 letters, digits, underscores or hyphens).";
  const max = platform === "darwin" ? 103 : 107;
  return path.isAbsolute(endpoint) && Buffer.byteLength(endpoint) <= max ? undefined : `Use an absolute Unix socket path of at most ${max} bytes.`;
}
