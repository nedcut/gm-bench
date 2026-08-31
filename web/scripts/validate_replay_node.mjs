import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

// Node can use the exact pinned npm package locally. The browser worker uses
// the matching versioned CDN index URL because browsers cannot read node_modules.
const indexURL = fileURLToPath(new URL("../node_modules/pyodide/", import.meta.url));
const pyodide = await loadPyodide({ indexURL });
const bundle = await readFile(new URL("../public/replay/gm_bench.zip", import.meta.url));
pyodide.FS.writeFile("/tmp/gm_bench.zip", bundle);
const fixture = await readFile(new URL("../public/replay/replay_fixture.json", import.meta.url), "utf8");
pyodide.globals.set("fixture_json", fixture);
const result = await pyodide.runPythonAsync(`
import json
import sys
sys.path.insert(0, "/tmp/gm_bench.zip")
from gm_bench.recorder import validate_replay_fixture
json.dumps(validate_replay_fixture(json.loads(fixture_json)))
`);
console.log(`Pyodide replay verified: ${result}`);
