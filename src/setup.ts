// GPL-2.0-only. Setup never connects to the bridge or starts/stops an editor.
import { constants } from "node:fs";
import { access, copyFile, link, lstat, mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";
import os from "node:os";
import { parseArgs, isDeepStrictEqual } from "node:util";
import { createInterface } from "node:readline/promises";
import { resolveOptions } from "./config.js";
import { diagnose } from "./doctor.js";
import { guideRoot, SERVER_INSTRUCTIONS } from "./guides.js";
import type { ServerOptions } from "./server.js";

export const clients = ["generic", "claude-code", "claude-desktop", "cursor", "gemini", "pi", "vscode", "opencode-v2", "codex"] as const;
export type SetupClient = typeof clients[number];
type JsonObject = Record<string, unknown>;

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a JSON object; no settings changed.");
  return value as JsonObject;
}

function serverKeys(client: SetupClient): string[] {
  return client === "vscode" ? ["servers"] : client === "opencode-v2" ? ["mcp", "servers"] : ["mcpServers"];
}

export function clientConfig(client: SetupClient, root: string, options: ServerOptions, node = process.execPath): JsonObject {
  const env = { LIBRESPRITE_ASSET_ROOT: options.assetRoot, LIBRESPRITE_EXECUTABLE: options.executable, LIBRESPRITE_SOCKET: options.socketPath };
  const args = [path.join(root, "dist/index.js")];
  const entry = client === "opencode-v2" ? { type: "local", command: [node, ...args], environment: env }
    : { command: node, args, env, ...(client === "vscode" ? { type: "stdio" } : {}),
      ...(client === "pi" ? { exposure: "deferred", description: "Create, inspect, draw and animate pixel art in a visible LibreSprite editor, with native undo and PNG feedback." } : {}) };
  if (client === "codex") return { mcp_servers: { libresprite: entry } };
  let config: JsonObject = { libresprite: entry };
  for (const key of serverKeys(client).reverse()) config = { [key]: config };
  return config;
}

export function formatConfig(client: SetupClient, config: JsonObject): string {
  if (client !== "codex") return JSON.stringify(config, null, 2) + "\n";
  const entry = object(object(config.mcp_servers).libresprite);
  return `[mcp_servers.libresprite]\ncommand = ${JSON.stringify(entry.command)}\nargs = ${JSON.stringify(entry.args)}\n\n[mcp_servers.libresprite.env]\n`
    + Object.entries(object(entry.env)).map(([key, value]) => `${key} = ${JSON.stringify(value)}\n`).join("");
}

export function mergeConfig(client: SetupClient, existing: unknown, generated: JsonObject): JsonObject {
  if (client === "codex") throw new Error("Codex TOML is preview-only. Merge the printed tables into config.toml using your editor.");
  const merged = structuredClone(object(existing));
  let target = merged;
  let source = generated;
  for (const key of serverKeys(client)) {
    target[key] = Object.hasOwn(target, key) ? object(target[key]) : {};
    target = object(target[key]);
    source = object(source[key]);
  }
  if (Object.hasOwn(target, "libresprite") && !isDeepStrictEqual(target.libresprite, source.libresprite)) {
    throw new Error("A different libresprite entry already exists. Review it manually; setup will not overwrite it.");
  }
  target.libresprite = source.libresprite;
  return merged;
}

