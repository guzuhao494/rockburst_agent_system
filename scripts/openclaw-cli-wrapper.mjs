import { pathToFileURL } from "node:url";

const cliPath = process.env.OPENCLAW_CLI_PATH;
if (!cliPath) {
  throw new Error("OPENCLAW_CLI_PATH is not set");
}

const resolvedArgs = [];
for (const arg of process.argv.slice(2)) {
  if (arg === "--message-from-env") {
    const encoded = process.env.OPENCLAW_MESSAGE_B64;
    if (!encoded) {
      throw new Error("OPENCLAW_MESSAGE_B64 is not set");
    }
    resolvedArgs.push("--message", Buffer.from(encoded, "base64").toString("utf8"));
    continue;
  }
  resolvedArgs.push(arg);
}

process.argv = [process.argv[0], cliPath, ...resolvedArgs];
await import(pathToFileURL(cliPath).href);
