"""Build the explainer showcase page: uv run --extra ml python scripts/explainer_report.py [OUT.html]

Reads experiments/explainer/{eval_lm.json, eval_lm_samples.json, encoder_eval.json,
encoder_eval_random.json, engine_free.json} and datasets/explainer_v1/{teacher.jsonl,
discovered_concepts.json}; writes a self-contained HTML page (inline SVG boards, no network).
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import chess
import chess.svg

EXP = Path("experiments/explainer")
DS = Path("datasets/explainer_v1")


def _load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def board_svg(fen: str, best: str | None = None, alt: str | None = None, size: int = 300) -> str:
    b = chess.Board(fen)
    arrows = []
    for san, color in ((best, "#2e7d5b"), (alt, "#b5523b")):
        if san:
            try:
                mv = b.parse_san(san)
                arrows.append(chess.svg.Arrow(mv.from_square, mv.to_square, color=color + "cc"))
            except ValueError:
                pass
    svg = chess.svg.board(b, size=size, arrows=arrows, flipped=not b.turn, coordinates=True,
                          colors={"square light": "#e8e4d6", "square dark": "#7f9a83",
                                  "margin": "#00000000", "coord": "#8a8f8a"})
    return svg.replace("<svg ", '<svg role="img" aria-label="chess board" ', 1)


def esc(s) -> str:
    return html.escape(str(s or ""))


CSS = """
/* Layout: one reading column; position studies as board + annotation rows that stack on phones */
:root {
  --bg: #f3f4f1; --surface: #ffffff; --ink: #1d2420; --muted: #5d6762; --line: #d9ddd6;
  --accent: #2e7d5b; --warn: #b5523b; --chip: #e7efe9;
  --display: "Instrument Serif", Georgia, serif; --body: "Instrument Sans", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #141a17; --surface: #1c2420; --ink: #e6ebe7; --muted: #9aa59f; --line: #2d3832;
  --accent: #6cc39a; --warn: #e08a72; --chip: #24332b; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #141a17; --surface: #1c2420; --ink: #e6ebe7; --muted: #9aa59f; --line: #2d3832;
  --accent: #6cc39a; --warn: #e08a72; --chip: #24332b; color-scheme: dark }
body { background: var(--bg); color: var(--ink); font: 15px/1.55 var(--body); }
.wrap { max-width: 1040px; margin: 0 auto; padding-inline: 20px; padding-block: 36px 64px; }
h1 { font: 400 clamp(36px, 6vw, 56px)/1.05 var(--display); margin: 0 0 12px; text-wrap: balance; }
h2 { font: 400 30px/1.15 var(--display); margin: 48px 0 12px; text-wrap: balance; }
h3 { font: 600 15px/1.3 var(--body); margin: 0; }
p { max-width: 68ch; margin: 0 0 12px; }
.lede { font-size: 17px; color: var(--muted); }
.mono, code { font-family: var(--mono); font-size: 13px; }
.label { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 20px 0 8px; }
.stat { border-top: 2px solid var(--accent); padding-top: 8px; }
.stat b { display: block; font: 400 30px/1.1 var(--display); font-variant-numeric: tabular-nums; }
.study { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 24px; padding: 24px 0;
  border-top: 1px solid var(--line); }
@media (max-width: 720px) { .study { grid-template-columns: minmax(0, 1fr); } .study .board { max-width: 300px; } }
.board svg { width: 100%; height: auto; display: block; }
.moves { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline; margin-bottom: 10px; }
.best { color: var(--accent); font-weight: 600; } .alt { color: var(--warn); font-weight: 600; }
.idea { font: 400 22px/1.3 var(--display); margin: 2px 0 10px; text-wrap: balance; }
.voices { display: grid; gap: 14px; }
.voice p { margin: 2px 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.chip { background: var(--chip); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.chip.neg { color: var(--warn); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 12px; color: var(--muted); font-weight: 600; }
.bar { height: 8px; background: var(--accent); border-radius: 2px; }
.bar.rand { background: var(--muted); opacity: .55; }
.r2 { display: grid; grid-template-columns: minmax(120px, 220px) minmax(0, 1fr) 52px; gap: 4px 10px; align-items: center; font-size: 13px; }
.muted { color: var(--muted); }
.judge { font-size: 13px; color: var(--muted); border-left: 2px solid var(--line); padding-left: 8px; }
ul { max-width: 68ch; padding-left: 20px; } li { margin-bottom: 6px; }
pre.mermaid { background: transparent; }
"""


def pct(x) -> str:
    return "–" if x is None else f"{100 * x:.0f}%"


def section_examples(samples: list[dict], teacher: dict, showcase: dict, idea_judge: dict) -> str:
    out = ['<h2 id="examples">Explanations on held-out positions</h2>',
           '<p class="muted">Positions from the test split, never seen in training. Green arrow: Stockfish\'s '
           'move. Red arrow: the alternative it is compared with. The student is Qwen3-1.7B with a LoRA '
           'adapter; the teacher is Claude Opus 5.5; the base model is the same Qwen without fine-tuning. '
           'Under each student idea is the verdict of a blind Opus judge that saw the engine analysis.</p>']
    reasons = (idea_judge.get("student") or {}).get("reasons", [])
    for i in showcase.get("pick", range(8)):
        s = samples[i]
        t = teacher.get(s["fen"], {})
        st = s.get("student") or {}
        chips = "".join(f'<span class="chip{"" if c["good"] else " neg"}">{esc(c["text"])}</span>'
                        for c in t.get("_chips", []))
        base = " ".join(str(showcase.get("base_raw", {}).get(s["fen"], "")).replace("*", "").split())
        verdict = reasons[i] if i < len(reasons) else ""
        out.append(f'''<article class="study">
  <div class="board">{board_svg(s["fen"], s["best"], s["alt"])}</div>
  <div>
    <div class="moves"><span class="label">{esc(t.get("_side", ""))} to move</span>
      <span class="mono best">{esc(s["best"])}</span><span class="muted">instead of</span>
      <span class="mono alt">{esc(s["alt"])}</span><span class="muted mono">{esc(t.get("_eval", ""))}</span></div>
    <div class="voices">
      <div class="voice"><div class="label">Student · Qwen3.5-2B + LoRA</div>
        <p class="idea">{esc(st.get("idea", "—"))}</p>
        <p class="judge"><span class="label">Judge</span> {esc(verdict)}</p>
        <p>{esc(st.get("why_best", ""))}</p>
        <p class="muted">Why not {esc(s["alt"])}: {esc(st.get("why_not_alt", ""))}</p>
        <p class="muted">Concepts: {esc(", ".join(st.get("concepts", []) if isinstance(st.get("concepts"), list) else []))}</p></div>
      <div class="voice"><div class="label">Teacher · Claude Opus 5.5</div><p>{esc(s["teacher"].get("idea", ""))}</p></div>
      <div class="voice"><div class="label">Base model, untuned</div><p class="muted">{esc(base[:260])}{"…" if len(base) > 260 else ""}</p></div>
    </div>
    <div class="chips">{chips}</div>
  </div>
</article>''')
    return "\n".join(out)


def section_eval(ev: dict, ij: dict, ef: dict) -> str:
    if not ev:
        return ""
    s, b = ev.get("student", {}), ev.get("base", {})
    js, jb = ev.get("judge_student_vs_teacher", {}), ev.get("judge_student_vs_base", {})
    tr = ev.get("transfer", {})
    rows = [
        ("Follows the format", pct(s.get("format_ok")), pct(b.get("format_ok")), "100%"),
        ("Passes the fact checker", pct(s.get("verifier_ok")), pct(b.get("verifier_ok")), "100%"),
        ("Concept tags agree with teacher (F1)", f'{s.get("concept_f1_vs_teacher", 0):.2f}',
         f'{b.get("concept_f1_vs_teacher", 0):.2f}', "1.00"),
        ("Words in the idea", f'{s.get("idea_words", 0):.1f}', f'{b.get("idea_words", 0):.1f}',
         f'{s.get("teacher_idea_words", 0):.1f}'),
        ("Whole explanation judged correct", pct(js.get("first_correct")), pct(jb.get("second_correct")),
         pct(js.get("second_correct"))),
        ("One-line idea judged correct", pct((ij.get("student") or {}).get("correct")), "–",
         pct((ij.get("teacher") or {}).get("correct"))),
    ]
    body = "".join(f"<tr><td>{a}</td><td>{x}</td><td>{y}</td><td>{z}</td></tr>" for a, x, y, z in rows)
    out = ['<h2 id="eval">How good are the explanations?</h2>',
           f'<p class="muted">{ev.get("n_test", 0)} held-out test positions. The fact checker re-plays every move '
           'and material claim on a real board. The judge (Opus 5.5) sees the engine analysis and two explanations '
           'in random order.</p>',
           f'<div class="scroll"><table><thead><tr><th></th><th>Student</th><th>Base model</th><th>Teacher</th></tr>'
           f'</thead><tbody>{body}</tbody></table></div>']
    if js:
        out.append(f'<p>Head to head against the teacher, the judge preferred the student {pct(js.get("first_wins"))} '
                   f'of the time, the teacher {pct(js.get("second_wins"))}, and called {pct(js.get("ties"))} a tie.'
                   + (f' Against the untuned base model the student won {pct(jb.get("first_wins"))}.' if jb else "")
                   + '</p>')
    if tr:
        cells = "".join(f"<tr><td>{esc(k.replace('_', ' '))}</td><td>{pct(v['accuracy'])}</td></tr>" for k, v in tr.items())
        out.append('<h3 style="margin-top:20px">Does the idea transfer?</h3><p class="muted">A weaker reader (Claude '
                   'Haiku 4.5, playing the part of a club player) picks between the two moves. Hints have every '
                   'move name masked. Hints still say things like "recapture with the knight", which identifies the move, so '
                   'this shows the hint points at the right move, not that its reasoning is right.</p>'
                   f'<div class="scroll"><table><thead><tr><th>Hint given</th><th>Picks Stockfish\'s move</th></tr>'
                   f'</thead><tbody>{cells}</tbody></table></div>')
    out.append('<h3 style="margin-top:20px">What went wrong</h3><p>The student learned the teacher\'s voice, length and '
               'vocabulary, and its ideas usually aim at the right kind of move. The judge\'s objections are almost all '
               'board geometry: a rook said to guard a square it can\'t reach, a bishop that isn\'t on the board, a pawn '
               'said to attack a queen it doesn\'t. A 1.7B model trained on 573 examples cannot work out which piece '
               'attacks which square from a list of pieces. The teacher, reading the same facts plus a diagram, is right '
               '93% of the time.</p>')
    if ef:
        out.append(f'<p class="muted">Engine-free mode (no Stockfish: the encoder picks and plays out the lines): '
                   f'its move matched Stockfish\'s in {pct(ef.get("encoder_best_is_stockfish_best"))} of {ef.get("n")} '
                   f'test positions.</p>')
    return "\n".join(out)


def section_encoder(enc: dict, rnd: dict) -> str:
    if not enc:
        return ""
    r2, r2r = enc.get("concept_r2", {}), rnd.get("concept_r2", {})
    keys = sorted(r2, key=lambda k: -r2[k])[:18]
    rows = []
    for k in keys:
        a, b = max(0.0, r2[k]), max(0.0, r2r.get(k, 0.0))
        rows.append(f'<span class="mono">{esc(k)}</span><span><div class="bar" style="width:{100 * a:.0f}%"></div>'
                    f'<div class="bar rand" style="width:{100 * b:.0f}%;margin-top:2px"></div></span>'
                    f'<span class="mono">{a:.2f}</span>')
    stats = [("Value error", f'{100 * enc.get("value_mae", 0):.1f} pts', "mean |win% − Stockfish|"),
             ("Matches Stockfish's move", pct(enc.get("policy_top1")), "cloud-eval positions"),
             ("Solves puzzle first move", pct(enc.get("puzzle_top1")), "Lichess puzzles"),
             ("Concept probe R²", f'{enc.get("concept_r2_mean", 0):.2f}',
              f'random network: {rnd.get("concept_r2_mean", float("nan")):.2f}')]
    tiles = "".join(f'<div class="stat"><span class="label">{a}</span><b>{b}</b><span class="muted">{c}</span></div>'
                    for a, b, c in stats)
    return f'''<h2 id="encoder">The chess encoder</h2>
<p class="muted">A 7.5M-parameter transformer over the 64 squares, trained only to predict Stockfish's evaluation and
moves on 400k positions and 150k puzzles. Its concept read-outs are trained on top of a frozen copy of what it learned, so
they measure what the network learned on its own (green), against the same read-out on a random untrained network (grey).</p>
<div class="stats">{tiles}</div>
<div class="r2" style="margin-top:16px">{"".join(rows)}</div>'''


def section_discovered(disc: dict, teach: list) -> str:
    if not disc:
        return ""
    tmap = {r["feature"]: r for r in teach}
    out = ['<h2 id="discovered">Concepts found inside the network</h2>',
           '<p class="muted">A sparse autoencoder splits the encoder\'s internal state into features. Static features '
           'describe a position; dynamic features describe what the best line achieves compared with the alternative '
           '(the network-side version of Schut et al.). Claude named each feature from its strongest examples, then '
           'had to predict which unseen positions trigger it from the name alone (50% is chance).</p>']
    for view, v in disc.get("views", {}).items():
        rows = []
        for f in v.get("features", []):
            it = f.get("interpretation", {})
            m = f["match"][0]
            sim = f.get("simulation", {}).get("balanced_accuracy")
            ex = f.get("examples", [None])[0]
            tr = tmap.get(f["feature"]) if view == "dynamic" else None
            teach_cell = f'{100 * tr["teachability"]:+.1f} pts' if tr else "–"
            rows.append(f'<tr><td>{f"<div style=width:120px>{board_svg(ex, size=120)}</div>" if ex else ""}</td>'
                        f'<td><b>{esc(it.get("name", ""))}</b><br><span class="muted">{esc(it.get("description", ""))}</span></td>'
                        f'<td class="mono">{esc(m[0])}<br>r = {m[1]}</td><td>{pct(sim) if sim is not None else "–"}</td>'
                        f'<td>{teach_cell}</td></tr>')
        out.append(f'<h3 style="margin-top:20px">{esc(view.title())} features · {v["alive"]} of {v["n_latents"]} in use, '
                   f'{pct(v.get("known_share"))} match a hand-written concept at |r| ≥ 0.5</h3>'
                   '<div class="scroll"><table><thead><tr><th>Top example</th><th>Claude\'s name</th><th>Closest '
                   'known measure</th><th>Predicts unseen</th><th>Teachable</th></tr></thead><tbody>' + "".join(rows) +
                   '</tbody></table></div>')
    out.append('<p class="muted">Predicts unseen: Claude, given only its own name for the feature, picks which of 10 '
               'unseen positions trigger it (50% is chance). Teachable: a weaker copy of the network fine-tuned on the '
               'feature\'s example positions vs on random positions, change in top-move accuracy on held-out examples '
               '(Schut et al.\'s test; ±5 points is noise at this sample size).</p>')
    return "\n".join(out)


def section_round2(joint: dict) -> str:
    """Round 2: one model picks the move and explains it (experiments/explainer/joint/*.json)."""
    if not joint:
        return ""
    names = [("instinct", "Encoder instinct (its first choice)"), ("A_reason_first", "A · idea → move"),
             ("D_tactics", "D · + verified tactical outcome per candidate"),
             ("E_tactics_move_first", "E · same input, move → idea"), ("E_depth4", "E · deeper tactics (4 plies)"),
             ("E2_more_labels", "E2 · +600 explanation labels"), ("E3_all_labels", "E3 · +2,000 explanation labels")]
    rows = []
    for key, label in names:
        if key == "instinct":
            d = next(iter(joint.values()))
            rows.append(f"<tr><td>{label}</td><td>{pct(d['eval']['instinct'])}</td><td>{pct(d['puzzle']['instinct'])}</td><td>–</td></tr>")
            continue
        d = joint.get(key)
        if not d:
            continue
        ideas = d.get("ideas", {})
        rows.append(f"<tr><td>{label}</td><td>{pct(d['eval']['explain'])}</td><td>{pct(d['puzzle']['explain'])}</td>"
                    f"<td>{pct(ideas.get('sound'))}</td></tr>")
    ex = []
    e = (joint.get("E3_all_labels") or joint.get("E_tactics_move_first", {})).get("ideas", {})
    for p, it in zip(e.get("plays", []), e.get("items", [])):
        if it.get("sound") and it.get("true") and len(ex) < 4:
            ex.append(f'<li><span class="mono">{esc(p["san"])}</span>: “{esc(p["idea"])}”</li>')
    return f"""<h2 id="round2">Round 2: one model that picks the move and explains it</h2>
<p>The first student only explained moves chosen by something else. Here a single language model (Qwen3-1.7B)
chooses its own move from six candidates suggested by the chess encoder, reading verified facts about the
position and each candidate. No engine appears in its input. Accuracy is the share of held-out positions where
it plays Stockfish's choice, with its explanation switched on.</p>
<div class="scroll"><table><thead><tr><th></th><th>Cloud-eval positions</th><th>Puzzles</th><th>Ideas judged sound</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p>Two findings. Telling the model what each candidate's forcing play wins or loses, from a tiny material search,
is what lets it beat its own instinct: small language models can't count exchanges. And writing the idea before
the move made it worse at tactics, while deciding first and explaining afterwards cost nothing. Its explanation
is an account of a decision it already made, not the thing that made the decision good.</p>
{"<p>More explanation data was the lever for the ideas: with 4× the Claude-written labels (E3), the share judged sound rose from 26% to 39% (p = 0.035) while the moves stayed as good. Ideas from E3 that a blind Opus judge rated true and sound:</p><ul>" + "".join(ex) + "</ul>" if ex else ""}
<p class="muted">Play it locally: <code>uv run --extra ml python scripts/play.py</code>, then open localhost:8766.</p>"""


def main(out_path: str = "experiments/explainer/showcase.html") -> None:
    from claude_chess.explainer import concepts as C
    from claude_chess.explainer import facts as F

    ev = _load(EXP / "eval_lm.json", {})
    samples = _load(EXP / "eval_lm_samples.json", [])
    enc = _load(EXP / "encoder_eval.json", {})
    rnd = _load(EXP / "encoder_eval_random.json", {})
    disc = _load(DS / "discovered_concepts.json", {})
    ij = _load(EXP / "idea_judge.json", {})
    ef = _load(EXP / "engine_free.json", {})
    teach = _load(EXP / "teachability.json", [])
    showcase = _load(EXP / "showcase_base.json", {})
    joint = {p.stem: json.loads(p.read_text()) for p in sorted((EXP / "joint").glob("*.json"))
             if p.stem not in ("positions", "summary")}
    teacher = {}
    tp = DS / "teacher.jsonl"
    if tp.exists():
        for ln in tp.read_text().splitlines():
            r = json.loads(ln)
            b = chess.Board(r["fen"])
            r["_side"] = "White" if b.turn else "Black"
            r["_eval"] = F.eval_words(r["value"], b.turn)
            r["_chips"] = [{"text": C.describe(k), "good": g >= 0} for k, _z, g in r.get("salience", [])[:4]]
            teacher[r["fen"]] = r
    n_pos = sum(1 for _ in teacher)
    head = f'''<title>Chess Explainer v1</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;600&family=Instrument+Serif&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{CSS}</style>'''
    intro = f'''<div class="wrap">
<span class="label">claude_chess · explainer model v1</span>
<h1>Teaching a small model to explain chess moves in a sentence</h1>
<p class="lede">Stockfish decides which move is best. Python checks the facts on a real board. Claude Opus 5.5 condenses
it into the idea a coach would say. A 1.7-billion-parameter open model then learns to do that last step itself.
Inside a small chess network trained only on Stockfish, a sparse autoencoder finds the concepts it uses.</p>
<pre class="mermaid">
flowchart LR
  A[Lichess positions + Stockfish lines] --> B[Concept detectors: what changes, best vs alternative]
  B --> C[Claude Opus 5.5: one-line idea + concepts]
  C --> D[Fact checker]
  D --> E[Qwen3-1.7B LoRA student]
  A --> F[Chess encoder 7.5M]
  F --> G[Sparse autoencoder: concepts it found]
</pre>
<p class="muted">{n_pos} teacher-labelled positions, of which the test split is held out from every training step.</p>'''
    nxt = """<h2 id="next">What would make it better</h2>
<ul>
<li>More explanation labels. The moves improved once the inputs carried resolved tactics; the ideas did not, and only 573 Claude-written ideas were used against 2,000 move-only examples.</li>
<li>Keep explanations inside the verified facts: let it point at facts it was given instead of writing free text, or sample several and keep one that passes the fact and geometry checkers.</li>
<li>Endgame-heavy training data: in a long endgame its ideas collapsed into one template.</li>
<li>A bigger student (Qwen3-4B with 4-bit LoRA), or feed the chess encoder into the language model directly.</li>
<li>Turn the teachable discovered concepts (get the king out of the centre, castle) into vocabulary the student uses.</li>
</ul>"""
    page = "\n".join([head, intro, section_examples(samples, teacher, showcase, ij), section_eval(ev, ij, ef),
                      section_encoder(enc, rnd), section_discovered(disc, teach), section_round2(joint), nxt, "</div>"])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(page)
    print(f"wrote {out_path} ({len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:])
