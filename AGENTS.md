# AGENTS.md

## Cursor Cloud specific instructions

This repo has two products:

- **`gm_bench/`** — a stdlib-only Python package (CLI + local web GUI) for the GM-Bench
  simulator. No runtime dependencies; dev tooling is `pytest`, `jsonschema`, `ruff`.
- **`web/`** — a Vite + React + TypeScript public landing site, managed with **Bun**.

### Python (`gm_bench`)

- Use `python3` (there is no `python` binary on this image). Requires Python >= 3.11.
- Dev deps install into `~/.local`, and the console scripts (`pytest`, `ruff`, `gm-bench`)
  land in `~/.local/bin`, which is **not on `PATH`**. Always invoke via the module form:
  - Lint: `python3 -m ruff format --check gm_bench examples tests` then
    `python3 -m ruff check gm_bench examples tests` (matches `.github/workflows/lint.yml`).
  - Tests: `python3 -m pytest -q`.
  - CLI: `python3 -m gm_bench run --agent value --seeds 1 --seasons 3` (see `README.md`
    for all subcommands).
  - GUI: `python3 -m gm_bench gui --port 8765`, then open `http://127.0.0.1:8765`.
- `run`/`compare`/`evaluate` and the GUI log to `data/gm_bench.sqlite` by default
  (override with `GM_BENCH_DB=...`, disable with `--no-log`).
- Model-backed subcommands (`model`, agents under `examples/`) need external provider
  credentials (e.g. `LLM_API_KEY`) or a local tool (Ollama/Codex/Claude/opencode) that is
  not installed here; scripted baselines (`value`, `random`, etc.) run fully offline.

### Web (`web/`)

- Managed with **Bun** (installed at `~/.bun/bin`, added to `PATH` via `~/.bashrc`).
  In a non-login shell use the full path `~/.bun/bin/bun`.
- Commands (run in `web/`): `bun install`, `bun dev`, `bun run lint` (oxlint),
  `bun run build`.
- Gotcha: `bun dev` binds to `localhost` only, not `127.0.0.1`. `curl http://127.0.0.1:5173`
  fails with connection refused — use `http://localhost:5173` (pass `--host` to expose it).
