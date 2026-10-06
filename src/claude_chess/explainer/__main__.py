"""`uv run --extra ml python -m claude_chess.explainer <command>` — see wiki/pages/explainer-model.md."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

MODELS_DIR = Path("data/models")


def _scale() -> dict[str, float]:
    from claude_chess.explainer import data as D
    p = D.DATA_DIR / "stats.json"
    return json.loads(p.read_text())["delta_scale"] if p.exists() else {}


def top_themes(data: dict, k: int = 64, min_count: int = 200) -> list[str]:
    cnt = Counter(t for s, src in zip(data["themes"], data["src"]) if src == 1 for t in str(s).split())
    return [t for t, c in cnt.most_common(k) if c >= min_count]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m claude_chess.explainer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("data", help="featurize Lichess evals/puzzles into data/explainer shards")
    d.add_argument("--kind", choices=["eval", "puzzle"], required=True)
    d.add_argument("--n", type=int, required=True)
    d.add_argument("--workers", type=int, default=8)

    sub.add_parser("stats", help="compute salience scale (per-concept delta std) -> data/explainer/stats.json")

    t = sub.add_parser("teacher", help="label selected positions with Claude (resumable)")
    t.add_argument("--n-train", type=int, default=1300)
    t.add_argument("--n-val", type=int, default=150)
    t.add_argument("--n-test", type=int, default=150)
    t.add_argument("--model", default="claude-opus-5-5")
    t.add_argument("--effort", default="medium")
    t.add_argument("--workers", type=int, default=6)
    t.add_argument("--budget", type=float, default=50.0)
    t.add_argument("--out", default="datasets/explainer_v1/teacher.jsonl")

    e = sub.add_parser("train-encoder", help="train the chess encoder (MLX)")
    e.add_argument("--out", default=str(MODELS_DIR / "enc_v1"))
    e.add_argument("--d", type=int, default=256)
    e.add_argument("--layers", type=int, default=8)
    e.add_argument("--heads", type=int, default=8)
    e.add_argument("--epochs", type=float, default=6)
    e.add_argument("--bs", type=int, default=512)
    e.add_argument("--lr", type=float, default=6e-4)
    e.add_argument("--probe-grad", action="store_true", help="let concept losses shape the trunk (ablation)")
    e.add_argument("--max-minutes", type=float, default=None)
    e.add_argument("--random-trunk", action="store_true", help="probe baseline: frozen random trunk")
    e.add_argument("--resume", default=None, help="checkpoint (.safetensors) to continue from")
    e.add_argument("--start-step", type=int, default=0)

    ee = sub.add_parser("eval-encoder", help="score an encoder checkpoint on the test split")
    ee.add_argument("--encoder", default=str(MODELS_DIR / "enc_v1"))
    ee.add_argument("--tag", default="best")
    ee.add_argument("--out", default="experiments/explainer/encoder_eval.json")

    s = sub.add_parser("build-sft", help="teacher labels -> mlx_lm chat data (train/valid/test.jsonl)")
    s.add_argument("--teacher", default="datasets/explainer_v1/teacher.jsonl")
    s.add_argument("--out", default="datasets/explainer_v1/sft")

    lt = sub.add_parser("train-lm", help="LoRA fine-tune the student LM with mlx_lm")
    lt.add_argument("--model", default="mlx-community/Qwen3-1.7B-bf16")
    lt.add_argument("--data", default="datasets/explainer_v1/sft")
    lt.add_argument("--adapter", default=str(MODELS_DIR / "lm_v1"))
    lt.add_argument("--iters", type=int, default=600)
    lt.add_argument("--batch-size", type=int, default=4)
    lt.add_argument("--lr", type=float, default=1e-4)
    lt.add_argument("--num-layers", type=int, default=16)
    lt.add_argument("--grad-accumulation", type=int, default=1)

    le = sub.add_parser("eval-lm", help="student vs teacher vs base on the held-out test split")
    le.add_argument("--teacher", default="datasets/explainer_v1/teacher.jsonl")
    le.add_argument("--model", default="mlx-community/Qwen3-1.7B-bf16")
    le.add_argument("--adapter", default=str(MODELS_DIR / "lm_v1"))
    le.add_argument("--n", type=int, default=150)
    le.add_argument("--judge-model", default="claude-opus-5-5")
    le.add_argument("--reader-model", default="claude-haiku-4-5-20251001")
    le.add_argument("--out", default="experiments/explainer/eval_lm.json")
    le.add_argument("--skip-base", action="store_true")

    dc = sub.add_parser("discover", help="SAE concept discovery on the encoder + Claude naming")
    dc.add_argument("--encoder", default=str(MODELS_DIR / "enc_v1"))
    dc.add_argument("--model", default="claude-opus-5-5")
    dc.add_argument("--n-novel", type=int, default=8)
    dc.add_argument("--n-known", type=int, default=4)

    x = sub.add_parser("explain", help="explain a position: FEN -> eval, concepts, idea")
    x.add_argument("fen")
    x.add_argument("--engine-free", action="store_true")
    x.add_argument("--model", default="mlx-community/Qwen3-1.7B-bf16")
    x.add_argument("--adapter", default=str(MODELS_DIR / "lm_v1"))
    x.add_argument("--encoder", default=str(MODELS_DIR / "enc_v1"))
    x.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "eval-encoder":
        from claude_chess.explainer import data as D
        from claude_chess.explainer import encoder as E
        model, ck = E.load(Path(args.encoder), args.tag)
        data = D.load(("eval", "puzzle"))
        bt = E.Batcher(data, _scale(), list(ck["cfg"].get("themes") or []))
        bt.c_mean, bt.c_std = ck["c_mean"], ck["c_std"]  # the checkpoint's own standardization
        bt.slim()
        res = E.evaluate(model, bt, bt.indices(2))
        res["encoder"] = args.encoder
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=1))
        print(json.dumps({k: v for k, v in res.items() if k not in ("concept_r2", "theme_auc")}))
        if "theme_auc" in res:
            print("theme AUC mean", res["theme_auc"].get("_mean"))
        return
    if args.cmd == "build-sft":
        from claude_chess.explainer import lm as L
        print(json.dumps(L.build_sft(Path(args.teacher), Path(args.out))))
    elif args.cmd == "train-lm":
        from claude_chess.explainer import lm as L
        Path(args.adapter).mkdir(parents=True, exist_ok=True)
        rc = L.train(args.model, Path(args.data), Path(args.adapter), iters=args.iters, batch_size=args.batch_size,
                     lr=args.lr, num_layers=args.num_layers, log_file=Path(args.adapter) / "train.log",
                     grad_accumulation=args.grad_accumulation)
        print(f"mlx_lm lora exit code {rc}; log: {Path(args.adapter) / 'train.log'}")
    elif args.cmd == "eval-lm":
        _eval_lm(args)
    elif args.cmd == "discover":
        from claude_chess.explainer import discover as DC
        from claude_chess.llm import ClaudeCLIStream
        llm = ClaudeCLIStream(model=args.model, effort="medium", timeout=900)
        res = DC.run(Path(args.encoder), llm, n_novel=args.n_novel, n_known=args.n_known,
                     log=lambda m: print(m, flush=True))
        print(json.dumps({v: {k: r[k] for k in ("fve", "alive", "known_share")} for v, r in res["views"].items()}))
    elif args.cmd == "explain":
        from claude_chess.explainer import pipeline as P
        enc = args.encoder if Path(args.encoder, "best.safetensors").exists() else None
        adapter = args.adapter if Path(args.adapter, "adapters.safetensors").exists() else None
        ex = P.Explainer(args.model, adapter, enc).explain(args.fen, engine_free=args.engine_free)
        if args.json:
            print(json.dumps(ex.to_dict(), indent=1))
        else:
            d = ex.to_dict()
            print(f"{d['fen']}\nEval: {d['eval']}  (analysis: {d['source']})\nBest {d['best']}  vs  {d['alt']}\n")
            print(ex.text.split("</think>")[-1].strip())
            print("\nVerified concept changes: " + "; ".join(
                f"{c['concept']} ({'+' if c['favours_best'] else '-'})" for c in d["salient_concepts"]))
    elif args.cmd == "data":
        from claude_chess.explainer import data as D
        D.build(args.kind, args.n, workers=args.workers)
    elif args.cmd == "stats":
        from claude_chess.explainer import data as D
        data = D.load(("eval",))
        scale = D.delta_scale(data)
        out = Path(D.DATA_DIR) / "stats.json"
        out.write_text(json.dumps({"delta_scale": scale, "n": int(len(data["fen"]))}, indent=1))
        print(f"wrote {out}")
    elif args.cmd == "teacher":
        from claude_chess.explainer import data as D
        from claude_chess.explainer import teacher as T
        from claude_chess.llm import ClaudeCLIStream
        data = D.load(("eval",))
        # test and val first: if the budget runs out it should cut training data, not the eval sets
        idx = T.select(data, {2: args.n_test, 1: args.n_val, 0: args.n_train})
        recs = [{k: (data[k][i].item() if hasattr(data[k][i], "item") else str(data[k][i]))
                 for k in ("fen", "best_line", "alt_line", "value", "value_alt", "split")} for i in idx]
        llm = ClaudeCLIStream(model=args.model, effort=args.effort, timeout=600)
        T.run(llm, recs, _scale(), Path(args.out), workers=args.workers, budget_usd=args.budget)
    elif args.cmd == "train-encoder":
        from claude_chess.explainer import data as D
        from claude_chess.explainer import encoder as E
        data = D.load(("eval", "puzzle"))
        cfg = E.Config(d=args.d, layers=args.layers, heads=args.heads, ff=4 * args.d,
                       probe_grad=args.probe_grad, themes=top_themes(data))
        cfg.n_themes = len(cfg.themes)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        res = E.train(data, _scale(), out, cfg, epochs=args.epochs, bs=args.bs, lr=args.lr,
                      max_minutes=args.max_minutes, log=lambda s: print(s, flush=True),
                      random_trunk=args.random_trunk, init_from=Path(args.resume) if args.resume else None,
                      start_step=args.start_step)
        print(json.dumps(res, indent=1))


def _eval_lm(args) -> None:
    """Held-out test split: student (LoRA) and base model vs the teacher's labels."""
    from claude_chess.explainer import evaluate as EV
    from claude_chess.explainer.lm import Student
    from claude_chess.llm import ClaudeCLI, ClaudeCLIStream

    recs = [json.loads(ln) for ln in Path(args.teacher).read_text().splitlines() if ln.strip()]
    test = [r for r in recs if r["split"] == 2 and r["verify"]["ok"]][: args.n]
    scale = _scale()
    out: dict = {"n_test": len(test)}
    log = lambda m: print(m, flush=True)  # noqa: E731
    student = Student(args.model, args.adapter)
    gen_s = EV.generate(student, test, log=log)
    del student
    out["student"] = EV.auto_metrics(test, gen_s, scale)
    gens = {"student": gen_s}
    if not args.skip_base:
        base = Student(args.model, None, max_tokens=250)  # the judge reads only its opening
        gen_b = EV.generate(base, test, log=log)
        del base
        out["base"] = EV.auto_metrics(test, gen_b, scale)
        gens["base"] = gen_b
    teacher_parsed = [r["label"] for r in test]
    judge = ClaudeCLIStream(model=args.judge_model, effort="medium", timeout=600)
    out["judge_student_vs_teacher"] = EV.pairwise(judge, test, [g["parsed"] for g in gen_s], teacher_parsed)
    if "base" in gens:
        # the base model ignores the format; judge its raw text as the "idea"
        base_as = [{"idea": g["raw"].split("</think>")[-1].strip()[:1200]} for g in gens["base"]]
        out["judge_student_vs_base"] = EV.pairwise(judge, test, [g["parsed"] for g in gen_s], base_as, seed=1)
    reader = ClaudeCLI(model=args.reader_model, thinking_tokens=0, timeout=300)
    out["transfer"] = EV.transfer(reader, test, {
        "no_hint": [None] * len(test),
        "teacher_idea": [EV.idea_hint(r["label"], r) for r in test],
        "student_idea": [EV.idea_hint(g["parsed"], r) for g, r in zip(gen_s, test)],
    })
    EV.save(out, Path(args.out))
    EV.save([{"fen": r["fen"], "best": r["best_san"][0], "alt": r["alt_san"][0], "teacher": r["label"],
              **{k: g[i]["parsed"] for k, g in gens.items()}} for i, r in enumerate(test)],
            Path(args.out).with_name("eval_lm_samples.json"))
    print(json.dumps({k: v for k, v in out.items()}, indent=1, default=str))


if __name__ == "__main__":
    main()
