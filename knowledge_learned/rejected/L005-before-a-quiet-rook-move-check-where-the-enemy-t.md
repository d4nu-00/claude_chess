---
title: Before a quiet rook move, check where the enemy third-rank rook can swing sideways
tags: [weak-pawns, king-safety, tactics]
status: rejected
kind: mistake
id: L005-before-a-quiet-rook-move-check-where-the-enemy-t
source: 20261002_110519_opus55-learnloop-g2:0:44
learner: hybrid-ctx(t2,claude-opus-5-5)
created: 2026-10-02 11:11
---
## Summary
- When an enemy rook sits on its third rank, list every sideways move it has (Rh3, Rg3) that hits your loose or isolated pawns near your king.
- An undefended h-pawn or g-pawn in front of a thin king shelter is a target. Defend it or create a counter-threat before making slow doubling moves.
- Prefer an active unpin that gains a tempo or counterplay (attack a pawn, hit a loose piece) over keeping the outpost knight with a passive rook move.

## Evidence
- Position: `r3r3/pppb1k2/3p3p/3P1p2/2P1nN2/4R3/PB4PP/R5K1 b - - 5 22` — played **Re7**, lost 153 cp.
- Engine best: 22...Nf6 23. Rg3 Re4 24. Bxf6 Rxf4 25. Bb2 Rg8 26. Rxg8
- Refutation: 23. Rh3 Kg8 24. Rxh6 Rh7 25. Rxh7 Kxh7 26. Rd1 Nc5
- Diagnosis: I played Re7 to keep the pinned outpost knight and double rooks, but missed that White's Re3 could simply swing to h3 and win the undefended isolated h6-pawn.
- Why general: Rook lifts along the third rank onto loose pawns in front of the king come up in many middlegames, and slow consolidating moves often ignore them.
- Gate: {"accepted": false, "reason": "lesson not shown at any of its own targets", "targets": 0, "targets_proposed": 1}

## Source game
```json
{
 "db_game_id": "20261002_110519_opus55-learnloop-g2:0",
 "run": "20261002_110519_opus55-learnloop-g2",
 "judge": "stockfish depth 18 (lesson) / move_analysis in run",
 "kb_version_at_learning": 2,
 "engine": "Stockfish 17",
 "harness_commit": "79abd2f",
 "white": "maia3-2400",
 "black": "hybrid-ctx(t2,claude-opus-5-5)",
 "result": "1/2-1/2",
 "date": "2026.10.02",
 "termination": "repetition",
 "player_config": {
  "model": "claude-opus-5-5",
  "white_spec": "maia3:2400",
  "black_spec": "hybrid-ctx",
  "ctx_version": 4,
  "threat_agent": false,
  "search": "compare",
  "learned_kb_version": 2
 }
}
```
```pgn
[Event "claude_chess opus55-learnloop-g2"]
[Site "claude_chess"]
[Date "2026.10.02"]
[Round "0"]
[White "maia3-2400"]
[Black "hybrid-ctx(t2,claude-opus-5-5)"]
[Result "1/2-1/2"]
[Termination "repetition"]
[BookPlies "6"]
[PlyCount "56"]
[Opening "Italian"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 { own +60 $0.0480 } 5. d4 exd4 { own +120 $0.0587 } 6. cxd4 Bb4+ { own +220 $0.0614 } 7. Nc3 Nxe4 { own +190 $0.0618 } 8. O-O Bxc3 { own +145 $0.0673 } 9. d5 Ne5 { own +0 $0.0333 } 10. bxc3 Nxc4 { own +230 $0.0332 } 11. Qd4 Ncd6 { own +20 $0.0836 } 12. Qxg7 Qf6 { own +0 $0.0320 } 13. Qxf6 Nxf6 { own +900 $0.0278 } 14. Re1+ Nfe4 { own +60 $0.0717 } 15. Ng5 f5 { own -100 $0.0343 } 16. f3 h6 { own -190 $0.0731 } 17. Nh3 Kf7 { own -110 $0.0907 } 18. fxe4 Nxe4 { own +220 $0.0638 } 19. c4 d6 { own +90 $0.0663 } 20. Bb2 Re8 { own +70 $0.0684 } 21. Nf4 Bd7 { own +80 $0.0634 } 22. Re3 Re7 { own +50 $0.0711 } 23. Rh3 Nd2 { own +110 $0.0815 } 24. Rxh6 Rae8 { own +0 $0.0441 } 25. Rh7+ Kg8 { own +0 $0.0309 } 26. Rh8+ Kf7 27. Rh7+ Kg8 { own +0 $0.0301 } 28. Rh8+ Kf7 1/2-1/2
```
