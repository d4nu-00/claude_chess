---
title: Don't move the last kingside defender when an enemy rook already sits on the open file
tags: [king-safety, open-file, tactics]
status: active
kind: mistake
id: L004-don-t-move-the-last-kingside-defender-when-an-en
source: 20261002_110033_opus55-hybrid-ctx-vs-maia3-2400:0:15
learner: hybrid-ctx(t2,claude-opus-5-5)
created: 2026-10-02 11:04
---
## Summary
- Your king is castled, its rook-pawn is gone and an enemy rook is on that file: treat your kingside knight as a defender, not a target to cash in.
- Before a 'saving' capture with that knight, list every queen move onto the open file (Qh4/Qh2-type). Look for mate on h1/h2 first.
- If the knight is attacked, give it up (d3, then Qxf3) rather than move it away. Material is secondary to keeping the file covered.

## Evidence
- Position: `r2qkbnr/1pp2pp1/p1p5/4p3/4P1p1/5N2/PPPP1PP1/RNBQ1RK1 w kq - 0 8` — played **Nxe5**, lost 852 cp.
- Engine best: 8. d3 gxf3 9. Qxf3 Bd6 10. Nd2 Qh4 11. Qh3 Qxh3
- Refutation: 8...Qh4 9. f4 g3 10. Qh5 Qxh5 11. d4 Qh1#
- Diagnosis: Nxe5 removed the knight that covered h2 and h4. That let ...Qh4 bring the queen alongside the h8 rook on the open h-file, with an unstoppable mate on h1.
- Why general: Whenever an opponent has opened a file toward your castled king, moving away the minor piece guarding the entry squares invites a queen-and-rook mate, however attractive the capture looks.
- Gate: {"accepted": true, "reason": "accepted", "targets": 1, "per_target": [{"src": "20261002_110033_opus55-hybrid-ctx-vs-maia3-2400:0:15", "base_cpl": 725, "cand_cpl": 286}], "target_base_cpl": 725, "target_cand_cpl": 286, "target_repeats": 3, "controls": 4, "control_mean_delta": 0.0, "targets_proposed": 1}

## Source game
```json
{
 "db_game_id": "20261002_110033_opus55-hybrid-ctx-vs-maia3-2400:0",
 "run": "20261002_110033_opus55-hybrid-ctx-vs-maia3-2400",
 "judge": "stockfish depth 18 (lesson) / move_analysis in run",
 "kb_version_at_learning": 1,
 "engine": "Stockfish 17",
 "harness_commit": "79abd2f",
 "white": "hybrid-ctx(t2,claude-opus-5-5)",
 "black": "maia3-2400",
 "result": "0-1",
 "date": "2026.10.02",
 "termination": "checkmate",
 "player_config": {
  "model": "claude-opus-5-5",
  "white_spec": "hybrid-ctx",
  "black_spec": "maia3:2400",
  "ctx_version": 4,
  "threat_agent": false,
  "search": "compare",
  "learned_kb_version": null
 }
}
```
```pgn
[Event "claude_chess opus55-hybrid-ctx-vs-maia3-2400"]
[Site "claude_chess"]
[Date "2026.10.02"]
[Round "0"]
[White "hybrid-ctx(t2,claude-opus-5-5)"]
[Black "maia3-2400"]
[Result "0-1"]
[Termination "checkmate"]
[BookPlies "6"]
[PlyCount "20"]
[Opening "Ruy Lopez"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Bxc6 { own +130 $0.0482 } 4... dxc6 5. O-O { own +60 $0.0779 } 5... Bg4 6. h3 { own +40 $0.0581 } 6... h5 7. hxg4 { own +330 $0.0320 } 7... hxg4 8. Nxe5 { own +170 $0.0874 } 8... Qh4 9. f3 { own -320 $0.0434 } 9... g3 10. Qe1 { own -10149 $0.0802 } 10... Qh1# 0-1
```
