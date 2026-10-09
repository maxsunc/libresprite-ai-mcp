import path from "node:path";
import { fileURLToPath } from "node:url";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createServer } from "./server.js";
import { resolveOptions } from "./config.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const options = resolveOptions(root);
const args = process.argv.slice(2);
if (args.length && !(args[0] === "--doctor" && (args.length === 1 || (args.length === 2 && args[1] === "--connect")))) {
  throw new Error("Usage: node dist/index.js [--doctor [--connect]]");
}
if (args[0] === "--doctor") {
  const { diagnose } = await import("./doctor.js");
  const result = await diagnose(options, process.argv.includes("--connect"));
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}
const { server, close } = createServer(options);

let closing = false;
async function shutdown() {
  if (closing) return;
  closing = true;
  close();
  await server.close();
  // Never kill a GUI process that may hold unsaved user work.
  process.exit(0);
}
process.once("SIGINT", () => { void shutdown(); });
process.once("SIGTERM", () => { void shutdown(); });
// The SDK stdio transport does not translate stdin EOF into transport close.
process.stdin.once("end", () => { void shutdown(); });
process.stdin.once("close", () => { void shutdown(); });
process.stdout.once("error", () => { void shutdown(); });
await server.connect(new StdioServerTransport());
