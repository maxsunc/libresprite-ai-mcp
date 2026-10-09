// GPL-2.0-only. Read-only diagnostics; never launches a GUI, resumes, or edits.
import { constants } from "node:fs";
import { access, lstat, readFile, readdir, realpath } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import os from "node:os";
import { BridgeClient } from "./bridge-client.js";
import type { ServerOptions } from "./server.js";
import { inspectMachO } from "./macho.js";

const exec = promisify(execFile);
type Check = { name: string; status: "ok" | "warning" | "error"; detail: string };

export async function diagnose(options: ServerOptions, connect = false): Promise<{ checks: Check[]; ok: boolean }> {
  const checks: Check[] = [];
  const add = (name: string, status: Check["status"], detail: string) => checks.push({ name, status, detail });
  add("node", Number(process.versions.node.split(".")[0]) >= 20 ? "ok" : "error", process.version);
  add("platform", process.platform === "darwin" && process.arch === "arm64" ? "ok" : "warning",
    `${process.platform}/${process.arch}; packaged editor requires Apple Silicon macOS (not Rosetta Node).`);
  try {
    await access(options.executable, constants.X_OK);
    // Upstream initializes user preferences/palettes even for --version. Never
    // execute an editor just to diagnose it; inspect the bundle and load commands.
    add("executable", "ok", `${options.executable} (accessible; not executed)`);
  } catch (error) { add("executable", "error", `${options.executable}: ${String(error)}. Check the configured executable path/permissions.`); }
  const resources = path.resolve(path.dirname(options.executable), "../Resources");
  try {
    const manifest = JSON.parse(await readFile(path.join(resources, "package-manifest.json"), "utf8")) as { version: string; minimumMacOS: string };
    await access(path.join(resources, "data/gui.xml"));
    add("resources", manifest.version === "0.9.0" ? "ok" : "error", `Package ${manifest.version}; macOS ${manifest.minimumMacOS}+; ${resources}`);
    if (process.platform === "darwin") {
      const { stdout } = await exec("/usr/bin/sw_vers", ["-productVersion"]);
      const actual = stdout.trim().split(".").map(Number), needed = manifest.minimumMacOS.split(".").map(Number);
      const older = (actual[0] ?? 0) < (needed[0] ?? 0) || (actual[0] === needed[0] && (actual[1] ?? 0) < (needed[1] ?? 0));
      add("macos", older ? "error" : "ok", `${stdout.trim()} (package minimum ${manifest.minimumMacOS})`);
      await exec("/usr/bin/codesign", ["--verify", "--deep", "--strict", path.resolve(resources, "../..")]);
      add("signature", "warning", "Ad-hoc signature verified; not Developer ID signed/notarized. Only open a package you trust.");
      const frameworks = path.resolve(resources, "../Frameworks");
      const app = await realpath(path.resolve(resources, "../.."));
      const binaries = [options.executable, ...(await readdir(frameworks)).filter((name) => name.endsWith(".dylib")).map((name) => path.join(frameworks, name))];
      for (const binary of binaries) {
        const bytes = await readFile(binary);
        const commands = inspectMachO(bytes);
        if (commands.rpaths.some((value) => value.startsWith("/") && !value.startsWith("/usr/lib/") && !value.startsWith("/System/Library/"))) throw new Error(`External library search path: ${binary}`);
        for (const dependency of commands.dependencies) {
          if (dependency.startsWith("/usr/lib/") || dependency.startsWith("/System/Library/")) continue;
          if (!dependency.startsWith("@loader_path/")) throw new Error(`External native dependency: ${dependency}`);
          const local = path.resolve(path.dirname(binary), dependency.slice("@loader_path/".length));
          await access(local, constants.R_OK);
          if (!(await realpath(local)).startsWith(app + path.sep)) throw new Error(`Library escapes app: ${local}`);
        }
        if (bytes.includes(Buffer.from("@loader_path/libSDL3.dylib"))) await access(path.join(frameworks, "libSDL3.dylib"), constants.R_OK);
      }
      add("libraries", "ok", `${binaries.length} bundled Mach-O files/aliases audited without executing the editor.`);
    }
  } catch (error) {
    const developmentData = path.join(path.dirname(options.executable), "data/gui.xml");
    try { await access(developmentData); add("resources", "warning", "Development layout (not an app package); native build dependencies required."); }
    catch { add("resources", "error", String(error)); }
  }
  const maxBytes = process.platform === "darwin" ? 103 : 107;
  add("socket-path", Buffer.byteLength(options.socketPath) <= maxBytes ? "ok" : "error", `${options.socketPath} (${Buffer.byteLength(options.socketPath)}/${maxBytes} bytes)`);
  try {
    const directory = await lstat(path.dirname(options.socketPath));
    const safe = directory.isDirectory() && !directory.isSymbolicLink() && (directory.mode & 0o077) === 0 && directory.uid === process.getuid?.();
    add("socket-directory", safe ? "ok" : "error", safe ? "Owned by you, mode 0700." : "Requires a real directory owned by you with mode 0700; do not chmod unrelated directories.");
  } catch (error) {
    add("socket-directory", (error as NodeJS.ErrnoException).code === "ENOENT" ? "warning" : "error", "Not available; launch creates a private directory. No files were changed by diagnostics.");
  }
  try {
    const endpoint = await lstat(options.socketPath);
    add("socket", endpoint.isSocket() && (endpoint.mode & 0o077) === 0 && endpoint.uid === process.getuid?.() ? "ok" : "error", "Endpoint exists. Launch will never replace it; connect, or investigate a confirmed stale socket manually.");
  } catch (error) { add("socket", (error as NodeJS.ErrnoException).code === "ENOENT" ? "warning" : "error", "No endpoint; launch a NEW editor with libresprite_launch."); }
  try {
    const info = await lstat(options.assetRoot);
    await access(options.assetRoot, constants.R_OK | constants.W_OK | constants.X_OK);
    add("asset-root", info.isDirectory() && !info.isSymbolicLink() ? "ok" : "error", options.assetRoot);
  } catch (error) { add("asset-root", (error as NodeJS.ErrnoException).code === "ENOENT" ? "warning" : "error", `${options.assetRoot}: not available; launch creates it. Start with copies of artwork.`); }
  if (connect) {
    const bridge = new BridgeClient(options.socketPath, 3000);
    try {
      const status = await bridge.request("status");
      add("bridge", status.bridgeVersion === "0.9.0" ? "ok" : "error", JSON.stringify(status));
    } catch (error) { add("bridge", "error", String(error)); }
    finally { bridge.close(); }
    add("disconnect", "warning", "Explicit diagnostic connection closed: the editor pauses on disconnect. It was never resumed or edited.");
  }
  add("preferences", "ok", path.join(os.homedir(), "Library/Application Support/LibreSprite AI MCP (packaged app only)"));
  return { checks, ok: !checks.some((check) => check.status === "error") };
}
