import { loadPyodide, type PyodideAPI } from "pyodide";
import { fixtureUrl } from "../replayData";

const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.6/full/";
const BUNDLE_URL = new URL(`${import.meta.env.BASE_URL}replay/gm_bench.zip`, self.location.origin).toString();
// The browsable episode and the verified episode must be the same file, so the
// path is stated once, in replayData.
const FIXTURE_URL = new URL(fixtureUrl(), self.location.origin).toString();

type RequestMessage = { type: "verify" };
type WorkerMessage =
  | { type: "status"; status: "loading" | "running" }
  | { type: "success"; decisions: number; state_digest: string }
  | { type: "error"; message: string };

let runtime: Promise<PyodideAPI> | undefined;

function post(message: WorkerMessage): void {
  self.postMessage(message);
}

async function loadRuntime(): Promise<PyodideAPI> {
  if (!runtime) {
    runtime = loadPyodide({ indexURL: PYODIDE_INDEX_URL });
  }
  return runtime;
}

async function verifyFixture(): Promise<void> {
  post({ type: "status", status: "loading" });
  const pyodide = await loadRuntime();
  const [bundleResponse, fixtureResponse] = await Promise.all([fetch(BUNDLE_URL), fetch(FIXTURE_URL)]);
  if (!bundleResponse.ok || !fixtureResponse.ok) {
    throw new Error("The replay files are unavailable. Check your connection and try again.");
  }
  const [bundle, fixture] = await Promise.all([
    bundleResponse.arrayBuffer(),
    fixtureResponse.json() as Promise<Record<string, unknown>>,
  ]);
  pyodide.FS.writeFile("/tmp/gm_bench.zip", new Uint8Array(bundle));
  pyodide.globals.set("fixture_json", JSON.stringify(fixture));
  post({ type: "status", status: "running" });
  const result = await pyodide.runPythonAsync(`
import json
import sys
sys.path.insert(0, "/tmp/gm_bench.zip")
from gm_bench.recorder import validate_replay_fixture
json.dumps(validate_replay_fixture(json.loads(fixture_json)))
`);
  const summary = JSON.parse(String(result)) as { decisions: number; state_digest: string };
  post({ type: "success", ...summary });
}

self.addEventListener("message", (event: MessageEvent<RequestMessage>) => {
  if (event.data?.type !== "verify") return;
  verifyFixture().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : "Replay verification failed.";
    post({ type: "error", message });
  });
});
