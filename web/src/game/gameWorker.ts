import { loadPyodide, version, type PyodideAPI } from "pyodide";
import type { GameRequest } from "./types";

let runtime: Promise<PyodideAPI> | undefined;
let engineVersion = "";
async function initialize() {
  const pyodide = await loadPyodide({
    indexURL: `https://cdn.jsdelivr.net/pyodide/v${version}/full/`,
  });
  const response = await fetch(
    `${import.meta.env.BASE_URL}replay/gm_bench.zip`,
  );
  if (!response.ok)
    throw new Error(
      `Simulator download failed (HTTP ${response.status}). Try again when connected.`,
    );
  const bytes = await response.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  engineVersion = Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
  pyodide.FS.writeFile("/tmp/gm_bench.zip", new Uint8Array(bytes));
  await pyodide.runPythonAsync(
    'import sys\nsys.path.insert(0, "/tmp/gm_bench.zip")\nfrom gm_bench.browser_game import handle_request',
  );
  return pyodide;
}

// Serialize requests even if a future UI sends more than one before completion.
let queue = Promise.resolve();
self.addEventListener("message", (event: MessageEvent<GameRequest>) => {
  const request = event.data;
  queue = queue.then(async () => {
    try {
      if (!runtime)
        runtime = initialize().catch((error) => {
          runtime = undefined;
          throw error;
        });
      const pyodide = await runtime;
      pyodide.globals.set("request_json", JSON.stringify(request));
      pyodide.globals.set("engine_version", engineVersion);
      const response = await pyodide.runPythonAsync(
        "handle_request(request_json, engine_version)",
      );
      self.postMessage({ id: request.id, ...JSON.parse(String(response)) });
    } catch (error) {
      self.postMessage({
        id: request.id,
        error:
          error instanceof Error
            ? error.message
            : "The simulator could not complete that request.",
      });
    }
  });
});
