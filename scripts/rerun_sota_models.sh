#!/usr/bin/env bash
# Re-run local Ollama candidates on the official leaderboard panel under the
# current sota-v1 contract, then rebuild the public leaderboard dataset.
#
# Usage (from repo root):
#   GM_BENCH_WORKERS=1 bash scripts/rerun_sota_models.sh
#
# Sequential by design — Ollama cannot usefully parallelize large local models.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export GM_BENCH_WORKERS="${GM_BENCH_WORKERS:-1}"
LOG_DIR="$ROOT/logs"
RESULT_DIR="$ROOT/results/leaderboard"
mkdir -p "$LOG_DIR" "$RESULT_DIR"

models=(
  "gemma4:e4b|ollama-gemma4-e4b.json"
  "qwen3.5:latest|ollama-qwen3-5-latest.json"
)

run_one() {
  local model="$1"
  local out_name="$2"
  local out_path="$RESULT_DIR/$out_name"
  local log_path="$LOG_DIR/sota-${out_name%.json}.log"
  local tmp_path
  tmp_path="$(mktemp "$RESULT_DIR/.tmp.${out_name}.XXXXXX")"

  echo "==> $(date -u +%Y-%m-%dT%H:%M:%SZ) starting $model -> $out_name (workers=$GM_BENCH_WORKERS)"
  # Write to a temp file so a failed/interrupted run never leaves a truncated
  # JSON artifact at the public path.
  if ! uv run python -m gm_bench model \
      --provider ollama \
      --model "$model" \
      --preset leaderboard \
      --repeats 3 \
      --agent-timeout 300 \
      --verbose \
      --json \
      --no-log \
      >"$tmp_path" \
      2>"$log_path"; then
    echo "!! model run failed for $model; log: $log_path" >&2
    rm -f "$tmp_path"
    return 1
  fi
  mv "$tmp_path" "$out_path"
  echo "==> validating $out_path"
  uv run python -m gm_bench validate-result "$out_path" --policy sota-v1 --json \
    | tee "$LOG_DIR/validate-${out_name%.json}.json" || true
}

# If a gemma run is already in progress writing the final path, skip re-entry.
if pgrep -f "gm_bench model --provider ollama --model gemma4:e4b" >/dev/null 2>&1; then
  echo "gemma4:e4b already running; waiting for it to finish before sequencing"
  while pgrep -f "gm_bench model --provider ollama --model gemma4:e4b" >/dev/null 2>&1; do
    sleep 30
  done
  # Existing run wrote directly to the final path (older launcher). Validate if present.
  if [[ -s "$RESULT_DIR/ollama-gemma4-e4b.json" ]]; then
    uv run python -m gm_bench validate-result \
      "$RESULT_DIR/ollama-gemma4-e4b.json" --policy sota-v1 --json \
      | tee "$LOG_DIR/validate-ollama-gemma4-e4b.json" || true
  else
    run_one "gemma4:e4b" "ollama-gemma4-e4b.json"
  fi
  run_one "qwen3.5:latest" "ollama-qwen3-5-latest.json"
else
  for entry in "${models[@]}"; do
    IFS='|' read -r model out_name <<<"$entry"
    # Skip models that already have a complete, non-empty JSON from this session
    # only when the user sets SKIP_EXISTING=1.
    if [[ "${SKIP_EXISTING:-0}" == "1" && -s "$RESULT_DIR/$out_name" ]]; then
      if python3 -c "import json; json.load(open('$RESULT_DIR/$out_name'))" 2>/dev/null; then
        echo "skipping $out_name (SKIP_EXISTING=1 and valid JSON present)"
        continue
      fi
    fi
    run_one "$model" "$out_name"
  done
fi

echo "==> rebuilding web leaderboard"
uv run python web/scripts/build_leaderboard.py
echo "==> done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
