---
title: Up a piece with the king uncastled: give material back to castle rather than knot up
tags: [king-safety, tactics, open-file, development]
status: rejected
kind: mistake
id: L006-up-a-piece-with-the-king-uncastled-give-material
source: 20261002_110519_opus55-learnloop-g2:0:22
learner: hybrid-ctx(t2,claude-opus-5-5)
created: 2026-10-02 11:11
---
## Summary
- When the enemy queen forks several loose units, list every target, including the pawn shielding your uncastled king and rook.
- If saving all the pieces leaves the king in the centre facing an open e-file, prefer returning material to castle and develop.
- Before choosing a 'keeps everything' move, check what it allows: queen captures near the king, Re1+ pins, and a stuck rook.

## Evidence
- Position: `r1bqk2r/pppp1ppp/8/3P4/2nQn3/2P2N2/P4PPP/R1B2RK1 b kq - 1 11` — played **Ncd6**, lost 103 cp.
- Engine best: 11...O-O 12. Qxc4 Nd6 13. Qb3 b6 14. Bg5 f6 15. Bf4
- Refutation: 12. Qxg7 Qf6 13. Qxf6 Nxf6 14. Re1+ Nfe4 15. Nd2 f5
- Diagnosis: I protected both knights with Ncd6 but allowed Qxg7. After that my king stayed stuck in the centre with the e-file open, Re1+ pinned a knight and my h-rook was dead, so the extra piece was worth nothing.
- Why general: In gambit-style positions you are often a piece up with the king uncastled. Hanging onto all the material instead of returning some to castle is a recurring way to lose the advantage.
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
