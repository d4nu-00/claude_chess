---
title: In rook endings, don't make your rook a passive guard of a weak pawn
tags: [rook-endgame, weak-pawns, seventh-rank, eg-rook]
status: rejected
id: L002-in-rook-endings-don-t-make-your-rook-a-passive-g
source: 20260925_085019_opus-harness-vs-maia3-2700:0:43
learner: hybrid-ctx(t2,threat,claude-opus-5-5)
created: 2026-09-25 09:06
---
## Summary
- When a weak pawn is attacked in a rook ending, compare passive defence with giving it up so your rook reaches the 7th rank or enemy pawns.
- A rook tied to an isolated pawn gets hit by pawn breaks (…c5, …b5). The pawn usually falls later anyway, and your rook stays passive.
- Before defending, ask whether the pawn can hold for long. If not, spend the tempo on rook activity now.

## Evidence
- Position: `2kr4/1pp2ppp/p1p5/5P2/3P4/8/PP3PKP/R7 w - - 1 22` — played **Rd1**, lost 168 cp.
- Engine best: 22. Re1 Rxd4 23. Re7 Rd7 24. Re8+ Rd8 25. Re7 Rf8
- Refutation: 22...c5 23. d5 Rd6 24. Rd3 b5 25. h4 c4 26. Rd4
- Diagnosis: I defended the isolated d-pawn with a passive rook. I missed that …c5 undermines it anyway, while Re1–Re7 gave active counterplay against f7 and the 7th rank.
- Why general: Choosing between passively guarding a doomed weak pawn and activating the rook comes up in almost every rook ending, and the rule that activity beats material applies directly.
- Gate: {"accepted": false, "reason": "target gain 0 < 50", "target_base_cpl": 11, "target_cand_cpl": 11, "target_repeats": 3, "controls": 4, "control_mean_delta": 0.0}

## Source game
```json
{
 "db_game_id": "20260925_085019_opus-harness-vs-maia3-2700:0",
 "run": "20260925_085019_opus-harness-vs-maia3-2700",
 "judge": "stockfish depth 18 (lesson) / move_analysis in run",
 "kb_version_at_learning": 0,
 "engine": "Stockfish 17",
 "harness_commit": "c560a6b",
 "white": "hybrid-ctx(t2,threat,claude-opus-5-5)",
 "black": "maia3-2700",
 "result": "0-1",
 "date": "2026.09.25",
 "termination": "adjudication (resign: SF -9999cp for 6 plies)",
 "player_config": {
  "model": "claude-opus-5-5",
  "white_spec": "hybrid-ctx",
  "black_spec": "maia3:2700",
  "ctx_version": 3,
  "threat_agent": true,
  "search": "compare",
  "learned_kb_version": null
 }
}
```
```pgn
[Event "claude_chess opus-harness-vs-maia3-2700"]
[Site "claude_chess"]
[Date "2026.09.25"]
[Round "0"]
[White "hybrid-ctx(t2,threat,claude-opus-5-5)"]
[Black "maia3-2700"]
[Result "0-1"]
[Termination "adjudication (resign: SF -9999cp for 6 plies)"]
[BookPlies "6"]
[PlyCount "107"]
[Opening "Ruy Lopez"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Bxc6 { own +140 $0.1227 } 4... dxc6 5. O-O { own +110 $0.1062 } 5... Bg4 6. d3 { own +40 $0.0869 } 6... Qf6 7. Nbd2 { own +70 $0.0978 } 7... Ne7 8. Nc4 { own +70 $0.0949 } 8... Ng6 9. Ne3 { own +70 $0.0996 } 9... Bxf3 10. Qxf3 { own +460 $0.0793 } 10... Qxf3 11. gxf3 { own +800 $0.0224 } 11... Nh4 12. Nf5 { own -40 $0.1178 } 12... Nxf3+ 13. Kg2 { own +110 $0.0898 } 13... Nd4 14. c3 { own +90 $0.1013 } 14... Nxf5 15. exf5 { own +320 $0.0227 } 15... O-O-O 16. Rd1 { own +90 $0.0822 } 16... Be7 17. Be3 { own +80 $0.1327 } 17... Bf6 18. d4 { own +70 $0.0933 } 18... exd4 19. Bxd4 { own +230 $0.0941 } 19... Bxd4 20. Rxd4 { own +420 $0.0788 } 20... Rxd4 21. cxd4 { own +500 $0.0211 } 21... Rd8 22. Rd1 { own -20 $0.0910 } 22... Rd5 23. f6 { own -10 $0.1088 } 23... gxf6 24. Kf3 { own +90 $0.1086 } 24... c5 25. Ke4 { own +70 $0.0980 } 25... Rxd4+ 26. Rxd4 { own +100 $0.0235 } 26... cxd4 27. Kxd4 { own +230 $0.0853 } 27... Kd7 28. Kd5 { own +60 $0.0739 } 28... b6 29. a4 { own +40 $0.0785 } 29... c6+ 30. Kd4 { own +40 $0.0781 } 30... Kd6 31. Kc4 { own +60 $0.0841 } 31... Ke5 32. Kd3 { own +60 $0.0766 } 32... Kf4 33. Ke2 { own +130 $0.0706 } 33... c5 34. h3 { own +60 $0.0855 } 34... b5 35. a5 { own +70 $0.0792 } 35... c4 36. Kd2 { own +90 $0.0890 } 36... Kf3 37. Ke1 { own +110 $0.0876 } 37... b4 38. Kf1 { own +90 $0.1075 } 38... c3 39. bxc3 { own +0 $0.0340 } 39... bxc3 40. Ke1 { own +0 $0.0271 } 40... f5 41. h4 { own -10 $0.0712 } 41... h5 42. Kd1 { own -100 $0.0249 } 42... Kxf2 43. Kc2 { own +80 $0.0725 } 43... f4 44. Kxc3 { own +120 $0.0866 } 44... f3 45. Kd4 { own -30 $0.0968 } 45... Ke2 46. Kc5 { own -580 $0.0800 } 46... f2 47. Kb6 { own -680 $0.0767 } 47... f1=Q 48. Kxa6 { own +120 $0.0868 } 48... Qb1 49. Ka7 Kd3 50. Ka6 { $0.0255 } 50... Kc4 51. Ka7 Kc5 52. Ka8 { $0.0303 } 52... Kc6 53. a6 { $0.0255 } 53... Kc7 54. Ka7 { $0.0285 } 0-1
```
