#!/usr/bin/env bash
# Safely resume Claude Sonnet medium from every zero-failure seed/repeat episode.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SEED11="${SEED11:-results/diagnostics/claude-sonnet-medium.serial-quota-fail.json}"
SEED12="${SEED12:-results/diagnostics/claude-sonnet-medium.seeds-12-18.json}"
SEED13="${SEED13:-results/diagnostics/claude-sonnet-medium.seeds-13-18.json}"
CHECKPOINT="${CHECKPOINT:-data/model_checkpoints/claude-sonnet-medium.json}"
CONTINUATION="${CONTINUATION:-results/diagnostics/claude-sonnet-medium.resumed.json}"
OUTPUT="${OUTPUT:-results/leaderboard/claude-sonnet-medium.json}"
PROGRESS="${PROGRESS:-logs/runs/claude-sonnet-medium.resume.progress.log}"

mkdir -p logs/runs results/diagnostics results/leaderboard "$(dirname "$CHECKPOINT")"
for source in "$SEED11" "$SEED12" "$SEED13"; do
  if [[ ! -s "$source" ]]; then
    echo "missing resume source: $source" >&2
    exit 1
  fi
done

echo "=== safe sonnet medium resume start $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee "$PROGRESS"
echo "guards: serial, fail-fast=2, atomic repeat checkpoint" | tee -a "$PROGRESS"

# Reuses only zero-failure episodes. Today that preserves seed 11 repeats 1-2,
# all seed 12 repeats, and seed 13 repeats 1-2. On interruption, --resume also
# reuses every subsequently completed repeat from CHECKPOINT.
PYTHONUNBUFFERED=1 GM_BENCH_WORKERS=1 CLAUDE_EFFORT=medium python3 -m gm_bench model \
  --provider claude \
  --model sonnet \
  --preset leaderboard \
  --seeds 11 12 13 14 15 16 17 18 \
  --repeats 3 \
  --workers 1 \
  --agent-timeout 300 \
  --fail-fast 2 \
  --checkpoint "$CHECKPOINT" \
  --resume \
  --resume-from "$SEED11" \
  --resume-from "$SEED12" \
  --resume-from "$SEED13" \
  --verbose \
  --json \
  --no-log \
  > "$CONTINUATION" \
  2>> "$PROGRESS"

# Never place a failed or ineligible row in the official leaderboard path.
python3 -m gm_bench validate-result "$CONTINUATION" --policy sota-v1 | tee -a "$PROGRESS"
cp "$CONTINUATION" "$OUTPUT"
python3 web/scripts/build_leaderboard.py | tee -a "$PROGRESS"
echo "=== safe resume complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$PROGRESS"
