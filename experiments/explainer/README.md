# Explainer v1 — reproduce

Design and findings: `wiki/pages/explainer-model.md`, `wiki/pages/concept-discovery.md`.
All commands: `uv run --extra ml python -m claude_chess.explainer <cmd>` (`--help` lists them).

```sh
# 0. data (Lichess CC0): puzzles + first 400 MB of the cloud-eval DB
mkdir -p data/raw && cd data/raw
curl -O https://database.lichess.org/lichess_db_puzzle.csv.zst
curl -r 0-419430399 -o lichess_db_eval.head400m.jsonl.zst https://database.lichess.org/lichess_db_eval.jsonl.zst
cd ../..

# 1. featurize (~15 min on 9 cores) + salience scale
python -m claude_chess.explainer data --kind eval --n 400000 --workers 9
python -m claude_chess.explainer data --kind puzzle --n 150000 --workers 9
python -m claude_chess.explainer stats

# 2. teacher labels (Claude Opus 5.5 via claude -p; resumable; halts on plan limits)
python -m claude_chess.explainer teacher --n-train 1300 --n-val 150 --n-test 150 --workers 4 --budget 34

# 3. encoder (MLX, ~35-60 min) + test-split eval + random-trunk probe baseline
python -m claude_chess.explainer train-encoder --out data/models/enc_v1 --epochs 5
python -m claude_chess.explainer eval-encoder --encoder data/models/enc_v1
python -m claude_chess.explainer train-encoder --out data/models/enc_rand --random-trunk --epochs 0.6
python -m claude_chess.explainer eval-encoder --encoder data/models/enc_rand --out experiments/explainer/encoder_eval_random.json

# 4. concept discovery (SAEs + Claude naming, ~$1.6)
python -m claude_chess.explainer discover

# 5. student LM (Qwen3-1.7B LoRA via mlx-lm, ~1.5 h on M1 Pro) + evaluation
python -m claude_chess.explainer build-sft
python -m claude_chess.explainer train-lm --iters 900 --batch-size 2 --grad-accumulation 2
python -m claude_chess.explainer eval-lm --n 100
python scripts/explainer_engine_free.py 30

# 6. use it / report
python -m claude_chess.explainer explain "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
python -m claude_chess.explainer explain "<FEN>" --engine-free
python scripts/explainer_report.py experiments/explainer/showcase.html
```

## Round 2: joint model (picks the move AND explains) + GUI

```sh
# data for the three variants (same positions/candidates; ~1 min each)
python -c "from pathlib import Path; from claude_chess.explainer import joint as J; \
  J.build_sft(Path('data/sft_joint_A'), Path('data/models/enc_v1'), order='reason_first', with_relations=True)"
#   ... order='move_first' -> data/sft_joint_B ; with_relations=False -> data/sft_joint_C
python -m claude_chess.explainer train-lm --data data/sft_joint_A --adapter data/models/joint_A \
  --iters 1573 --batch-size 2 --grad-accumulation 2        # ~2 h; then B and C the same way
python scripts/explainer_round2.py                         # picks checkpoints, evaluates, links joint_best

# play it (http://localhost:8766); --player composite = encoder picks, v1.1 student explains
python scripts/play.py
```

One GPU job at a time on a 16 GB Mac (two MLX jobs → Metal out-of-memory).
