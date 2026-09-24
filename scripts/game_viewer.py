"""Step-through HTML viewer for one game: board, eval graph and Claude's reasoning per move.

Usage: uv run python scripts/game_viewer.py RUN_DIR [--game 0] [--out file.html] [--title "..."]
Reads games.pgn, decisions.jsonl, traces.jsonl, move_analysis.jsonl from the run directory.
Arrows: blue = the move played; green = Stockfish's post-game best move (analysis only — it was
never shown to Claude). No LLM calls.
"""

from __future__ import annotations

import argparse
import html
import io
import json
from pathlib import Path

import chess
import chess.pgn
import chess.svg

from claude_chess.llm import extract_json


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _parse(text: str) -> dict:
    try:
        return extract_json(text)
    except Exception:
        return {}


def _e(x) -> str:
    return html.escape(str(x))


def build(rd: Path, gid: int, title: str | None) -> str:
    f = io.StringIO((rd / "games.pgn").read_text())
    while (g := chess.pgn.read_game(f)) is not None:
        if int(g.headers.get("Round", -1)) == gid:
            break
    assert g is not None, f"game {gid} not found"
    dec = {d["ply"]: d for d in _jsonl(rd / "decisions.jsonl") if d["game"] == gid}
    ana = {a["ply"]: a for a in _jsonl(rd / "move_analysis.jsonl") if int(a["game"]) == gid}
    trc: dict[int, list[dict]] = {}
    for t in _jsonl(rd / "traces.jsonl"):
        if t["game"] == gid:
            trc.setdefault(t["ply"], []).append(t)
    book = int(g.headers.get("BookPlies", 0))
    b = g.board()
    frames = [{"svg": chess.svg.board(b, size=400), "title": "Start position", "body": "", "ev": 0}]
    white_ev = []
    for i, mv in enumerate(g.mainline_moves(), 1):
        mover_white = b.turn == chess.WHITE
        num = f"{(i + 1) // 2}{'.' if mover_white else '...'}"
        san = b.san(mv)
        a = ana.get(i)
        arrows = [chess.svg.Arrow(mv.from_square, mv.to_square, color="#2563eb")]
        if a and a.get("best_move") and a["best_move"] != san:
            try:
                bm = b.parse_san(a["best_move"])
                arrows.append(chess.svg.Arrow(bm.from_square, bm.to_square, color="#16a34a"))
            except ValueError:
                pass
        b.push(mv)
        ev = None
        if a:
            ev = a["eval_after"] if a["color"] == "white" else -a["eval_after"]
        white_ev.append(ev)
        d = dec.get(i)
        who = g.headers["White"] if mover_white else g.headers["Black"]
        body: list[str] = []
        if a:
            body.append(f"<p class=mut>Stockfish after the move (White's view): <b>{ev:+d}</b> cp · this move lost "
                        f"{a['cpl']} cp · best was <span class=best>{_e(a['best_move'])}</span></p>")
        if i <= book:
            body.append("<p class=mut>Opening book move (not chosen by either player).</p>")
        elif d and "maia" not in d["player"]:
            ts = trc.get(i, [])
            prop = next((t for t in ts if t["role"] == "proposer"), None)
            pj = _parse(prop["response"]) if prop else {}
            if pj.get("thinking"):
                body.append(f"<div class=think><b>Claude (proposer):</b> {_e(pj['thinking'])}</div>")
            cands = (d.get("search") or {}).get("candidates") or {}
            if cands:
                rows = []
                for s, c in cands.items():
                    tags = []
                    if c.get("source") == "engine":
                        tags.append("added by tactical search")
                    if c.get("vetoed"):
                        tags.append("vetoed: loses material")
                    if c.get("threat_verified"):
                        tags.append(f"refuted by {c.get('threat_reply')}")
                    mat = c.get("tactical_cp")
                    pos = c.get("positional_cp")
                    rows.append(
                        f"<tr class='{'sel' if s == san else ''}'><td><b>{_e(s)}</b></td>"
                        f"<td>{_e(c.get('reason') or '')}</td><td>{'' if c.get('prior') is None else f'{c['prior']:.2f}'}</td>"
                        f"<td>{'' if mat is None else f'{mat:+d}'}</td><td>{'' if pos is None else f'{pos:+d}'}</td>"
                        f"<td>{_e(', '.join(tags))}</td></tr>")
                body.append("<table><tr><th>candidate</th><th>Claude's reason</th><th>prior</th>"
                            "<th>material (search)</th><th>positional (Claude)</th><th>verdict</th></tr>"
                            + "".join(rows) + "</table>")
            cmp_ = next((_parse(t["response"]) for t in ts if t["role"] == "compare"), {})
            if cmp_.get("thinking"):
                body.append(f"<div class=think><b>Claude (positional comparison):</b> {_e(cmp_['thinking'])}</div>")
            thr = next((_parse(t["response"]) for t in ts if t["role"] == "threat"), {})
            reps = [r for r in thr.get("replies") or [] if isinstance(r, dict)]
            if reps:
                items = "".join(f"<li>after <b>{_e(r.get('move'))}</b>: {_e(r.get('reply'))} — {_e(r.get('idea', ''))}</li>"
                                for r in reps)
                body.append(f"<div class=think><b>Claude (threat agent, opponent's advocate):</b><ul>{items}</ul></div>")
            body.append(f"<p class=mut>Decision: {_e(d.get('note') or '')} · {d.get('calls')} calls · "
                        f"${d.get('cost') or 0:.3f} · {d.get('seconds') or 0:.0f}s</p>")
        frames.append({"svg": chess.svg.board(b, arrows=arrows, size=400,
                                              lastmove=mv, check=b.king(b.turn) if b.is_check() else None),
                       "title": f"{num} {san} — {who}", "body": "".join(body), "ev": ev})
    # eval graph (White's view, clipped to ±800)
    n = len(white_ev)
    pts = []
    for k, v in enumerate(white_ev):
        v = 0 if v is None else max(-800, min(800, v))
        pts.append(f"{(k + 1) / max(1, n) * 600:.1f},{60 - v / 800 * 55:.1f}")
    graph = (f"<svg id=graph viewBox='0 0 600 120' preserveAspectRatio=none><line x1=0 x2=600 y1=60 y2=60 class=axis />"
             f"<polyline points='0,60 {' '.join(pts)}' class=ev /><line id=cur x1=0 x2=0 y1=0 y2=120 class=cur /></svg>")
    moves = " ".join(f"<a href='#' data-i='{k}'>{_e(fr['title'].split(' — ')[0])}</a>" for k, fr in enumerate(frames) if k)
    h = g.headers
    title = title or f"{h['White']} vs {h['Black']}"
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--acc:#2563eb;--sel:#dbeafe;--card:#f5f5f4;--good:#16a34a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--acc:#60a5fa;--sel:#1e3a5f;--card:#292524;--good:#4ade80}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:1100px}}
h1{{font-size:19px;margin:0 0 4px}} .mut{{color:var(--mut)}} .best{{color:var(--good);font-weight:600}}
.wrap{{display:flex;gap:20px;flex-wrap:wrap;margin-top:10px}} .board svg{{width:min(400px,100%);height:auto}}
.side{{flex:1;min-width:300px}} button{{font:inherit;padding:6px 14px;margin-right:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}} td,th{{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
tr.sel{{background:var(--sel)}} .think{{background:var(--card);border-radius:8px;padding:8px 10px;margin:8px 0;font-size:14px}}
.think ul{{margin:4px 0 0 18px;padding:0}} .moves a{{color:var(--acc);text-decoration:none;margin-right:6px;line-height:1.9}}
.moves a.cur{{font-weight:700;text-decoration:underline}} #graph{{width:100%;height:90px;background:var(--card);border-radius:6px;cursor:pointer}}
.axis{{stroke:var(--line)}} .ev{{fill:none;stroke:var(--acc);stroke-width:2}} .cur{{stroke:var(--fg);stroke-width:1;opacity:.5}}
</style></head><body>
<h1>{_e(title)}</h1>
<div class=mut>{_e(h.get('Opening', ''))} · result {_e(h.get('Result'))} ({_e(h.get('Termination', ''))}) · {_e(h.get('PlyCount'))} plies ·
← → keys to step · blue arrow = move played · green arrow = Stockfish's best (post-game analysis, never shown to Claude)</div>
<p class=mut style="margin:8px 0 2px">Evaluation (White's view, Stockfish, clipped ±8 pawns) — click to jump</p>{graph}
<div class=wrap><div class=board id=b></div><div class=side><h2 id=t style="font-size:17px;margin:0 0 6px"></h2>
<div><button id=p>◀ prev</button><button id=n>next ▶</button></div><div id=body></div></div></div>
<h2 style="font-size:16px">Moves</h2><div class=moves>{moves}</div>
<script>const F={json.dumps(frames)};let i=0;const N=F.length-1;
function show(k){{i=Math.max(0,Math.min(N,k));b.innerHTML=F[i].svg;t.textContent=F[i].title;body.innerHTML=F[i].body;
document.getElementById('cur').setAttribute('x1',i/N*600);document.getElementById('cur').setAttribute('x2',i/N*600);
document.querySelectorAll('.moves a').forEach(a=>a.classList.toggle('cur',+a.dataset.i===i));}}
p.onclick=()=>show(i-1);n.onclick=()=>show(i+1);
document.onkeydown=e=>{{if(e.key=='ArrowLeft')show(i-1);if(e.key=='ArrowRight')show(i+1);}};
document.getElementById('graph').onclick=e=>{{const r=e.currentTarget.getBoundingClientRect();show(Math.round((e.clientX-r.left)/r.width*N));}};
document.querySelectorAll('.moves a').forEach(a=>a.onclick=e=>{{e.preventDefault();show(+a.dataset.i);}});show(0);</script>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--game", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--title", default=None)
    args = ap.parse_args()
    rd = Path(args.run_dir)
    out = Path(args.out or rd / f"game{args.game}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(rd, args.game, args.title))
    print(out)


if __name__ == "__main__":
    main()
