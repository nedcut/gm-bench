import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { Plugin } from "vite";

// Generate before Vite resolves the worker import, in both dev and production.
// Only replace changed bytes: a concurrent build must not reload an active game.
export function simulatorBundle(
  destination = resolve(import.meta.dirname, "../.generated/gm_bench.zip"),
): Plugin {
  return {
    name: "gm-bench-simulator-bundle",
    buildStart() {
      const temporary = mkdtempSync(join(tmpdir(), "gm-bench-source-"));
      try {
        const archive = join(temporary, "gm_bench.zip");
        execFileSync(
          "python3",
          [
            resolve(
              import.meta.dirname,
              "../../scripts/build_web_replay_bundle.py",
            ),
            "--bundle",
            archive,
          ],
          { stdio: "pipe" },
        );
        const bytes = readFileSync(archive);
        if (
          !existsSync(destination) ||
          !bytes.equals(readFileSync(destination))
        ) {
          mkdirSync(dirname(destination), { recursive: true });
          writeFileSync(destination, bytes);
        }
      } finally {
        rmSync(temporary, { recursive: true, force: true });
      }
    },
  };
}
