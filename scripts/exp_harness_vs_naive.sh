#!/usr/bin/env bash
# Harness vs no harness, per model, against the Maia ladder. See wiki/pages/results.md.
# Usage: scripts/exp_harness_vs_naive.sh [PREFIX] [MODELS...]
#   e.g. scripts/exp_harness_vs_naive.sh exp1 claude-sonnet-5 claude-haiku-4-5-20251001
# Then: uv run claude-chess report PREFIX --out experiments/PREFIX
set -euo pipefail
PREFIX=${1:-exp1}; shift || true
MODELS=${*:-"claude-sonnet-5 claude-haiku-4-5-20251001"}
LEVELS=${LEVELS:-"1100 1300 1500 1700 1900"}
GAMES=${GAMES:-4}
JOBS=${JOBS:-5}
COMMON="--games $GAMES --parallel $GAMES --max-plies 200 --backend cli --thinking 0 \
  --resign-cp 1000 --resign-plies 6"
jobs=()
for model in $MODELS; do
  short=$( [[ $model == *haiku* ]] && echo haiku || ([[ $model == *sonnet* ]] && echo sonnet || echo opus) )
  for arm in harness naive; do
    i=0
    for lvl in $LEVELS; do
      if [[ $arm == harness ]]; then spec="hybrid-ctx --threat-agent"; else spec="naive"; fi
      # Same opening offset for both arms at a level -> paired design (same openings/colours).
      jobs+=("uv run claude-chess match --white $spec --black maia:$lvl --model $model $COMMON \
        --opening-offset $((i * 2)) --label ${PREFIX}-${short}-${arm}-maia${lvl}")
      i=$((i + 1))
    done
  done
done
mkdir -p logs
printf '%s\n' "${jobs[@]}" | xargs -P "$JOBS" -I{} bash -c '{} > "logs/$(echo "{}" | grep -o "label [^ ]*" | cut -d" " -f2).log" 2>&1'
