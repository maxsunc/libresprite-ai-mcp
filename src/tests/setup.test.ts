// GPL-2.0-only. No live editor, agent configuration, or personal artwork is used.
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { chmod, cp, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { clientConfig, clients, formatConfig, installSkill, mergeConfig, writeConfig } from "../setup.js";
import { createServer } from "../server.js";
import { guideRoot, SERVER_INSTRUCTIONS } from "../guides.js";
import { resolveOptions } from "../config.js";
import { windowsPipeName } from "../endpoint.js";

const exec = promisify(execFile);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const options = { assetRoot: path.resolve("Artwork é with spaces"), executable: path.resolve("Editor é/editor"), socketPath: "test-endpoint" };

async function fixture(): Promise<string> { return mkdtemp(path.join(os.tmpdir(), "lsai-setup-")); }
async function fakeEditor(filename: string): Promise<void> {
  await mkdir(path.join(path.dirname(filename), "data"), { recursive: true });
  await writeFile(path.join(path.dirname(filename), "data/gui.xml"), "test resources");
  await writeFile(filename, "#!/bin/sh\ntouch \"$0.was-run\"\n", { mode: 0o700 });
  await chmod(filename, 0o700);
}

test("all setup profiles generate absolute commands, explicit artwork/runtime paths, and their documented shapes", () => {
  for (const client of clients) {
    const config = clientConfig(client, root, options);
    const text = formatConfig(client, config);
    assert.ok(text.includes("LIBRESPRITE_ASSET_ROOT"), client);
    assert.ok(text.includes("LIBRESPRITE_EXECUTABLE"), client);
    assert.ok(text.includes("LIBRESPRITE_SOCKET"), client);
    if (client === "codex") {
      assert.ok(text.startsWith("[mcp_servers.libresprite]\n"));
      assert.ok(text.includes(`command = ${JSON.stringify(process.execPath)}`));
      assert.ok(text.includes(`LIBRESPRITE_ASSET_ROOT = ${JSON.stringify(options.assetRoot)}`));
      assert.throws(() => mergeConfig(client, {}, config), /preview-only/);
    } else {
      assert.deepEqual(JSON.parse(text), config);
      const container = client === "vscode" ? config.servers : client === "opencode-v2"
        ? (config.mcp as Record<string, unknown>).servers : config.mcpServers;
      const entry = (container as Record<string, Record<string, unknown>>).libresprite!;
      assert.deepEqual(client === "opencode-v2" ? entry.command : [entry.command, ...(entry.args as string[])],
        [process.execPath, path.join(root, "dist/index.js")]);
      assert.deepEqual(client === "opencode-v2" ? entry.environment : entry.env, {
        LIBRESPRITE_ASSET_ROOT: options.assetRoot, LIBRESPRITE_EXECUTABLE: options.executable, LIBRESPRITE_SOCKET: options.socketPath,
      });
      if (client === "pi") assert.equal(entry.exposure, "deferred");
      if (client === "vscode") assert.equal(entry.type, "stdio");
      const original = { privateSetting: { token: "keep me" } };
      const merged = mergeConfig(client, original, config);
      assert.deepEqual(merged.privateSetting, original.privateSetting);
      assert.deepEqual(original, { privateSetting: { token: "keep me" } });
      assert.deepEqual(mergeConfig(client, merged, config), merged);
    }
  }
});

test("JSON settings merges preserve unrelated data, back up exact bytes, are idempotent and refuse conflicts/invalid containers", async () => {
  const directory = await fixture();
  try {
    const filename = path.join(directory, "settings.json");
    const original = '{"theme":"dark", "mcpServers":{"other":{"command":"keep","env":{"TOKEN":"private"}}}}\r\n';
    await writeFile(filename, original);
    const generated = clientConfig("cursor", root, options);
    const backup = await writeConfig(filename, "cursor", generated);
    assert.equal(await readFile(backup!, "utf8"), original);
    const merged = JSON.parse(await readFile(filename, "utf8"));
    assert.equal(merged.theme, "dark");
    assert.equal(merged.mcpServers.other.env.TOKEN, "private");
    assert.equal(await writeConfig(filename, "cursor", generated), undefined);
    assert.equal((await readdir(directory)).length, 2, "No extra backup/temp/lock on a repeated setup");
    await assert.rejects(writeConfig(filename, "cursor", clientConfig("cursor", root, { ...options, assetRoot: "changed" })), /already exists/);
    assert.deepEqual(JSON.parse(await readFile(filename, "utf8")), merged);
    for (const data of ['{"mcpServers":[]}', '{"mcpServers":null}', '[]', '{ // JSONC\n}', '{broken']) {
      await writeFile(filename, data);
      await assert.rejects(writeConfig(filename, "cursor", generated));
      assert.equal(await readFile(filename, "utf8"), data);
    }
    const newFile = path.join(directory, "new/settings.json");
    await writeConfig(newFile, "vscode", clientConfig("vscode", root, options));
    assert.ok(JSON.parse(await readFile(newFile, "utf8")).servers.libresprite);
    await assert.rejects(writeConfig(path.join(directory, "no-toml/config.toml"), "codex", clientConfig("codex", root, options)), /preview-only/);
    assert.equal(existsSync(path.join(directory, "no-toml")), false);
    await writeFile(filename + ".libresprite-setup.lock", "another setup");
    await assert.rejects(writeConfig(filename, "cursor", generated), { code: "EEXIST" });
    assert.equal(await readFile(filename, "utf8"), "{broken");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("setup refuses settings symlinks without touching their target", async (t) => {
  const directory = await fixture();
  try {
    const original = path.join(directory, "original.json");
    const alias = path.join(directory, "alias.json");
    await writeFile(original, "{}");
    try { await symlink(original, alias); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "EPERM") { t.skip("Symlinks require OS permission"); return; } throw error; }
    await assert.rejects(writeConfig(alias, "generic", clientConfig("generic", root, options)), /symlink/);
    assert.equal(await readFile(original, "utf8"), "{}");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("portable skills install explicitly, idempotently, and never replace a different skill", async () => {
  const directory = await fixture();
  try {
    const filename = await installSkill(root, directory);
    assert.equal(await readFile(filename, "utf8"), await readFile(path.join(root, ".agents/skills/pixel-animation/SKILL.md"), "utf8"));
    assert.equal(await installSkill(root, directory), filename);
    await writeFile(filename, "a user's custom skill");
    await assert.rejects(installSkill(root, directory), /already exists/);
    assert.equal(await readFile(filename, "utf8"), "a user's custom skill");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("every MCP client receives onboarding instructions and can read shared guides without connecting to an editor", async () => {
  const app = createServer(options);
  const client = new Client({ name: "generic-test-agent", version: "1" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  try {
    await app.server.connect(serverTransport);
    await client.connect(clientTransport);
    assert.equal(client.getInstructions(), SERVER_INSTRUCTIONS);
    assert.equal((await client.listTools()).tools.length, 70);
    const resources = (await client.listResources()).resources;
    assert.deepEqual(resources.map(r => r.uri), ["libresprite://guides/getting-started", "libresprite://skills/pixel-animation"]);
    const guide = await client.readResource({ uri: resources[0]!.uri });
    assert.ok("text" in guide.contents[0]!);
    assert.equal(guide.contents[0].text, SERVER_INSTRUCTIONS);
    const skill = await client.readResource({ uri: resources[1]!.uri });
    assert.ok("text" in skill.contents[0]!);
    assert.equal(skill.contents[0].text, await readFile(path.join(root, ".agents/skills/pixel-animation/SKILL.md"), "utf8"));
  } finally { await client.close(); app.close(); await app.server.close(); }
});

test("CLI preview is read-only, rejects invalid arguments, and blocks installation when prerequisites fail", async () => {
  const directory = await fixture();
  try {
    const executable = path.join(directory, "editor");
    await fakeEditor(executable);
    const socketPath = process.platform === "win32" ? windowsPipeName(directory) : path.join(directory, "private/b.sock");
    const env = { ...process.env, LIBRESPRITE_EXECUTABLE: executable, LIBRESPRITE_SOCKET: socketPath, LIBRESPRITE_ASSET_ROOT: path.join(directory, "artwork é") };
    const args = [path.join(root, "dist/index.js"), "--setup"];
    const { stdout, stderr } = await exec(process.execPath, [...args, "--client", "generic", "--asset-root", path.join(directory, "artwork é")], { env, cwd: directory });
    const generated = JSON.parse(stdout);
    assert.equal(generated.mcpServers.libresprite.env.LIBRESPRITE_ASSET_ROOT, path.join(directory, "artwork é"));
    assert.ok(stderr.includes("[ok] executable"));
    assert.equal(existsSync(executable + ".was-run"), false);
    assert.deepEqual((await readdir(directory)).sort(), ["data", "editor"]);
    for (const flags of [[], ["--client", "unknown"], ["--client", "generic", "--write"], ["--client", "generic", "--config", "somewhere"], ["--typo"]]) {
      await assert.rejects(exec(process.execPath, [...args, ...flags], { env, cwd: directory }));
    }
    await assert.rejects(exec(process.execPath, [...args, "--client", "generic", "--write", "--config", path.join(directory, "config.json"), "--skill-dir", path.join(directory, "skills")], {
      env: { ...env, LIBRESPRITE_EXECUTABLE: path.join(directory, "missing") }, cwd: directory,
    }));
    assert.equal(existsSync(path.join(directory, "config.json")), false);
    assert.equal(existsSync(path.join(directory, "skills")), false);
    const config = path.join(directory, "config.json");
    await exec(process.execPath, [...args, "--client", "generic", "--write", "--config", config, "--skill-dir", path.join(directory, "skills")], { env, cwd: directory });
    assert.ok(JSON.parse(await readFile(config, "utf8")).mcpServers.libresprite);
    assert.ok(existsSync(path.join(directory, "skills/pixel-animation/SKILL.md")));
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("relocated packages find their editor, shared skills and resource content independently of cwd", async () => {
  await mkdir(path.join(root, "build"), { recursive: true });
  const directory = await mkdtemp(path.join(root, "build/setup-relocation-é "));
  const packageRoot = path.join(directory, "Review package é");
  const mcp = path.join(packageRoot, "mcp");
  const client = new Client({ name: "relocation-test", version: "1" });
  try {
    await cp(path.join(root, "dist"), path.join(mcp, "dist"), { recursive: true });
    await writeFile(path.join(mcp, "package.json"), '{"type":"module"}');
    await writeFile(path.join(mcp, "package-layout.json"), '{"layout":1}');
    await cp(path.join(root, ".agents/skills"), path.join(packageRoot, ".agents/skills"), { recursive: true });
    assert.equal(guideRoot(mcp), packageRoot);
    const packaged = resolveOptions(mcp, {});
    await fakeEditor(packaged.executable);
    const args = [path.join(mcp, "dist/index.js")];
    const env = { ...process.env, LIBRESPRITE_EXECUTABLE: packaged.executable, LIBRESPRITE_ASSET_ROOT: path.join(directory, "Artwork é"),
      LIBRESPRITE_SOCKET: process.platform === "win32" ? windowsPipeName(mcp) : path.join(os.tmpdir(), `lsai-setup-${process.pid}`, "b.sock") };
    const { stdout } = await exec(process.execPath, [...args, "--setup", "--client", "generic", "--skill-dir", path.join(directory, "installed")], { env, cwd: os.tmpdir() });
    assert.equal(JSON.parse(stdout).mcpServers.libresprite.args[0], args[0]);
    assert.ok(existsSync(path.join(directory, "installed/pixel-animation/SKILL.md")));
    await client.connect(new StdioClientTransport({ command: process.execPath, args, env: env as Record<string, string>, cwd: os.tmpdir(), stderr: "pipe" }));
    const skill = await client.readResource({ uri: "libresprite://skills/pixel-animation" });
    assert.ok("text" in skill.contents[0]!);
    assert.equal(skill.contents[0].text, await readFile(path.join(root, ".agents/skills/pixel-animation/SKILL.md"), "utf8"));
    assert.equal(existsSync(packaged.executable + ".was-run"), false);
  } finally { await client.close(); await rm(directory, { recursive: true, force: true }); }
});
