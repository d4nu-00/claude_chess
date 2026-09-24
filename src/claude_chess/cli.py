"""claude-chess CLI: match / analyze / context."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, Callable

import chess

SPEC_HELP = ("naive | engine-ctx | engine-noctx | hybrid-ctx | hybrid-noctx | stockfish:ELO | stockfish-skill:N | "
             "maia:RATING (1100..1900, step 100) | random")


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
    if spec.startswith("maia:"):
        from claude_chess.match.maia import MaiaPlayer
        rating = int(spec.split(":", 1)[1])
        return lambda: MaiaPlayer(rating=rating)
    if spec in ("naive", "engine-ctx", "engine-noctx", "hybrid-ctx", "hybrid-noctx"):
        def factory():
            from claude_chess.engine.players import ClaudeEnginePlayer, NaiveClaudePlayer
            from claude_chess.llm import make_llm
            llm = make_llm(args.model, backend=args.backend, thinking_tokens=args.thinking)
            legal = not args.no_legal_moves
            if spec == "naive":
                p = NaiveClaudePlayer(llm, show_legal_moves=legal, board_read=args.board_read)
                p.name = f"naive({args.model})"
            elif spec.startswith("hybrid"):
                ctx = spec == "hybrid-ctx"
                p = ClaudeEnginePlayer(llm, use_context=ctx, n_candidates=args.candidates,
                                       show_legal_moves=legal, illegal_policy=args.illegal_policy,
                                       max_retries=args.max_retries, tactical=True,
                                       tac_depth=args.tac_depth, tac_margin=args.tac_margin,
                                       board_read=args.board_read, threat_agent=args.threat_agent,
                                       tablebase=not args.no_tablebase, search=args.search)
                ab = ",ab" if args.search == "alphabeta" else ""
                thr = ",threat" if args.threat_agent or args.search == "alphabeta" else ""
                p.name = f"{spec}(t{args.tac_depth}{thr}{ab},{args.model})"
            else:
                ctx = spec == "engine-ctx"
                p = ClaudeEnginePlayer(llm, use_context=ctx, depth=args.depth,
                                       n_candidates=args.candidates, n_replies=args.replies,
                                       show_legal_moves=legal, illegal_policy=args.illegal_policy,
                                       max_retries=args.max_retries, board_read=args.board_read)
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
                          "tac_depth": args.tac_depth, "tac_margin": args.tac_margin,
                          "thinking": args.thinking, "board_read": args.board_read,
                          "threat_agent": args.threat_agent, "tablebase": not args.no_tablebase,
                          "search": args.search,
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


def cmd_db(args: argparse.Namespace) -> None:
    from claude_chess.match import database as db

    if args.db_cmd == "ingest":
        if args.all:
            totals = db.ingest_all(args.runs_root, db_path=args.db_path, include_invalid=True)
            print(f"ingested {totals['runs']} run(s), {totals['games']} game(s), "
                 f"{totals['moves']} move(s)")
        else:
            if not args.run_dir:
                raise SystemExit("db ingest: give RUN_DIR ... or --all")
            n_games = n_moves = 0
            for rd in args.run_dir:
                r = db.ingest_run(rd, db_path=args.db_path)
                n_games += r["games"]
                n_moves += r["moves"]
                print(f"{rd}: {r['games']} game(s), {r['moves']} move(s)")
            print(f"total: {n_games} game(s), {n_moves} move(s)")
    elif args.db_cmd == "stats":
        stats = db.player_stats(db_path=args.db_path, include_invalid=args.include_invalid,
                                include_aborted=args.include_aborted)
        header = ("player", "G", "W", "D", "L", "score", "moves", "ACPL", "blunder%", "illegal%",
                 "calls", "cost$")
        print(" | ".join(header))
        for p in stats:
            print(" | ".join(str(x) for x in (
                p["player"], p["games"], p["W"], p["D"], p["L"], p["score"], p["moves"],
                p["acpl"], p["blunder_rate"], p["illegal_rate"], p["llm_calls"],
                round(p["cost_usd"], 4))))
    elif args.db_cmd == "export":
        n = db.export_pgn(args.pgn, db_path=args.db_path, player=args.player,
                          include_invalid=args.include_invalid)
        print(f"wrote {n} game(s) to {args.pgn}")
    elif args.db_cmd == "query":
        conn = db.connect(args.db_path)
        try:
            rows = conn.execute(args.sql).fetchall()
        finally:
            conn.close()
        if rows:
            cols = rows[0].keys()
            print(" | ".join(cols))
            for r in rows:
                print(" | ".join(str(r[c]) for c in cols))
        print(f"({len(rows)} row(s))")
    else:
        raise SystemExit("db: choose a subcommand (ingest/stats/export/query)")


def cmd_dataset(args: argparse.Namespace) -> None:
    from pathlib import Path

    from claude_chess.dataset import export
    root = Path(args.runs_root)
    dirs = [Path(d) for d in args.run_dir] or sorted(p for p in root.iterdir()
                                                     if p.is_dir() and not p.name.startswith("_"))
    stats = export(dirs, Path(args.out), with_context=args.with_context)
    import json
    print(json.dumps(stats, indent=2))


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
    m.add_argument("--tac-depth", type=int, default=2,
                   help="hybrid: full-width plies of material search after each candidate")
    m.add_argument("--tac-margin", type=int, default=100,
                   help="hybrid: veto candidates this many cp worse (material) than the best")
    m.add_argument("--illegal-policy", default="random")
    m.add_argument("--max-retries", type=int, default=3)
    m.add_argument("--thinking", type=int, default=None,
                   help="CLI backend: max extended-thinking tokens per call (0 = off; default = CLI default)")
    m.add_argument("--threat-agent", action="store_true",
                   help="hybrid: extra Claude call names refutations; Python verifies them")
    m.add_argument("--search", choices=("compare", "alphabeta"), default="compare",
                   help="hybrid: 1-ply batched positional compare, or depth-2 alpha-beta over "
                        "Claude positional leaves (implies the threat agent for replies)")
    m.add_argument("--no-tablebase", action="store_true", help="hybrid: don't play tablebase moves")
    m.add_argument("--board-read", action="store_true",
                   help="Claude also reports piece placement/threats; scored vs the real board")
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

    x = sub.add_parser("dataset", help="export Claude reasoning traces as a training dataset")
    x.add_argument("run_dir", nargs="*", help="run directories (default: every run under --runs-root)")
    x.add_argument("--runs-root", default="runs")
    x.add_argument("--out", default="datasets/reasoning")
    x.add_argument("--with-context", action="store_true",
                   help="include the rendered context block in SFT inputs")
    x.set_defaults(func=cmd_dataset)

    d = sub.add_parser("db", help="query the permanent games database (db/games.sqlite)")
    d.add_argument("--db-path", default="db/games.sqlite")
    dsub = d.add_subparsers(dest="db_cmd", required=True)

    di = dsub.add_parser("ingest", help="(re)ingest run dir(s) into the database")
    di.add_argument("run_dir", nargs="*", help="run directories to ingest")
    di.add_argument("--all", action="store_true", help="ingest every run under --runs-root, "
                    "including runs/_invalid (stored with valid=0)")
    di.add_argument("--runs-root", default="runs")

    ds = dsub.add_parser("stats", help="per-player W/D/L/score, ACPL, blunder/illegal rate, cost")
    ds.add_argument("--include-invalid", action="store_true")
    ds.add_argument("--include-aborted", action="store_true")

    de = dsub.add_parser("export", help="export stored games to a single PGN file")
    de.add_argument("--pgn", required=True)
    de.add_argument("--player", default=None, help="only games this player name played in")
    de.add_argument("--include-invalid", action="store_true")

    dq = dsub.add_parser("query", help="run a read SQL query against the database")
    dq.add_argument("sql")

    d.set_defaults(func=cmd_db)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
