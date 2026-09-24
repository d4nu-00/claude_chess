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
ARMS=${ARMS:-"harness naive"}
CTX=${CTX:-2}   # context version for the harness arm (3 = relations/last move/deltas/material check)
COMMON="--games $GAMES --parallel $GAMES --max-plies 200 --backend cli --thinking 0 \
  --resign-cp 1000 --resign-plies 6"
jobs=()
for model in $MODELS; do
  short=$( [[ $model == *haiku* ]] && echo haiku || ([[ $model == *sonnet* ]] && echo sonnet || echo opus) )
  for arm in $ARMS; do
    for lvl in $LEVELS; do
      if [[ $arm == harness ]]; then spec="hybrid-ctx --threat-agent --ctx-version $CTX"; else spec="naive"; fi
      # Opening offset is a function of the Maia level only, so both arms (and any later
      # re-run with a subset of LEVELS) play identical openings/colours: a paired design.
      jobs+=("uv run claude-chess match --white $spec --black maia:$lvl --model $model $COMMON \
        --opening-offset $(((lvl - 1100) / 100)) --label ${PREFIX}-${short}-${arm}-maia${lvl}")
    done
  done
done
mkdir -p logs
printf '%s\n' "${jobs[@]}" | xargs -P "$JOBS" -I{} bash -c '{} > "logs/$(echo "{}" | grep -o "label [^ ]*" | cut -d" " -f2).log" 2>&1'
