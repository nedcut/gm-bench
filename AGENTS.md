# AGENTS.md

## Environment scope

For local development, use the repository environment and current project
configuration (`pyproject.toml`, `uv.lock`, and `.venv`). The commands below describe
the Cursor Cloud image; its PATH and installed-tool assumptions do not apply to
other machines. Inspect the current environment before reporting a missing tool.
Keep Claude and other subscription- or rate-limited CLI usage serial wherever the
adapter runs. These instructions do not authorize paid model runs or publication.

## Decision log (lab notebook)

`docs/lab_notebook.html` is the internal record of how scoring, contract and
methodology decisions were made (not the public site). Keep it in the loop:

- **Before** working on scoring, contracts, the simulator's rules or a
  methodology question, read its entries (newest first) so you build on what
  was already tried and decided instead of re-deriving or contradicting it.
- **After** a decision, or a finding that changes one, add a dated entry:
  what was tried, what it showed, what was decided, with its charts.
- Cite a committed diagnostic or published row for every number. Never put
  private seeds or per-episode panel scores in it.

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
- **Never parallelize Claude (or other subscription/rate-limited CLIs).** Model adapters
  default to serial (`workers=1`), but `GM_BENCH_WORKERS` / `--workers N` overrides that.
  On 2026-07-11 a Claude Sonnet leaderboard panel with parallel fan-out burned a full
  Claude Pro **5h usage limit in ~5 minutes** and produced an invalid result
  (fail_rate 0.873; the multi-megabyte failed artifact was intentionally not retained).
  Always run Claude with explicit serial workers:
  `GM_BENCH_WORKERS=1` (and do not set a higher global `GM_BENCH_WORKERS` when Claude is
  next). Smoke with `--preset smoke` before any full panel. Full serial panel is hours
  of quota, not minutes — budget a whole 5h window on purpose.

### GM-Bench 2.0 (`gm_bench/agentic/`, `gm-bench agentic`)

- The contract is frozen at agentic fingerprint `07de948a4f4afbae`. It covers
  `gm_bench/agentic/{tools,brief,episode,mcp_server}.py` byte for byte: any edit,
  even to a docstring or comment, fails `tests/test_agentic_mcp.py` and invalidates
  every committed row. Changes that belong in a new contract go to
  `docs/bench_v2_1_queue.md`. Driver files (`gm_bench/agentic/provenance.py` lists
  them) may change; each row records the driver commit that played it.
- `--isolation container` needs Docker with the daemon running. Private-panel runs
  (`scripts/run_bench_v2_panel_from_keychain.py`) always pass `--isolation container`:
  a same-user harness can read the private seeds from the run directory.
- `agentic --harness claude` (and `codex`) spends subscription quota. The driver is
  serial; run one harness at a time and smoke one short episode before a panel.
  Operator guide: `docs/agentic_lane.md`.

### GM-Bench 2.1 (`gm_bench/v21/`, `--contract 2.1`)

- Built on top of 1.0 and 2.0 without editing either: `League21`, score-v2
  and `AgenticEpisode21` subclass or wrap the frozen code. Never put a 2.1
  change into a 1.0 or 2.0 contract source.
- Frozen at fingerprint `282dbf382c4ee56c`: model rows exist under it, so
  `gm_bench/v21/{rules,scoring,runner,episode}.py` must not change (pinned
  in `tests/test_v21.py`); a change is a new version. Spec:
  `docs/bench_v2_1_spec.md`.
- Lane: `config/bench_v21_lane.json` (same private panel as 2.0, 2.1
  reference pins); rows in `results/agentic_v21/`, 2.0 rows stay in
  `results/agentic/`.
- `gm-bench agentic` defaults to 2.0; pass `--contract 2.1` (the panel
  launcher passes it through). Paid runs follow the 2.0 rules (serial
  within a provider, smoke first, price checked first).

### Web (`web/`)

- Managed with **Bun** (installed at `~/.bun/bin`, added to `PATH` via `~/.bashrc`).
  In a non-login shell use the full path `~/.bun/bin/bun`.
- Commands (run in `web/`): `bun install`, `bun dev`, `bun run lint` (oxlint),
  `bun run build`.
- Gotcha: `bun dev` binds to `localhost` only, not `127.0.0.1`. `curl http://127.0.0.1:5173`
  fails with connection refused — use `http://localhost:5173` (pass `--host` to expose it).
