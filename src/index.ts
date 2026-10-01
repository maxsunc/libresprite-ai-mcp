import path from "node:path";
import { fileURLToPath } from "node:url";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createServer } from "./server.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { server, close } = createServer({
  socketPath: path.resolve(process.env.LIBRESPRITE_SOCKET ?? path.join(root, ".runtime/bridge.sock")),
  executable: path.resolve(process.env.LIBRESPRITE_EXECUTABLE ?? path.join(root, "build/libresprite/bin/libresprite")),
  assetRoot: path.resolve(process.env.LIBRESPRITE_ASSET_ROOT ?? path.join(root, "assets")),
});

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