async function existingFile(filename: string): Promise<Buffer | undefined> {
  try {
    const info = await lstat(filename);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error(`Refusing non-regular file or symlink: ${filename}`);
    return await readFile(filename);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
}

export async function writeConfig(filename: string, client: SetupClient, generated: JsonObject): Promise<string | undefined> {
  // Validate before creating even a parent directory (TOML isn't safely mergeable with JSON.parse).
  mergeConfig(client, {}, generated);
  await mkdir(path.dirname(filename), { recursive: true, mode: 0o700 });
  const lock = filename + ".libresprite-setup.lock";
  await writeFile(lock, "LibreSprite setup in progress\n", { flag: "wx", mode: 0o600 });
  const temporary = filename + `.${randomUUID()}.tmp`;
  try {
    const original = await existingFile(filename);
    let parsed: unknown = {};
    if (original) {
      try { parsed = JSON.parse(original.toString("utf8")); }
      catch { throw new Error("Settings must be strict JSON. JSONC/comments, malformed JSON and TOML are never rewritten; merge the preview manually."); }
    }
    const merged = mergeConfig(client, parsed, generated);
    if (original && isDeepStrictEqual(parsed, merged)) return undefined;
    // shortcut: Windows inherits the folder ACL; add ACL preservation before supporting shared settings folders.
    await writeFile(temporary, JSON.stringify(merged, null, 2) + "\n", { flag: "wx", mode: 0o600 });
    let backup: string | undefined;
    if (original) {
      backup = filename + `.${randomUUID()}.bak`;
      await writeFile(backup, original, { flag: "wx", mode: 0o600 });
      const current = await existingFile(filename);
      if (!current?.equals(original)) throw new Error(`Settings changed during setup. Nothing replaced; backup: ${backup}`);
      await rename(temporary, filename);
    } else {
      // Publish new settings exclusively, without replacing a concurrently created file.
      await link(temporary, filename);
    }
    return backup;
  } finally {
    await unlink(temporary).catch((error: NodeJS.ErrnoException) => { if (error.code !== "ENOENT") throw error; });
    await unlink(lock);
  }
}

export async function installSkill(root: string, skillsDirectory: string): Promise<string> {
  const source = path.join(guideRoot(root), ".agents/skills/pixel-animation/SKILL.md");
  const target = path.join(skillsDirectory, "pixel-animation/SKILL.md");
  const content = await readFile(source);
  const existing = await existingFile(target);
  if (existing) {
    if (existing.equals(content)) return target;
    throw new Error(`A different pixel-animation skill already exists: ${target}. Nothing overwritten.`);
  }
  await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
  await copyFile(source, target, constants.COPYFILE_EXCL);
  return target;
}

function absolute(value: string): string {
  if (!value.trim() || value.includes("\0")) throw new Error("Paths must not be empty or contain NUL.");
  return path.resolve(value === "~" ? os.homedir() : value.startsWith("~/") || value.startsWith("~\\") ? path.join(os.homedir(), value.slice(2)) : value);
}

const help = `Usage: node dist/index.js --setup [options]
  --client NAME       ${clients.join(", ")}
  --asset-root PATH   Artwork folder (use disposable copies); ~ is expanded
  --config PATH       Client settings file (used only with --write)
  --write             Explicitly merge settings; backup existing JSON, refuse conflicts
  --skill-dir PATH    Explicitly copy pixel-animation into PATH/pixel-animation
  --help              Show this help

No options: interactive client/artwork selection and optional confirmed JSON install.
With options: print config to stdout; diagnostics/status go to stderr.
Without --write / --skill-dir, no files are changed. Codex TOML is preview-only.
Setup never launches, connects, resumes, stops or reloads an editor/client.
`;

export async function runSetup(root: string, args: string[]): Promise<void> {
  const { values } = parseArgs({ args, options: {
    client: { type: "string" }, "asset-root": { type: "string" }, config: { type: "string" },
    write: { type: "boolean" }, "skill-dir": { type: "string" }, help: { type: "boolean" },
  } });
  if (values.help) { process.stdout.write(help); return; }
  const interactive = args.length === 0 && process.stdin.isTTY;
  if (!values.client && !interactive) throw new Error("Choose --client NAME, or run --setup in a terminal for the wizard.\n" + help);
  if (values.write && !values.config) throw new Error("--write requires --config PATH; no client settings are guessed.");
  if (values.config && !values.write) throw new Error("--config requires --write. Omit both for a read-only preview.");
  const prompt = interactive ? createInterface({ input: process.stdin, output: process.stderr }) : undefined;
  try {
    const name = values.client ?? ((await prompt!.question(`Client (${clients.join(", ")}) [generic]: `)).trim() || "generic");
    if (!clients.includes(name as SetupClient)) throw new Error(`Unknown client: ${name}. Choose ${clients.join(", ")}.`);
    const client = name as SetupClient;
    const options = resolveOptions(root);
    const artwork = values["asset-root"] ?? (prompt ? (await prompt.question(`Artwork folder [${options.assetRoot}]: `)).trim() || options.assetRoot : options.assetRoot);
    options.assetRoot = absolute(artwork);
    const config = clientConfig(client, root, options);
    process.stdout.write(formatConfig(client, config));
    const diagnostics = await diagnose(options); // Never use --connect: another agent may own the editor.
    for (const check of diagnostics.checks) process.stderr.write(`[${check.status}] ${check.name}: ${check.detail}\n`);
    if (!diagnostics.ok) {
      process.exitCode = 1;
      process.stderr.write("Fix the errors above before installing settings/skills. Build the modified native editor (see docs/building.md or docs/windows.md), or set LIBRESPRITE_EXECUTABLE to its path. Preview only; no files changed.\n");
      return;
    }
    let filename = values.config;
    if (prompt && client !== "codex") {
      filename = (await prompt.question("Client JSON settings path (blank = preview only; see docs/setup.md for locations): ")).trim() || undefined;
      if (filename && !/^y(es)?$/i.test((await prompt.question(`Merge into ${absolute(filename)} with a backup? [y/N]: `)).trim())) filename = undefined;
    }
    if (filename) {
      const destination = absolute(filename);
      const backup = await writeConfig(destination, client, config);
      process.stderr.write(`Settings ready: ${destination}${backup ? `\nBackup: ${backup}` : ""}\n`);
    }
    if (values["skill-dir"]) process.stderr.write(`Skill ready: ${await installSkill(root, absolute(values["skill-dir"]))}\n`);
    process.stderr.write("Reload/restart only your chosen client when safe; setup did not do so. Check its MCP status for libresprite (70 tools). Image-capable MCP results are required for visual review.\n" + SERVER_INSTRUCTIONS + "\n");
    process.stderr.write(`Shared skill: ${path.join(guideRoot(root), ".agents/skills/pixel-animation/SKILL.md")} (also available as MCP resource libresprite://skills/pixel-animation).\n`);
  } finally { prompt?.close(); }
}
