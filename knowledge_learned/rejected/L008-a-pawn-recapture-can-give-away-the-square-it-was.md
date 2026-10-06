---
title: A pawn recapture can give away the square it was guarding
tags: [outpost, centre-closed, opposite-castling, exchange]
status: rejected
kind: mistake
id: L008-a-pawn-recapture-can-give-away-the-square-it-was
source: 20261002_111123_opus55-learnloop-g3:0:33
learner: hybrid-ctx(t2,claude-opus-5-5)
created: 2026-10-02 11:26
---
## Summary
- Before recapturing with a pawn, list the squares it currently guards. Check which enemy piece could land on each one after the pawn leaves, and whether it arrives with tempo.
- In locked centres, the square in front of the enemy pawn chain is critical. A knight landing there with tempo on your queen can force trades that kill your attack.
- When kings are on opposite wings, don't win a pawn if it lets the opponent force a queen trade. Prefer a prophylactic move and keep the guard pawn.

## Evidence
- Position: `2r2rk1/1p2bpp1/pq1p1n2/3Pp3/6p1/1N3P2/PPPQB2P/1K1R3R w - - 0 17` — played **fxg4**, lost 139 cp.
- Engine best: 17. a3 g6 18. Rdf1 gxf3 19. Bxf3 e4 20. Be2
- Refutation: 17...Ne4 18. Qa5 Qxa5 19. Nxa5 Rc7 20. Rhf1 Bg5 21. Nb3
- Diagnosis: I recaptured fxg4 without noticing that the f3 pawn was the only guard of e4, so ...Ne4 hit my queen and forced a queen trade that left me worse.
- Why general: Pawn captures that open a file often give up control of a central outpost, and checking 'what did this pawn guard?' catches this in any structure.
- Gate: {"accepted": false, "reason": "lesson not shown at any of its own targets", "targets": 0, "targets_proposed": 1}

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
