---
title: Up a piece against checks: block with the minor piece, not the queen
tags: [king-safety, exchange, tactics]
status: rejected
kind: drift
id: L012-up-a-piece-against-checks-block-with-the-minor-p
source: 20261002_112909_opus55-learnloop-g4:0:120-142
learner: hybrid-ctx(t2,claude-opus-5-5)
created: 2026-10-02 11:59
---
## Summary
- When a piece up and facing queen checks, interpose the knight or rook; keep your queen free to counterattack and guard pawns.
- Don't force a queen trade at any price; a queen block that drops pawns or tangles your pieces gives back your edge.
- Trust the material count: Q+R+N vs Q+R is winning, so play solidly rather than desperately simplifying.

## Evidence
- Slow drift: plies 120–142, 12 moves, 410 cp lost in total (max 98 in one move).
- Moves: Rxc4(-0), Qh4(-66), Qd4(-0), Kg7(-0), Rc2(-7), Nf7(-0), Qc4+(-22), Ne5(-30), Qc7(-98), Qc4(-29), Qf7(-77), Qf5(-81)
- Followed by Kf8 (-581) at ply 150.
- How it got there: Black was a clean piece up (Q+R+N vs Q+R) with the engine at +4 to +5.5 throughout, but I rated my position at only about +1 and played as if I were struggling. Against White's queen checks I kept interposing my queen (Qh4, Qc7, Qf7, Qf5) to force a queen trade. The engine wanted the knight or rook to block (Rh4, Nf7) so the queen stayed free. Blocking with the queen at move 68 let White take the a6 pawn, and each later queen block left my pieces more tangled and my king more exposed. That set up the Kf8 collapse.
- Turning point: ply 136
- Misconception: I treated an immediate queen trade as the main goal, so I blocked checks with my queen, when blocking with the minor piece kept my queen active and my material safe.
- Why general: Converting extra material against an exposed king with queens on comes down to blocking checks with minor pieces and keeping the queen active, whatever the structure.
- Gate: {"accepted": false, "reason": "lesson not shown at any of its own targets", "targets": 0, "targets_proposed": 3}

