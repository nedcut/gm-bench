#!/usr/bin/env bash
# Resume Claude Sonnet medium leaderboard after quota death on seed 11.
# Serial only. Merges seed-11 checkpoint with a fresh seeds 12-18 run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHECKPOINT="${CHECKPOINT:-results/diagnostics/claude-sonnet-medium.serial-quota-fail.json}"
CONTINUATION="${CONTINUATION:-results/diagnostics/claude-sonnet-medium.seeds-12-18.json}"
OUTPUT="${OUTPUT:-results/leaderboard/claude-sonnet-medium.json}"
PROGRESS="${PROGRESS:-logs/runs/claude-sonnet-medium.seeds-12-18.progress.log}"

mkdir -p logs/runs results/diagnostics results/leaderboard

if [[ ! -f "$CHECKPOINT" ]]; then
  echo "missing checkpoint: $CHECKPOINT" >&2
  exit 1
fi

echo "=== resume sonnet medium seeds 12-18 start $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee "$PROGRESS"
echo "guards: GM_BENCH_WORKERS=1 --workers 1 CLAUDE_EFFORT=medium" | tee -a "$PROGRESS"
echo "checkpoint=$CHECKPOINT" | tee -a "$PROGRESS"

# Belt-and-suspenders serial: env + flag. Never raise workers for Claude.
PYTHONUNBUFFERED=1 GM_BENCH_WORKERS=1 CLAUDE_EFFORT=medium python3 -m gm_bench model \
  --provider claude \
  --model sonnet \
  --preset leaderboard \
  --seeds 12 13 14 15 16 17 18 \
  --repeats 3 \
  --workers 1 \
  --agent-timeout 300 \
  --verbose \
  --json \
  --no-log \
  > "$CONTINUATION" \
  2>> "$PROGRESS"
echo "continuation exit=$? finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$PROGRESS"

python3 scripts/merge_model_panel.py \
  --base "$CHECKPOINT" \
  --keep-seeds 11 \
  --add "$CONTINUATION" \
  --output "$OUTPUT" \
  --validate sota-v1 | tee -a "$PROGRESS"

python3 web/scripts/build_leaderboard.py | tee -a "$PROGRESS"
echo "=== resume complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$PROGRESS"
