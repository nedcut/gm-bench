#!/usr/bin/env bash
# Re-run local Ollama candidates on the official leaderboard panel under the
# current sota-v1 contract, then rebuild the public leaderboard dataset.
#
# Usage (from repo root):
#   GM_BENCH_WORKERS=1 bash scripts/rerun_sota_models.sh
#
# Env knobs:
#   SKIP_EXISTING=1     skip a model whose output file already holds valid JSON
#   ALLOW_INELIGIBLE=1  exit 0 even when models fail sota-v1 validation
#                       (set this for known-diagnostic local models)
#
# Sequential by design — Ollama cannot usefully parallelize large local models.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export GM_BENCH_WORKERS="${GM_BENCH_WORKERS:-1}"
LOG_DIR="$ROOT/logs"
RESULT_DIR="$ROOT/results/leaderboard"
DIAGNOSTIC_DIR="$ROOT/results/diagnostics"
mkdir -p "$LOG_DIR" "$RESULT_DIR" "$DIAGNOSTIC_DIR"

models=(
  "gemma4:e4b|$RESULT_DIR/ollama-gemma4-e4b.json"
  # qwen's current run is intentionally published as a diagnostic: it fails
  # the public-leaderboard policy and therefore must not enter the official
  # artifact directory validated by CI.
  "qwen3.5:latest|$DIAGNOSTIC_DIR/ollama-qwen3-5-latest.json"
)

ineligible=()

run_one() {
  local model="$1"
  local out_path="$2"
  local out_name="${out_path##*/}"
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
  if ! uv run python -m gm_bench validate-result "$out_path" --policy sota-v1 --json \
      | tee "$LOG_DIR/validate-${out_name%.json}.json"; then
    ineligible+=("$model")
    echo "!! $model is NOT sota-v1 eligible; see $LOG_DIR/validate-${out_name%.json}.json" >&2
  fi
}

for entry in "${models[@]}"; do
  IFS='|' read -r model out_path <<<"$entry"
  out_name="${out_path##*/}"
  if [[ "${SKIP_EXISTING:-0}" == "1" && -s "$out_path" ]]; then
    if uv run python -c "import json, sys; json.load(open(sys.argv[1]))" "$out_path" 2>/dev/null; then
      echo "skipping $out_name (SKIP_EXISTING=1 and valid JSON present)"
      continue
    fi
  fi
  run_one "$model" "$out_path"
done

echo "==> rebuilding web leaderboard"
uv run python web/scripts/build_leaderboard.py
echo "==> done $(date -u +%Y-%m-%dT%H:%M:%SZ)"

if ((${#ineligible[@]})); then
  echo "!! ${#ineligible[@]} model(s) failed sota-v1 validation: ${ineligible[*]}" >&2
  echo "!! Their rows are published as diagnostics only, not sota-v1 results." >&2
  if [[ "${ALLOW_INELIGIBLE:-0}" != "1" ]]; then
    echo "!! Set ALLOW_INELIGIBLE=1 if this is expected." >&2
    exit 1
  fi
fi
