import { test, expect } from "bun:test";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "vite";
import { simulatorBundle } from "./simulatorBundle";

test("dev startup replaces a stale archive with an importable game bundle", async () => {
  const root = await mkdtemp(join(tmpdir(), "gm-bench-dev-bundle-"));
  const destination = join(root, "gm_bench.zip");
  await writeFile(destination, "stale archive without browser_game");
  const server = await createServer({
    configFile: false,
    root,
    plugins: [simulatorBundle(destination)],
    server: { host: "127.0.0.1", port: 0 },
  });
  try {
    await server.listen();
    const address = server.httpServer!.address();
    if (!address || typeof address === "string")
      throw new Error("Missing dev server port");
    const response = await fetch(
      `http://127.0.0.1:${address.port}/gm_bench.zip`,
    );
    expect(response.ok).toBe(true);
    expect(Buffer.from(await response.arrayBuffer())).toEqual(
      await readFile(destination),
    );
    // Import from the ZIP alone, with no checkout on Python's import path.
    const result = execFileSync(
      "python3",
      [
        "-I",
        "-c",
        `
import sys
sys.path.insert(0, sys.argv[1])
from gm_bench.browser_game import BrowserGame
assert len(BrowserGame(1).snapshot()["team"]["roster"]) == 23
print("game ready")
`,
        destination,
      ],
      { cwd: root, encoding: "utf8" },
    );
    expect(result.trim()).toBe("game ready");
    const before = (await stat(destination)).mtimeMs;
    const second = await createServer({
      configFile: false,
      root,
      plugins: [simulatorBundle(destination)],
      server: { host: "127.0.0.1", port: 0 },
    });
    try {
      await second.listen();
      expect((await stat(destination)).mtimeMs).toBe(before);
    } finally {
      await second.close();
    }
  } finally {
    await server.close();
    await rm(root, { recursive: true, force: true });
  }
}, 15000);
