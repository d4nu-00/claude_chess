---
title: Before a pawn recapture, check which squares that pawn stops guarding
tags: [opposite-castling, outpost, king-safety]
status: rejected
kind: collapse
id: L009-before-a-pawn-recapture-check-which-squares-that
source: 20261002_111123_opus55-learnloop-g3:0:31-45
learner: hybrid-ctx(t2,claude-opus-5-5)
created: 2026-10-02 11:29
---
## Summary
- When recapturing with a pawn in a pawn storm, list the squares it currently guards; giving them up can hand enemy knights a central outpost.
- A tempo-gaining knight jump into the hole that lands on a fork matters more than a half-open file toward their king.
- If pieces can recapture instead, keep the guarding pawn and open the file with a piece.

## Evidence
- Collapse: plies 31–45, 8 moves, 637 cp lost in total (max 296 in one move).
- Moves: g4(-89), fxg4(-139), Qe1(-6), Qg1(-96), Rf1(-10), Qxh1(-0), Bd3(-1), Qe4(-296)
- Followed by Bxe4 (-0) at ply 47.
- How it got there: In a closed Najdorf structure with castling on opposite sides, I played the thematic 16.g4 to open lines against h5. That was already a little loose. The real slide came with 17.fxg4. Recapturing with the f-pawn gave up White's only guard of e4, so Black's knight jumped to e4 with tempo. From there it went to f2 and forked my rooks. I had judged the position as +2 for White because the g-file was 'opening', but in reality my pieces were tied up defending f2 and the d1/h1 rooks. I lost the exchange and kept underestimating Black's activity. That ended in 23.Qe4, which let a material-up opponent trade queens.
- Turning point: ply 33
- Misconception: I thought the pawn recapture that opened a file toward the enemy king was automatically good, and ignored that the f-pawn was the only thing keeping the enemy knight out of e4 and f2.
- Why general: Many wing pawn breaks force a choice of recapture, and the pawn that recaptures often leaves behind holes the opponent's pieces can use for counterplay.
- Gate: {"accepted": false, "reason": "target gain -81 < 20", "targets": 3, "per_target": [{"src": "20261002_111123_opus55-learnloop-g3:0:45", "base_cpl": 10, "cand_cpl": 218}, {"src": "20261002_111123_opus55-learnloop-g3:0:33", "base_cpl": 49, "cand_cpl": 49}, {"src": "20261002_111123_opus55-learnloop-g3:0:37", "base_cpl": 40, "cand_cpl": 73}], "target_base_cpl": 33, "target_cand_cpl": 113, "target_repeats": 2, "controls": 4, "control_mean_delta": -53.5, "targets_proposed": 3}

## Source game
```json
{
 "db_game_id": "20261002_111123_opus55-learnloop-g3:0",
 "run": "20261002_111123_opus55-learnloop-g3",
 "judge": "stockfish depth 18 (lesson) / move_analysis in run",
 "kb_version_at_learning": 3,
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
  "learned_kb_version": 2
 }
}
```
```pgn
[Event "claude_chess opus55-learnloop-g3"]
[Site "claude_chess"]
[Date "2026.10.02"]
[Round "0"]
[White "hybrid-ctx(t2,claude-opus-5-5)"]
[Black "maia3-2400"]
[Result "0-1"]
[Termination "checkmate"]
[BookPlies "8"]
[PlyCount "114"]
[Opening "Sicilian Najdorf"]

1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 { own +90 $0.0505 } 5... a6 6. Be3 { own +30 $0.0494 } 6... e5 7. Nb3 { own +60 $0.0568 } 7... Be6 8. f3 { own +70 $0.0611 } 8... h5 9. Qd2 { own +60 $0.0584 } 9... Nbd7 10. O-O-O { own +60 $0.0625 } 10... Rc8 11. Kb1 { own +60 $0.0642 } 11... Be7 12. Nd5 { own +40 $0.0613 } 12... Bxd5 13. exd5 { own +330 $0.0284 } 13... Nb6 14. Bxb6 { own +35 $0.0673 } 14... Qxb6 15. Be2 { own +60 $0.0591 } 15... O-O 16. g4 { own +80 $0.0571 } 16... hxg4 17. fxg4 { own +210 $0.0662 } 17... Ne4 18. Qe1 { own +40 $0.0676 } 18... Nf2 19. Qg1 { own -120 $0.0783 } 19... Bd8 20. Rf1 { own -80 illegal ['Rhf1: illegal in this position'] $0.1030 } 20... Nxh1 21. Qxh1 { own +390 $0.0759 } 21... Qe3 22. Bd3 { own +60 $0.0739 } 22... Bg5 23. Qe4 { own +110 $0.0899 } 23... Qxe4 24. Bxe4 { own +900 $0.0326 } 24... g6 25. c3 { own +35 $0.0603 } 25... Kg7 26. Kc2 { own +40 $0.0595 } 26... Rh8 27. Rf2 { own +90 $0.0614 } 27... Bf4 28. Nd2 { own -60 $0.0755 } 28... Rxh2 29. Rxh2 { own +45 $0.0718 } 29... Bxh2 30. Nf3 { own +60 $0.0587 } 30... Bf4 31. Kd3 { own +60 $0.0603 } 31... Rh8 32. a4 { own +50 $0.0586 } 32... Rh3 33. Kc4 { own +70 $0.0630 } 33... f5 34. gxf5 { own +0 $0.0366 } 34... gxf5 35. Ng1 { own -30 $0.0697 } 35... Rg3 36. Ne2 { own -165 $0.0795 } 36... fxe4 37. Nxg3 { own +180 $0.0275 } 37... Bxg3 38. a5 { own +40 $0.0562 } 38... Kf6 39. b4 { own +60 $0.0550 } 39... Kf5 40. Kb3 { own +60 $0.0571 } 40... e3 41. b5 { own -640 $0.0498 } 41... e2 42. b6 { own -760 $0.0545 } 42... e1=Q 43. Kc4 { own -170 $0.0496 } 43... Qe2+ 44. Kb3 { own -200 $0.0257 } 44... Qb5+ 45. Kc2 { own -160 $0.0491 } 45... Qxa5 46. c4 { own -40 $0.0516 } 46... Qxb6 47. Kc3 { own -80 $0.0544 } 47... Qc5 48. Kb3 { own -60 $0.0552 } 48... b5 49. cxb5 { own -40 $0.0513 } 49... axb5 50. Kb2 { own -85 $0.0479 } 50... Qxd5 51. Kc3 { $0.0250 } 51... Qc4+ 52. Kb2 { $0.0238 } 52... e4 53. Ka1 { $0.0291 } 53... e3 54. Kb1 { $0.0277 } 54... e2 55. Ka1 { $0.0258 } 55... e1=Q+ 56. Kb2 Qec3+ 57. Kb1 Q4b3# 0-1
```
