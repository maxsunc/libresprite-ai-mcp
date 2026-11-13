// GPL-2.0-only.
import assert from "node:assert/strict";
import test from "node:test";
import { windowsPipeName, validWindowsPipe, endpointError } from "../endpoint.js";

test("Windows endpoints remain local named pipes, not resolved file paths", () => {
  const pipe = windowsPipeName("C:\\a checkout with spaces");
  assert.ok(validWindowsPipe(pipe));
  assert.equal(endpointError(pipe, "win32"), undefined);
  assert.equal(pipe, windowsPipeName("c:\\a checkout with spaces"));
  assert.notEqual(pipe, windowsPipeName("C:\\another checkout"));
  for (const value of ["C:\\bridge.sock", "\\\\server\\pipe\\libresprite-ai-test", "\\\\.\\pipe\\other", pipe + "\\child", pipe + ":stream", "\\\\.\\pipe\\libresprite-ai-" + "x".repeat(101)]) {
    assert.equal(validWindowsPipe(value), false, value);
    assert.ok(endpointError(value, "win32"), value);
  }
  assert.equal(endpointError("/tmp/b.sock", "linux"), undefined);
  assert.ok(endpointError("relative.sock", "linux"));
  assert.ok(endpointError("/" + "a".repeat(104), "darwin"));
});