## Source game
```json
{
 "db_game_id": "20261002_112909_opus55-learnloop-g4:0",
 "run": "20261002_112909_opus55-learnloop-g4",
 "judge": "stockfish depth 18 (lesson) / move_analysis in run",
 "kb_version_at_learning": 3,
 "engine": "Stockfish 17",
 "harness_commit": "79abd2f",
 "white": "maia3-2400",
 "black": "hybrid-ctx(t2,claude-opus-5-5)",
 "result": "0-1",
 "date": "2026.10.02",
 "termination": "adjudication (ply cap 200, SF eval -512cp)",
 "player_config": {
  "model": "claude-opus-5-5",
  "white_spec": "maia3:2400",
  "black_spec": "hybrid-ctx",
  "ctx_version": 4,
  "threat_agent": false,
  "search": "compare",
  "learned_kb_version": 3
 }
}
```
```pgn
[Event "claude_chess opus55-learnloop-g4"]
[Site "claude_chess"]
[Date "2026.10.02"]
[Round "0"]
[White "maia3-2400"]
[Black "hybrid-ctx(t2,claude-opus-5-5)"]
[Result "0-1"]
[Termination "adjudication (ply cap 200, SF eval -512cp)"]
[BookPlies "6"]
[PlyCount "200"]
[Opening "French"]

1. e4 e6 2. d4 d5 3. Nc3 Nf6 4. e5 Nfd7 { own +120 $0.0591 } 5. f4 c5 { own +90 $0.0562 } 6. Nf3 Nc6 { own +60 $0.0537 } 7. Be3 cxd4 { own +60 $0.0601 } 8. Nxd4 Bc5 { own +60 $0.0602 } 9. Qd2 O-O { own +60 $0.0636 } 10. O-O-O a6 { own +40 $0.0656 } 11. h4 Nxd4 { own +70 $0.0753 } 12. Bxd4 b5 { own +60 $0.0626 } 13. h5 b4 { own +60 $0.0671 } 14. Ne2 Qa5 { own +60 $0.0712 } 15. Kb1 Rb8 { own +40 $0.0730 } 16. h6 g6 { own +60 $0.0743 } 17. g4 Bb7 { own +45 $0.0754 } 18. f5 exf5 { own +140 $0.0834 } 19. gxf5 Bxd4 { own +190 $0.0698 } 20. Qxd4 Qc5 { own +70 $0.0762 } 21. Qf4 d4 { own +50 $0.0822 } 22. Rg1 Nxe5 { own +70 $0.0897 } 23. Nxd4 Qd5 { own +40 $0.0707 } 24. Bg2 Qc5 { own +40 $0.0717 } 25. Bxb7 Rxb7 { own +330 $0.0359 } 26. fxg6 fxg6 { own +210 $0.0882 } 27. Qe4 Re7 { own +50 $0.0693 } 28. Nb3 Qc4 { own +70 $0.0810 } 29. Rd4 Rf1+ { own -100 $0.0462 } 30. Rxf1 Qxf1+ { own +500 $0.0357 } 31. Nc1 Qf8 { own +110 $0.0731 } 32. Qd5+ Nf7 { own +60 $0.0753 } 33. Rxb4 Qxh6 { own +110 $0.0707 } 34. Rb8+ Kg7 { own +0 $0.0316 } 35. Qd4+ Re5 { own +90 $0.0619 } 36. Rb7 Qe3 { own +120 $0.0742 } 37. Qd7 Qf4 { own +60 $0.0736 } 38. a3 Re1 { own +180 $0.0385 } 39. Ka2 Rxc1 { own +320 $0.0397 } 40. c3 Qc4+ { own +60 $0.0782 } 41. Rb3 Rc2 { own +110 $0.0963 } 42. Qd1 Qe4 { own +60 $0.0827 } 43. Rb4 Qe2 { own +110 $0.0750 } 44. Qd4+ Qe5 { own +120 $0.0697 } 45. Qd3 Qe6+ { own +110 $0.0729 } 46. c4 Qf5 { own +90 $0.0723 } 47. Qd4+ Qe5 { own +110 $0.0764 } 48. Qd3 Qe2 { own +110 $0.0702 } 49. Qd4+ Ne5 { own +90 $0.1040 } 50. Rb7+ Kf6 { own +0 $0.0421 } 51. Qf4+ Ke6 52. Rb6+ Ke7 { own +25 $0.0771 } 53. Qf6+ Kd7 { own +0 $0.0326 } 54. Qd6+ Ke8 { own +0 $0.0300 } 55. Rb8+ Kf7 56. Rf8+ Kg7 57. Qf6+ Kh6 58. Qh4+ Qh5 { own +0 $0.0339 } 59. Qf4+ Qg5 { own +100 $0.0420 } 60. Qe4 Rxc4 { own +220 $0.0759 } 61. Qh1+ Qh4 { own +90 $0.0797 } 62. Qd5 Qd4 { own +90 $0.0733 } 63. Qh1+ Kg7 { own +120 $0.0556 } 64. Rb8 Rc2 { own +120 $0.0845 } 65. Rb7+ Nf7 { own +90 $0.0802 } 66. Qf3 Qc4+ { own +140 $0.0770 } 67. Rb3 Ne5 { own +90 $0.0823 } 68. Qb7+ Qc7 { own -10 $0.0885 } 69. Qxa6 Qc4 { own +60 $0.1084 } 70. Qb7+ Qf7 { own +60 $0.0767 } 71. Qe4 Qf5 { own +90 $0.0837 } 72. Rb7+ Nf7 { own +40 $0.0847 } 73. Qd4+ Qf6 { own +110 $0.0746 } 74. Qd3 Qc6 { own +70 $0.0862 } 75. Qd4+ Kf8 { own -100 $0.0506 } 76. Rb8+ Ke7 { own +50 $0.0927 } 77. Qb4+ Qc5 { own +80 $0.0759 } 78. Rb7+ Kf8 { own +80 $0.0867 } 79. Rb8+ Kg7 { own +0 $0.0366 } 80. Qb3 Qc4 { own +110 $0.0727 } 81. Rb7 Qxb3+ { own +130 $0.0833 } 82. Kxb3 Rf2 { own +60 $0.0658 } 83. a4 Kf6 { own +70 $0.0617 } 84. a5 Ke6 { own +80 $0.0729 } 85. a6 Rf3+ { own +0 $0.0445 } 86. Ka4 Rf4+ { own +90 $0.0837 } 87. b4 Rf1 { own +60 $0.0816 } 88. a7 Ra1+ { own +110 $0.0660 } 89. Kb5 Nd6+ { own +180 $0.0384 } 90. Kb6 Nc8+ { own +100 $0.0357 } 91. Kc7 Nxa7 { own +240 $0.0613 } 92. b5 Nxb5+ { own +100 $0.0779 } 93. Rxb5 Rc1+ { $0.0306 } 94. Kd8 Kf7 { $0.0353 } 95. Rb7+ Kg8 { $0.0342 } 96. Ke7 Rf1 { $0.0302 } 97. Ke6 Rf8 { $0.0314 } 98. Ke5 Rf7 { $0.0360 } 99. Rb8+ Kg7 { $0.0329 } 100. Ke4 h5 { $0.0302 } 0-1
```
