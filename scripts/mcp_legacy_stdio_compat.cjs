#!/usr/bin/env node
"use strict";

// Let MCP 2026 clients fall back cleanly when a proxied upstream still requires
// the legacy initialize handshake. All non-discovery traffic is passed through
// byte-for-byte; request payloads and credentials are never logged.

const readline = require("node:readline");
const { spawn } = require("node:child_process");

const separator = process.argv.indexOf("--");
if (separator < 0 || separator === process.argv.length - 1) {
  process.stderr.write("usage: mcp_legacy_stdio_compat.cjs -- COMMAND [ARG ...]\n");
  process.exit(2);
}

const command = process.argv[separator + 1];
const args = process.argv.slice(separator + 2);
const child = spawn(command, args, { stdio: ["pipe", "pipe", "pipe"] });

child.stdout.pipe(process.stdout);
child.stderr.pipe(process.stderr);

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let childInputClosed = false;
const closeChildInput = () => {
  if (childInputClosed) return;
  childInputClosed = true;
  child.stdin.end();
};
input.on("line", (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    child.stdin.write(`${line}\n`);
    return;
  }

  if (message && message.method === "server/discover" && message.id !== undefined) {
    process.stdout.write(
      `${JSON.stringify({
        jsonrpc: "2.0",
        id: message.id,
        error: { code: -32601, message: "Method not found" },
      })}\n`,
    );
    return;
  }
  child.stdin.write(`${line}\n`);
});
input.on("close", closeChildInput);
// On Windows, readline's close event can lag after a redirected parent stdin
// reaches EOF. Forward the stream end directly so the MCP child can exit.
process.stdin.on("end", closeChildInput);

child.on("error", (error) => {
  process.stderr.write(`failed to start MCP bridge: ${error.message}\n`);
  process.exitCode = 1;
});
child.on("exit", (code, signal) => {
  if (signal) {
    process.removeAllListeners(signal);
    process.kill(process.pid, signal);
    return;
  }
  process.exitCode = code ?? 1;
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
