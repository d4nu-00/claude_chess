"""claude-chess CLI: match / analyze / context."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, Callable

import chess

SPEC_HELP = "naive | engine-ctx | engine-noctx | stockfish:ELO | stockfish-skill:N | random"


def make_player_factory(spec: str, args: Any, seed: int = 0) -> Callable[[], Any]:
    """Return a zero-arg factory building a fresh player for `spec` (one per game)."""
    spec = spec.strip()
    if spec == "random":
        from claude_chess.match.baselines import RandomPlayer
        counter = iter(range(10**9))
        return lambda: RandomPlayer(seed=seed * 100003 + next(counter))
    if spec.startswith("stockfish-skill:"):
        from claude_chess.match.baselines import StockfishPlayer
        n = int(spec.split(":", 1)[1])
        return lambda: StockfishPlayer(skill=n, time=args.sf_time)
    if spec.startswith("stockfish:") or spec == "stockfish":
        from claude_chess.match.baselines import StockfishPlayer
        elo = int(spec.split(":", 1)[1]) if ":" in spec else None
        return lambda: StockfishPlayer(elo=elo, time=args.sf_time)
    if spec in ("naive", "engine-ctx", "engine-noctx"):
        def factory():
            from claude_chess.engine.players import ClaudeEnginePlayer, NaiveClaudePlayer
            from claude_chess.llm import make_llm
            llm = make_llm(args.model, backend=args.backend)
            legal = not args.no_legal_moves
            if spec == "naive":
                p = NaiveClaudePlayer(llm, show_legal_moves=legal)
                p.name = f"naive({args.model})"
            else:
                ctx = spec == "engine-ctx"
                p = ClaudeEnginePlayer(llm, use_context=ctx, depth=args.depth,
                                       n_candidates=args.candidates, n_replies=args.replies,
                                       show_legal_moves=legal, illegal_policy=args.illegal_policy,
                                       max_retries=args.max_retries)
                p.name = f"{spec}(d{args.depth},{args.model})"
            return p
        return factory
    raise SystemExit(f"unknown player spec {spec!r}; expected {SPEC_HELP}")


def parse_position(text: str) -> chess.Board:
    """Accept a FEN, or a move list in SAN/UCI (move numbers allowed)."""
    text = text.strip()
    if text in ("", "startpos"):
        return chess.Board()
    try:
        return chess.Board(text)
    except ValueError:
        pass
    board = chess.Board()
    for tok in text.split():
        tok = re.sub(r"^\d+\.+", "", tok)
        if not tok or tok in ("1-0", "0-1", "1/2-1/2", "*"):
            continue
        try:
            board.push_san(tok)
        except ValueError:
            board.push_uci(tok)
    return board


def cmd_match(args: argparse.Namespace) -> None:
    from claude_chess.match.openings import OPENINGS
    from claude_chess.match.runner import play_match
    fa = make_player_factory(args.white, args, seed=1)
    fb = make_player_factory(args.black, args, seed=2)
    label = args.label or f"{args.white}_vs_{args.black}".replace(":", "")
    rd = play_match(fa, fb, args.games, args.max_plies,
                    openings=None if args.no_openings else OPENINGS, parallel=args.parallel,
                    label=label, runs_root=args.runs_root, analyze=not args.no_analysis,
                    analysis_depth=args.analysis_depth,
                    meta={"white_spec": args.white, "black_spec": args.black, "model": args.model,
                          "depth": args.depth, "candidates": args.candidates, "replies": args.replies,
                          "illegal_policy": args.illegal_policy, "argv": sys.argv[1:]})
    print(f"run dir: {rd}")


def cmd_analyze(args: argparse.Namespace) -> None:
    from claude_chess.match.analysis import analyze_run
    analyze_run(args.run_dir, depth=args.depth)


def cmd_context(args: argparse.Namespace) -> None:
    from claude_chess.context import build_context, render_context
    board = parse_position(args.position)
    print(board.fen())
    print(render_context(build_context(board)))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="claude-chess")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("match", help="play a match between two players")
    m.add_argument("--white", required=True, help=SPEC_HELP + " (player A; colours alternate)")
    m.add_argument("--black", required=True, help=SPEC_HELP + " (player B)")
    m.add_argument("--games", type=int, default=2)
    m.add_argument("--max-plies", type=int, default=200)
    m.add_argument("--model", default="sonnet")
    m.add_argument("--backend", default="auto")
    m.add_argument("--parallel", type=int, default=1)
    m.add_argument("--label", default=None)
    m.add_argument("--depth", type=int, default=1)
    m.add_argument("--candidates", type=int, default=4)
    m.add_argument("--replies", type=int, default=2)
    m.add_argument("--illegal-policy", default="random")
    m.add_argument("--max-retries", type=int, default=3)
    m.add_argument("--no-legal-moves", action="store_true", help="hide legal-move list from Claude")
    m.add_argument("--no-openings", action="store_true", help="start every game from the initial position")
    m.add_argument("--no-analysis", action="store_true")
    m.add_argument("--analysis-depth", type=int, default=12)
    m.add_argument("--sf-time", type=float, default=0.05, help="Stockfish player seconds/move")
    m.add_argument("--runs-root", default="runs")
    m.set_defaults(func=cmd_match)

    a = sub.add_parser("analyze", help="(re)analyse a run dir")
    a.add_argument("run_dir")
    a.add_argument("--depth", type=int, default=12)
    a.set_defaults(func=cmd_analyze)

    c = sub.add_parser("context", help="print render_context for a FEN or move list")
    c.add_argument("position")
    c.set_defaults(func=cmd_context)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
