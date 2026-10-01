import { randomUUID } from "node:crypto";
import { createConnection, type Socket } from "node:net";

export type BridgeResult = Record<string, unknown>;

export class BridgeError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
    this.name = "BridgeError";
  }
}

/** One request at a time. A timeout/disconnect never automatically retries an
 * edit: the editor may already have committed it. Reconnect and inspect first. */
export class BridgeClient {
  private socket?: Socket;
  private input = "";
  private queue: Promise<unknown> = Promise.resolve();
  private closed = false;
  private pending?: {
    id: string;
    resolve: (value: BridgeResult) => void;
    reject: (error: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  };
  sessionId?: string;
  private supportedMethods?: ReadonlySet<string>;

  constructor(readonly socketPath: string, private readonly timeoutMs = 10_000) {}

  request(method: string, params: BridgeResult = {}): Promise<BridgeResult> {
    const next = this.queue.then(() => this.send(method, params));
    this.queue = next.catch(() => undefined);
    return next;
  }

  close(): void {
    this.closed = true;
    this.fail(new BridgeError("DISCONNECTED", "Bridge connection closed; no requests were retried."));
  }

  private fail(error: Error): void {
    const pending = this.pending;
    this.pending = undefined;
    if (pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    const socket = this.socket;
    this.socket = undefined;
    socket?.destroy();
    this.input = "";
    // Do not carry a session token into a new connection/process.
    this.sessionId = undefined;
    this.supportedMethods = undefined;
  }

  private async connect(): Promise<void> {
    if (this.closed) throw new BridgeError("DISCONNECTED", "This bridge client has been closed.");
    if (this.socket && !this.socket.destroyed) return;
    await new Promise<void>((resolve, reject) => {
      const socket = createConnection(this.socketPath);
      this.socket = socket;
      const timer = setTimeout(() => {
        reject(new BridgeError("CONNECT_TIMEOUT", "Could not connect to the LibreSprite bridge."));
        this.fail(new BridgeError("CONNECT_TIMEOUT", "Bridge connection timed out."));
      }, this.timeoutMs);
      socket.once("connect", () => {
        clearTimeout(timer);
        resolve();
      });
      socket.on("error", (error) => {
        clearTimeout(timer);
        reject(new BridgeError("CONNECTION_FAILED", error.message));
        if (this.socket === socket) this.fail(this.pending
          ? new BridgeError("OUTCOME_UNKNOWN", `Bridge connection failed during an operation (${error.message}). It may have completed; reconnect and inspect before another edit.`)
          : new BridgeError("CONNECTION_FAILED", error.message));
      });
      socket.on("close", () => {
        clearTimeout(timer);
        reject(new BridgeError("DISCONNECTED", "LibreSprite disconnected."));
        if (this.socket === socket) this.fail(new BridgeError("OUTCOME_UNKNOWN", "LibreSprite disconnected. An in-flight edit may have completed; reconnect and inspect before issuing another edit."));
      });
      socket.setEncoding("utf8");
      socket.on("data", (data: string) => {
        if (this.socket !== socket) return;
        this.input += data;
        if (Buffer.byteLength(this.input) > 8 * 1024 * 1024 + 1) {
          this.fail(new BridgeError("INVALID_RESPONSE", "Bridge response exceeds the protocol limit."));
          return;
        }
        const newline = this.input.indexOf("\n");
        if (newline < 0) return;
        const line = this.input.slice(0, newline);
        this.input = this.input.slice(newline + 1);
        try {
          const response = JSON.parse(line) as {
            jsonrpc?: string;
            id?: unknown;
            result?: BridgeResult;
            error?: { message?: string; data?: { code?: string } };
          };
          const pending = this.pending;
          if (!pending || response.jsonrpc !== "2.0" || response.id !== pending.id || this.input.length) {
            throw new Error("Unexpected response ID, protocol, or extra data.");
          }
          clearTimeout(pending.timer);
          this.pending = undefined;
          if (response.error) {
            pending.reject(new BridgeError(response.error.data?.code ?? "BRIDGE_ERROR", response.error.message ?? "Native bridge failed."));
          } else if (response.result && typeof response.result === "object" && !Array.isArray(response.result)) {
            pending.resolve(response.result);
          } else {
            pending.reject(new BridgeError("INVALID_RESPONSE", "Native bridge returned an invalid result."));
            this.fail(new BridgeError("INVALID_RESPONSE", "Invalid result."));
          }
        } catch (error) {
          this.fail(new BridgeError("INVALID_RESPONSE", error instanceof Error ? error.message : "Invalid JSON response."));
        }
      });
    });
  }

  private async send(method: string, params: BridgeResult): Promise<BridgeResult> {
    await this.connect();
    if (this.closed || !this.socket || this.socket.destroyed) {
      throw new BridgeError("DISCONNECTED", "Bridge connection closed before the request was sent.");
    }
    if (method !== "status" && !this.sessionId) {
      throw new BridgeError("NOT_CONNECTED", "Call libresprite_connect after connecting or reconnecting, then explicitly resume before editing.");
    }
    if (method !== "status" && this.supportedMethods && !this.supportedMethods.has(method)) {
      throw new BridgeError("UNSUPPORTED_METHOD", `This editor does not support ${method}. Rebuild LibreSprite and launch a NEW development window; running windows keep their old bridge.`);
    }
    // Capture the token at execution time, not when a request entered the queue.
    const payload = method === "status" ? params : { ...params, sessionId: this.sessionId };
    const id = randomUUID();
    const line = JSON.stringify({ jsonrpc: "2.0", id, method, params: payload }) + "\n";
    if (Buffer.byteLength(line) > 1024 * 1024) throw new BridgeError("REQUEST_TOO_LARGE", "Split the edit into smaller batches.");
    const result = await new Promise<BridgeResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.fail(new BridgeError("OUTCOME_UNKNOWN", "Bridge timed out. The operation may have completed; reconnect and inspect. No automatic retry was attempted."));
      }, this.timeoutMs);
      this.pending = { id, resolve, reject, timer };
      this.socket!.write(line);
    });
    if (method === "status") {
      if (result.protocolVersion !== 1 || typeof result.sessionId !== "string") {
        this.fail(new BridgeError("PROTOCOL_MISMATCH", "Unsupported native bridge version."));
        throw new BridgeError("PROTOCOL_MISMATCH", "Unsupported native bridge version.");
      }
      this.sessionId = result.sessionId;
      if (Array.isArray(result.methods) && result.methods.every((method) => typeof method === "string")) {
        this.supportedMethods = new Set(result.methods as string[]);
      }
    }
    return result;
  }
}
