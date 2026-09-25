# Opus 5.5's thoughts — Opus + harness (White) vs Maia-1900

## Summary of how Opus thought

**1. Opening — knew the theory.** Named the Exchange Variation (4.Bxc6) and correctly rejected
5.Nxe5 because "...Qd4 forks e5 and e4 and wins it back" (standard Ruy Lopez theory). 6.h3,
7.Qxf3, 8.d3 were all textbook, with explicit threat checks ("Nf6 attacks e4, defended only by the queen").

**2. Spotting the tactic.** 9.Qg3: "hits g7 and e5 (pawn e5 defended? no…)". The comparison call
adds: "the engine confirms it wins a pawn; the Bxf2+ check it allows is harmless" — Claude
proposing, the Python search confirming, Claude judging the side-effects.

**3. Using the context.** Opus repeatedly quotes the v3 material check: "the engine says only
Qb4, Qb3 and Qa3 keep material" (13), "only dxc4, Qc3 and Qa2 avoid losing material" (19),
"only five queen moves avoid losing material" (23), "Four moves avoid losing material" (28).
It reasons *within* the safe set rather than blundering and being vetoed (search overruled it
once in 52 moves).

**4. Textbook technique when ahead.** "White is a pawn up… consolidate" (14–18), trade queens
into a better ending (26: "Qxc7 trades queens into a better ending"), "trade pieces and advance
the d-pawn" (37), push the passed b-pawn "with piece support" (46), and at the end
**stalemate awareness**: "up a bishop, a knight and three pawns against a bare king… the only
danger is stalemate" (54).

**5. Recurring narrative errors (play unaffected — the search checks material).**
- **Recaptures described as wins:** 27.Rxc7 "wins it [the queen] outright" and 32.Nxb3
  "wins a full rook" — both were recaptures completing trades. Sonnet made the same error
  (22.Bxg5 "wins queen for bishop"). An LLM pattern: it evaluates the capture, not the sequence.
- **Material-count drift:** "a pawn up" (38) while actually three up (it said so at 35–37);
  22: "Qxb3 loses the queen for a rook" (it would lose the queen for a pawn).
- For the distillation dataset these are exactly why only `[verified]` facts should be trusted.

**6. Its one real mistake:** 24.Nd2 (−2.2). Thinking: "the b3 pawn is an advanced target… hit b3
or trade off Black's active pieces". Stockfish preferred e5; Opus went for a long-term target
instead of the more forcing central push — a strategic, not tactical, miss.

## Move by move

Run `20260924_225106_opus-harness-vs-maia1900`. Every note Opus wrote, move by move: **proposer** (thinking + candidates with reasons), **comparison** (positional ranking of the safe candidates), **threat agent** (the opponent's most dangerous reply to the move played). Stockfish figures are post-game analysis only — Opus never saw them.

### 4. Bxc6  —  Stockfish +0.0 after the move, loss 39 cp (best: Ba4)
- **Thinking:** Bb5 is attacked by a6 and must move or trade; Ba4 is the main line, Bxc6 is the Exchange Variation. Black has no other threats and White has no checks.
- **Candidates:** Ba4 (0.6) — Morphy mainline, keeps pin pressure; Bxc6 (0.25) — Exchange Variation, damages structure; Bc4 (0.08) — retreat eyeing f7; Be2 (0.07) — safe solid retreat
- **Comparison:** Ba4 is the main line keeping the pin pressure; Bxc6 Exchange Variation is fully sound (the engine's 'en prise' note is just a normal trade). Bc4 loses time and Be2 is passive.
- **Threat agent on Bxc6:** dxc6 — bishop pair; Nxe5 Qd4 regains the pawn
- *Decision:* hybrid

### 5. O-O  —  Stockfish -0.1 after the move, loss 12 cp (best: Nc3)
- **Thinking:** No White pieces are hanging and Black threatens nothing immediate. Nxe5 grabs a pawn, but ...Qd4 forks e5 and e4 and wins it back, so O-O is the main line.
- **Candidates:** O-O (0.5) — main line, safeguards e4 indirectly; Nc3 (0.2) — develops, defends e4; d4 (0.15) — opens centre, trade toward endgame; Nxe5 (0.15) — wins pawn but Qd4 regains
- **Comparison:** O-O is the main line of the Exchange Ruy, supporting a later d4 with the king safe. Nxe5 regains nothing after Qd4/Qg5 forks and hands Black the initiative, while d4 and Nc3 are playable but less precise.
- **Threat agent on O-O:** Bg4 — pin Nf3, then Qf6/Bxf3 to wreck the kingside
- *Decision:* hybrid

### 6. h3  —  Stockfish +0.4 after the move, loss 0 cp (best: h3)
- **Thinking:** Nxe5 fails to ...Qd4 forking e5 and g4 area, and Bg4 pins nothing yet; the standard continuations are h3 (asking the bishop), d3, Re1 and c3.
- **Candidates:** h3 (0.4) — question the bishop, main line; d3 (0.25) — solid support of e4; Re1 (0.15) — defend e4, flexible; c3 (0.2) — prepare d4 break
- **Comparison:** h3 is the main line, and White need not fear the h5 gambit if he simply declines the bishop. d3 and Re1 are solid; c3 is slower and takes c3 away from the knight.
- **Threat agent on h3:** h5 — gambit: hxg4 hxg4 opens h-file, Qh4 mating ideas
- *Decision:* hybrid

### 7. Qxf3  —  Stockfish +0.3 after the move, loss 1 cp (best: Qxf3)
- **Thinking:** Black's bishop on f3 is undefended and attacks Qd1 and e4; recapturing is mandatory. Qxf3 keeps the structure intact and is standard.
- **Candidates:** Qxf3 (0.85) — recapture, healthy structure; gxf3 (0.12) — recapture, damages own king; Qe1 (0.02) — saves queen but loses piece; Qe2 (0.01) — saves queen, loses bishop trade
- **Comparison:** Qxf3 recaptures with a healthy structure and an active queen, keeping the king shelter intact. gxf3 wrecks the kingside pawns and invites ...Qg5+ ideas.
- **Threat agent on Qxf3:** Qd4 — centralizes, hits e4 and b2
- *Decision:* vetoed Qe1,Qe2; hybrid

### 8. d3  —  Stockfish +0.6 after the move, loss 6 cp (best: d3)
- **Thinking:** No pieces hang for either side, and Black's Nf6 attacks e4, which is defended only by the queen. Natural developing moves that also guard e4 are best: d3, Nc3 and Re1.
- **Candidates:** d3 (0.4) — solid e4 support, opens Bc1; Nc3 (0.3) — develops, guards e4; Re1 (0.15) — rook defends e4; Qe2 (0.15) — keeps e4 guarded, frees f3
- **Comparison:** Quiet opening position with a closed centre, where solid development and support for e4 matter most. d3 is the most flexible move; Nc3 is also natural but allows ...Bb4, and Qe2 wastes time.
- **Threat agent on d3:** Qd7 — O-O-O and g5 kingside pawn storm
- *Decision:* hybrid

### 9. Qg3  —  Stockfish +0.4 after the move, loss 20 cp (best: Nd2)
- **Thinking:** Nothing hanging immediately; Qg3 hits g7 and e5 (pawn e5 defended? no—e5 only by nothing after Bc5), so Qg3 gains material threats. Development moves Nd2/Nc3/Be3 are solid alternatives.
- **Candidates:** Qg3 (0.45) — double attack g7 and e5; Nd2 (0.2) — develop, Nc4 ideas; Nc3 (0.15) — develop, support e4; Be3 (0.2) — challenge Bc5
- **Comparison:** Qg3 forks e5 and g7, and the engine confirms it wins a pawn; the Bxf2+ check it allows is harmless. Be3 is the most solid of the rest, contesting the active Bc5 and developing.
- **Threat agent on Qg3:** Nh5 — tempo on queen, frees g7 defence
- *Decision:* hybrid

### 10. Qxe5  —  Stockfish +1.8 after the move, loss 9 cp (best: Qxe5)
- **Thinking:** Pawn e5 is undefended, so Qxe5 wins a pawn, though Black gets tempo play with ...Bd6, ...Re8 or ...Nd7. Pf2 is pinned by Bc5, so the quiet alternatives develop pieces or step out of the pin.
- **Candidates:** Qxe5 (0.45) — wins undefended e5 pawn; Nc3 (0.2) — develops knight, guards e4; Bg5 (0.15) — pins Nf6, develops; Kh1 (0.1) — unpins f2, prepares f4; Nd2 (0.1) — develops, Nf3/Nb3 plans
- **Comparison:** Qxe5 wins a clean pawn that the search confirms, though the queen gets harassed and White is behind in development. Among the quiet moves, Nc3 develops most usefully, Bg5 walks into ...Nh5 or ...h6, and Kh1 is slow.
- **Threat agent on Qxe5:** Re8 — tempo on queen, then Nxe4/Bd6 regains pawn
- *Decision:* hybrid

### 11. Qc3  —  Stockfish +2.0 after the move, loss 0 cp (best: Qg5)
- **Thinking:** The queen on e5 is undefended and attacked by Bd6, and only four retreats keep material. Pe4 is still covered by d3, and White has no useful checks or winning captures.
- **Candidates:** Qc3 (0.32) — safe centralized retreat, keeps e4 guarded; Qg5 (0.28) — kingside pressure; Nf6 guarded by g7, Qd8; Qf5 (0.22) — active retreat, but ...g6 gains tempo; Qa5 (0.18) — safe square, eyes c7
- **Comparison:** White is a pawn up and must retreat the queen; the question is which square gives safety plus central control. Qc3 is the most stable, Qf5 and Qg5 are exposed to tempo moves, and Qa5 is offside.
- **Threat agent on Qc3:** Nxe4 — knight hits queen; follow-up Bh2+ tricks
- *Decision:* hybrid

### 12. Be3  —  Stockfish +2.1 after the move, loss 0 cp (best: Be3)
- **Thinking:** Nothing of ours is hanging: e4 is attacked twice but d3 defends it, and ...Nxe4 dxe4 gives up a knight for pawns. White is behind in development, so the priority is to develop the queenside and cover e4 while keeping the healthier pawn structure.
- **Candidates:** Nd2 (0.3) — develops, guards e4, frees Bc1; Re1 (0.25) — overprotects e4; Bg5 (0.25) — develops, pins Nf6; Be3 (0.2) — solid development
- **Comparison:** White is a pawn up and needs to finish development; Be3 and Nd2 are the most natural moves. Bg5 drops the e4 pawn to Nxe4.
- **Threat agent on Be3:** Nh5 — Nf4 hitting d3/g2, Qh4 pressure
- *Decision:* hybrid

### 13. Qb3  —  Stockfish +2.1 after the move, loss 12 cp (best: Qb3)
- **Thinking:** The white queen on c3 is attacked by Be5, and the engine says only Qb4, Qb3 and Qa3 keep material. Qb3 is the most active, eyeing b7 and f7, and there are no useful checks or safe captures.
- **Candidates:** Qb3 (0.45) — safe, hits b7 and f7; Qb4 (0.3) — safe, eyes b7; Qa3 (0.15) — safe retreat; Qc4 (0.1) — active; engine flags loss, verify
- **Comparison:** Qb3 is the most active retreat, hitting b7 and eyeing the a2-g8 diagonal toward f7 while staying safe. Qb4 can be harassed by ...a5 or ...c5, and Qa3 is passive.
- **Threat agent on Qb3:** Qd6 — eye h2 via Bh2+ Kh1 Bf4 kingside attack
- *Decision:* vetoed Qc4; hybrid

### 14. Nd2  —  Stockfish +2.2 after the move, loss 7 cp (best: Nd2)
- **Thinking:** White is a pawn up. Nothing is hanging, and Black has no immediate threat since b2 and e4 are both defended. The priority is finishing development with Nb1 while avoiding the flagged queen moves that lose material.
- **Candidates:** Nd2 (0.4) — develop, support e4 and c4; Nc3 (0.25) — develop, guard d5 and e4; f4 (0.15) — kick bishop, gain space; a4 (0.2) — clamp b5, queenside space
- **Comparison:** White is a pawn up and should finish development calmly. Nd2 and Nc3 both develop, with Nd2-f3/c4 slightly more flexible, while f4 loosens the king and a4 is slow.
- **Threat agent on Nd2:** Nh5 — Nf4 jump, kingside pressure with Qg5
- *Decision:* hybrid

### 15. Nf3  —  Stockfish +2.7 after the move, loss 0 cp (best: f4)
- **Thinking:** White is a pawn up; Black's Be5 eyes b2, and the queen on b3 is loosely placed after ...b5. Safe consolidating moves that also hit e5 or guard b2 are preferred.
- **Candidates:** Nf3 (0.35) — attacks Be5, develops; Rab1 (0.2) — secures b2, frees queen; f4 (0.2) — kicks bishop, gains space; a3 (0.15) — prophylaxis, keeps structure; Qa3 (0.1) — hits a6, repositions queen
- **Comparison:** White is a pawn up with a healthy kingside majority, so solid development and neutralising Black's queenside counterplay matter most. Nf3 develops with tempo on Be5 and covers h2, while a3 is useful prophylaxis against b4.
- **Threat agent on Nf3:** Bd6 — keep the bishop, then c5-c4 hitting the queen
- *Decision:* hybrid

### 16. a4  —  Stockfish +1.8 after the move, loss 80 cp (best: Qc3)
- **Thinking:** Nothing of White's is hanging: e4 is covered by d3, and Nxe4 dxe4 Rxe4 would cost Black a knight for two pawns. Black has no immediate threat, so White, a pawn up, should play solid moves that make pieces more active and press on b5.
- **Candidates:** a4 (0.3) — pawn break against b5, opens a-file; Rfe1 (0.25) — backs up e4, calm development; Bg5 (0.2) — pins Nf6, eases pressure on e4; Rae1 (0.15) — rook to e-file, keeps f-rook; c4 (0.1) — second break against b5
- **Comparison:** White is a pawn up with a solid centre, and a4 opens the a-file against Black's weak queenside (b5, a6, doubled c-pawns). Rfe1 is a sound way to defend e4; Bg5 invites h6 and giving up the bishop.
- **Threat agent on a4:** bxa4 — opens b-file, then ...Rxb2 after Qxa4
- *Decision:* hybrid

### 17. axb5  —  Stockfish +1.7 after the move, loss 5 cp (best: Rfe1)
- **Thinking:** Nothing of White's is hanging, but Black's ...c4 would hit the queen and d3. Nothing wins material outright, so the candidates are safe moves that keep the queenside tension or fork with e5.
- **Candidates:** axb5 (0.35) — opens a-file, keeps even material; e5 (0.25) — pawn forks Bd6 and Nf6; a5 (0.2) — fixes the queenside, stops ...c4 ideas; c4 (0.2) — stops ...c4, pressures b5
- **Comparison:** axb5 opens the a-file for White's rook while Black's queenside pawns stay weak, and e5 simply drops a pawn. a5 fixes the queenside safely; c4 weakens d4 and d3.
- **Threat agent on axb5:** c4 — pawn hits Qb3 and d3, opening lines against the queen
- *Decision:* hybrid

### 18. Ra7  —  Stockfish +1.6 after the move, loss 0 cp (best: e5)
- **Thinking:** White is a pawn up, and no pieces are hanging for either side. Black's main idea is ...c4 to gain tempo on the queen, or pressure on e4. Activating the rooks on the open a-file and consolidating look best.
- **Candidates:** Ra6 (0.3) — activate rook, pressure d6; Rfe1 (0.25) — reinforce e4, consolidate; Ra7 (0.2) — seize 7th, hit c7; Nd2 (0.25) — control c4, guard e4
- **Comparison:** White holds the open a-file, and the rook on the 7th adds to the queen's pressure on f7 and hits c7. Doubling on the a-file is the natural plan, while Nd2 is passive.
- **Threat agent on Ra7:** c4 — tempo on queen, rook a7 offside
- *Decision:* hybrid

### 19. Qa2  —  Stockfish +1.2 after the move, loss 33 cp (best: Qc3)
- **Thinking:** White's queen on b3 is attacked by the c4 pawn, and only dxc4, Qc3 and Qa2 avoid losing material. dxc4 grabs a pawn and opens lines; the queen retreats are the fallbacks.
- **Candidates:** dxc4 (0.5) — wins pawn, queen defended; Qa2 (0.25) — doubles on a-file safely; Qc3 (0.2) — safe retreat, eyes f6/c7; Qxb5 (0.05) — desperado check, likely bad
- **Comparison:** Qa2 keeps the queen safe behind Ra7 and holds e4 via d3. dxc4 releases the tension, weakening e4 and opening the b-file for Black's rooks.
- **Threat agent on Qa2:** cxd3 — opens c-file, pressure on c2/e4
- *Decision:* vetoed Qxb5; hybrid

### 20. cxd3  —  Stockfish +2.1 after the move, loss 0 cp (best: cxd3)
- **Thinking:** Black's d3 pawn forks c2 and threatens dxc2, while e4 hangs to Nxe4/Rxe4. cxd3 wins the pawn back and removes the threat; e5 is a forcing alternative that hits Nf6 and the pin on f7 via Qa2 matters.
- **Candidates:** cxd3 (0.6) — recaptures pawn, removes dxc2; e5 (0.2) — hits Nf6 and Bd6, forcing; Ng5 (0.12) — eyes f7 with Qa2 battery; Qxf7+ (0.08) — forcing check, likely unsound
- **Comparison:** cxd3 recaptures the pawn and restores material with a solid position and active Ra7. The other moves ignore the hanging pawns and give Black activity.
- **Threat agent on cxd3:** Qb6 — offer queen trade, hit b2 and e3
- *Decision:* vetoed Qxf7+; hybrid

### 21. Rc1  —  Stockfish +2.4 after the move, loss 14 cp (best: Nd4)
- **Thinking:** Nothing of White's is hanging, and Qxf7+, Rxc7 and Ra8 all lose material. Black's main idea is ...b3 hitting the queen, so centralizing the queen with Qc4 (hitting b4 and c7) and taking the c-file look best.
- **Candidates:** Qc4 (0.4) — centralize, hit b4 and c7; Rc1 (0.25) — take c-file, pressure c7; Qa4 (0.15) — attack Re8 and b4; Nd4 (0.2) — centralize knight, eye c6/b5
- **Comparison:** White is up a pawn and should pile up on the weak c7 pawn while keeping the kingside safe. Rc1 and Qc4 both add a second attacker to c7, with Rc1 also keeping the queen's pressure on f7.
- **Threat agent on Rc1:** b3 — kicks Qa2, pawn guarded by Rb8
- *Decision:* hybrid

### 22. Qa4  —  Stockfish +2.5 after the move, loss 0 cp (best: Qa5)
- **Thinking:** The queen on a2 is attacked by the b3 pawn, and only queen retreats along the a-file or to b1 avoid losing material. The b3 pawn is defended by Rb8, so Qxb3 loses the queen for a rook.
- **Candidates:** Qa4 (0.35) — safe, eyes Re8 and b3; Qa5 (0.25) — active, supports Ra7; Qb1 (0.2) — guards b2, solid; Qa6 (0.2) — hits Bd6, active
- **Comparison:** The queen must move. Qa4 eyes both b3 and e8 and stays flexible; Qa5 adds a third attacker on c7 but can be harassed by ...Rb5.
- **Threat agent on Qa4:** Bd7 — hits queen with tempo, covers Re8
- *Decision:* hybrid

### 23. Qc6  —  Stockfish +2.5 after the move, loss 73 cp (best: Qa5)
- **Thinking:** Qa4 is attacked by Rb4, and the engine says only five queen moves avoid losing material. Qc6 is the most active retreat: it hits Bd6 and eyes Re8, while Qa5 and Qa3 keep pressure on Rb4.
- **Candidates:** Qc6 (0.35) — active retreat, hits d6/e8; Qa5 (0.25) — attacks Rb4, eyes c7; Qa6 (0.2) — safe, supports Ra7; Qa3 (0.2) — pressures Rb4 and b-pawn
- **Comparison:** Qc6 centralizes the queen, adds a third attacker on c7 and eyes Re8, which leaves Black passive. Qa3 is the most passive retreat, even though it watches b3.
- **Threat agent on Qc6:** Rxb2 — grabs b2, b-pawns roll toward promotion
- *Decision:* hybrid

### 24. Nd2  —  Stockfish +3.0 after the move, loss 221 cp (best: e5)
- **Thinking:** Ra7 is defended by Be3, so Qxa7 fails. Black has no immediate threat, but the b3 pawn is an advanced target and Rb4 is loose. White should hit b3 or trade off Black's active pieces.
- **Candidates:** Nd2 (0.32) — attacks b3, reroutes knight; Bc5 (0.25) — challenges Bd6, eyes Rb4; Rc3 (0.23) — attacks b3 pawn; Qa6 (0.2) — safe queen, supports Ra7
- **Comparison:** The b3 pawn is Black's main asset, and White's plan should be to round it up while keeping Ra7 protected. Nd2 hits b3 and guards e4; Rc3 also targets b3; Bc5 and Qa6 do less toward that plan.
- **Threat agent on Nd2:** Rb6 — hit Qc6, queen loses post, pressure b2
- *Decision:* hybrid

### 25. Nc4  —  Stockfish +2.7 after the move, loss 5 cp (best: Nc4)
- **Thinking:** No black piece hangs and nothing is en prise to White. Black's Rb4 eyes b2 and Qb8 hits Ra7, which Be3 defends. Nc4 blocks the b-file pressure and hits d6, while Qc3 and Bc5 attack the active black pieces.
- **Candidates:** Nc4 (0.35) — hits Bd6, blocks, active knight; Qc3 (0.25) — attacks Rb4 and b3 pawn; Bc5 (0.2) — trade key defender Bd6; Rxc7 (0.2) — exchange sac breaking c7
- **Comparison:** Nc4 is the most harmonious: the knight blockades b3, hits d6, is protected by the queen and Rc1, and Bf4 is harmless. Qc3 and Bc5 are playable but passive or give up the good bishop; Rxc7 simply drops material.
- **Threat agent on Nc4:** Rxc4 — exchange sac removes knight, then Bd6/b-pawn play
- *Decision:* hybrid

### 26. Qxc7  —  Stockfish +3.8 after the move, loss 65 cp (best: Qxc7)
- **Thinking:** Nothing of ours is hanging and Black has no immediate threat. Pc7 is attacked twice and defended only by the queen, so we can win it; Rxc7 keeps the queens on, while Qxc7 trades queens into a better ending.
- **Candidates:** Rxc7 (0.5) — wins pawn, rook on 7th; Qxc7 (0.3) — wins pawn, trades queens; Na5 (0.1) — reroute toward c6/b3; Kh1 (0.1) — safe waiting move
- **Comparison:** Qxc7 wins the c7 pawn safely, since Ra7 protects the queen and Black can only trade into a worse endgame. It also keeps White's grip on the 7th rank, while the other two moves give Black time to consolidate.
- **Threat agent on Qxc7:** Rxc4 — grab knight first, then trade queens
- *Decision:* vetoed Rxc7; hybrid

### 27. Rxc7  —  Stockfish +4.0 after the move, loss 0 cp (best: Rxc7)
- **Thinking:** Black's queen on c7 is undefended and attacked by Ra7, so Rxc7 wins it outright; nothing else of White's hangs to a stronger threat. Alternatives are only for search diversity.
- **Candidates:** Rxc7 (0.94) — wins undefended queen; Ra6 (0.02) — keeps rook, minor loss; Ra3 (0.02) — attacks b3; Rc2 (0.02) — defensive
- *Decision:* vetoed Ra6,Ra3,Rc2; only tactically sound candidate

### 28. Rc3  —  Stockfish +4.0 after the move, loss 0 cp (best: Ne5)
- **Thinking:** Black threatens Rxd3; the pd3 pawn is undefended. Four moves avoid losing material: Rc3 (defends d3 and hits b3), Ne5 (guards d3), e5 (counterattacks Nf6) and Bd2 (hits Rb4).
- **Candidates:** Rc3 (0.4) — defends d3, attacks b3 pawn; Ne5 (0.25) — guards d3, eyes f7; e5 (0.2) — counterattacks Nf6; Bd2 (0.15) — attacks Rb4 with tempo
- **Comparison:** Rc3 solidly guards d3, hits the weak b3 pawn and keeps the doubled rooks active. Ne5 invites Bd6 hitting both c7 and e5, and Bd2 simply gives up d3.
- **Threat agent on Rc3:** Nxe4 — knight hits Rc3 and f2; dxe4 Rd1+ with Rxc4 tricks
- *Decision:* vetoed e5; hybrid

### 29. Nd2  —  Stockfish +3.6 after the move, loss 60 cp (best: g3)
- **Thinking:** No White pieces are hanging, and Black has no immediate threat; the Nc4 is defended three times. White is two pawns up, so the aim is to win the weak b3 pawn by driving off or outnumbering its only defender, Rb4, without allowing ...Rxb2.
- **Candidates:** Bd2 (0.35) — hits Rb4, then Rxb3; Nd2 (0.25) — second attacker on b3; Na3 (0.15) — attack b3, reroute knight; Kf1 (0.25) — centralize king, safe
- **Comparison:** Nd2 hits the weak b3 pawn, which only the Rb4 defends, and pulls the knight out of the rook's attack. Kf1 is a sound centralizing move, while Bd2 and Na3 are passive.
- **Threat agent on Nd2:** Bd6 — bishop attacks Rc7 and the rook on b4 becomes active
- *Decision:* hybrid

### 30. d4  —  Stockfish +4.0 after the move, loss 0 cp (best: d4)
- **Thinking:** Pd3 is attacked twice, and Black's b3 pawn is loose. Only Rxb3, Nxb3 and d4 avoid losing material. d4 gains time on the e5 knight and keeps the extra pawn; the b3 captures cash in a pawn first.
- **Candidates:** d4 (0.4) — saves d-pawn with tempo on knight; Nxb3 (0.3) — wins b3 pawn, knight active; Rxb3 (0.25) — trade rooks, grab pawn; f4 (0.05) — kick knight, forcing
- **Comparison:** d4 saves the pawn with tempo on Ne5 and keeps White's edge. Rxb3 lets Black win back d3 and activate their pieces.
- **Threat agent on d4:** Ng6 — safe retreat; Nc4/Nd3 fail to rook captures, Rdxd4 costs an exchange
- *Decision:* vetoed Nxb3,f4; hybrid

### 31. Rxb3  —  Stockfish +4.4 after the move, loss 0 cp (best: R7c4)
- **Thinking:** Pb3 is loose, attacked by Rc3 and Nd2 and defended only by Rb4; Black threatens nothing immediate. Rxb3 wins it and trades rooks while keeping e4 covered by Nd2, whereas Nxb3 would let ...Rxe4 follow.
- **Candidates:** Rxb3 (0.55) — wins pawn, trades rooks; Nxb3 (0.2) — wins pawn, but e4 weakens; d5 (0.12) — push passed pawn; f3 (0.13) — shore up e4 first
- **Comparison:** Rxb3 wins a clean pawn and keeps the strong Rc7 and the central pawns, so it is clearly best. The alternatives leave material level, and Nxb3 loosens the grip on e4.
- **Threat agent on Rxb3:** Rxb3 — trade rooks, then press d4 with Rd8
- *Decision:* hybrid

### 32. Nxb3  —  Stockfish +4.5 after the move, loss 0 cp (best: Nxb3)
- **Thinking:** Black's Rb3 is undefended and attacked by Nd2, so Nxb3 wins a full rook and is clearly best. Alternatives are much weaker but included for diversity.
- **Candidates:** Nxb3 (0.94) — wins undefended rook; Nc4 (0.02) — blocks b-file, attacks nothing; Rc2 (0.02) — defends b2; Bxh6 (0.02) — tactical shot, loses material
- *Decision:* vetoed Nc4,Rc2,Bxh6; only tactically sound candidate

### 33. Rc3  —  Stockfish +4.4 after the move, loss 28 cp (best: Nc5)
- **Thinking:** The knight on b3 is undefended and attacked by Rb8, and b2 falls if the knight moves away. Rc3 defends b3, which also keeps b2 shielded, so it is the only move that doesn't lose material.
- **Candidates:** Rc3 (0.8) — defends Nb3, keeps b2 safe; Nd2 (0.08) — retreat knight, gives b2; Nc5 (0.07) — active knight, gives b2; Na5 (0.05) — knight to a5, gives b2
- **Comparison:** Rc3 guards the knight and keeps b2, preserving the three-pawn edge and the passed b-pawn. The other moves give up b2 and activate Black's rook, but White stays two pawns up with central passers.
- **Threat agent on Rc3:** Bb4 — harass rook, activate bishop
- *Decision:* hybrid

### 34. Rc2  —  Stockfish +5.0 after the move, loss 0 cp (best: Rc2)
- **Thinking:** Rc3 is attacked by Bb4, and Bxc3 bxc3 would lose the exchange, so the rook must move to one of the safe squares; there are no Black pieces hanging and Rc8+ just loses the rook. Rc4 is the most active choice because it hits the bishop (defended by Rb8), and the other safe squares keep the extra pawns and give some activity.
- **Candidates:** Rc4 (0.35) — active, attacks Bb4; Rc2 (0.25) — safe, guards b2 and 2nd rank; Rd3 (0.2) — supports d4 passer; Rc6 (0.15) — active, pressures g6 and 6th rank; Rc1 (0.05) — safe retreat
- **Comparison:** Rc4 and Rc6 lose material, so only Rc2 and Rd3 keep White's extra pawns. Rc2 is slightly more solid: it holds the c-file, guards b2 and avoids tempo-gaining ...Nf4 hits.
- **Threat agent on Rc2:** Rc8 — contests c-file, offers rook trade
- *Decision:* hybrid

### 35. Nc5  —  Stockfish +5.3 after the move, loss 28 cp (best: Nc1)
- **Thinking:** Nb3 is undefended and attacked by Rb8, while Black's Be1 is loose and hits f2. White is three pawns up, so save the knight or trade pieces safely.
- **Candidates:** Nc5 (0.35) — saves knight, strong outpost; Nd2 (0.25) — saves knight, guards f3/e4; Bd2 (0.2) — offers bishop trade; Kf1 (0.2) — attacks Be1, forces trade
- **Comparison:** Nc5 centralises the knight on a strong outpost and supports the d-pawn. Nd2 also rescues the knight and restricts Be1, likely forcing a piece trade that suits the side ahead.
- **Threat agent on Nc5:** Bb4 — hit knight, eye d2/rook activity
- *Decision:* hybrid

### 36. d5  —  Stockfish +4.8 after the move, loss 63 cp (best: Nd3)
- **Thinking:** Nothing is hanging right now: Nc5 is attacked by Bb4 but defended twice, and b2 is covered by Rc2. Black threatens nothing immediate, so the priorities are to harass the bishop, push the d-passer and activate the king.
- **Candidates:** Nd3 (0.35) — hits bishop, covers b2; d5 (0.25) — push passed pawn; Kf1 (0.2) — centralize king; f3 (0.2) — solidify e4, king route
- **Comparison:** White is up material and should advance the protected d-pawn to press, while keeping b2 covered. Nd3 gains a tempo on the bishop but is more passive; the king moves are useful but slow.
- **Threat agent on d5:** Ne5 — blockade e5, eye c4/d3
- *Decision:* hybrid

### 37. f4  —  Stockfish +4.7 after the move, loss 47 cp (best: Na6)
- **Thinking:** Nothing of White's is hanging: Nc5 is attacked by Bb4 but defended twice. White is three pawns up, so it should trade pieces and advance the d-pawn, while watching for knight jumps to Nc4 or Nd3.
- **Candidates:** Bd4 (0.3) — attacks Ne5, centralizes, supports Nc5; f4 (0.25) — kicks knight, gains space; Kf1 (0.2) — king activation, covers e2/d3 squares; d6 (0.15) — advance passer; Nb3 (0.1) — retreat knight, unpin tension
- **Comparison:** White's protected d5-passer is the long-term asset, and dislodging the e5 blockader is the key plan. f4 does that at once, while d6 gives up the pawn's protection too early.
- **Threat agent on f4:** Nd3 — knight forks f4, b2, c5
- *Decision:* hybrid

### 38. f5  —  Stockfish +4.6 after the move, loss 55 cp (best: Na6)
- **Thinking:** No hanging pieces for either side. Black's Ng6 hits f4, but Be3 defends it. White is a pawn up with a protected d-passer, so the plan is to push it or gain space while keeping f4 and Nc5 covered.
- **Candidates:** d6 (0.35) — advance protected passer; f5 (0.25) — kick knight, gain space; Kf2 (0.22) — activate king safely; e5 (0.18) — support d6 push
- **Comparison:** Only f5 keeps material level; the others lose the Nc5 to Bxc5 since Be3 is overloaded/defending f4 and the knight falls. f5 also gains space and kicks the knight to a poor square.
- **Threat agent on f5:** Ne5 — knight takes the strong e5 outpost, eyeing c4 and d3
- *Decision:* hybrid

### 39. d6  —  Stockfish +3.9 after the move, loss 44 cp (best: Na6)
- **Thinking:** No White pieces are hanging, and Black has no immediate threats; Bb4 on Nc5 is covered twice. The d-pawn can advance safely to d6 because the knight on c5 blocks the b4 bishop, while Bd4 and king activation are solid alternatives.
- **Candidates:** d6 (0.4) — push protected passer, threat d7; Bd4 (0.25) — hits Ne5, centralizes bishop; Kf2 (0.2) — activate king; b3 (0.15) — secure b-pawn, free rook
- **Comparison:** Pushing the protected passer to d6 threatens d7 and ties Black down, while Nf3+ is harmless (gxf3). Bd4 is also good and pressures e5; Kf2 invites piece checks, and b3 drops material.
- **Threat agent on d6:** Bxc5 — trade off Nc5, then Nd7/Rd8 vs the d6 pawn
- *Decision:* threat Kf2?Bxc5 (+0->-100); hybrid

### 40. Nb7  —  Stockfish +4.9 after the move, loss 0 cp (best: Nb7)
- **Thinking:** Pd6 is attacked by Rd8 and undefended, and Black's Ne5 is loose. Nb7 guards d6 and hits the rook, while Bd4/Bf4 attack e5 so that Rxd6 can be met by Bxe5.
- **Candidates:** Nb7 (0.45) — defends d6, attacks Rd8; Bd4 (0.25) — hits loose Ne5, Rxd6 Bxe5; Bf4 (0.18) — attacks Ne5, counter Rxd6; Bd2 (0.12) — trade bishops, keep Nc5
- **Comparison:** Nb7 guards d6 and hits the rook, keeping the strong passer, so it is best. Bd4 simply drops the pawn, while Bf4 and Bd2 keep material level but leave the d-pawn passive and weakly supported.
- **Threat agent on Nb7:** Bxd6 — saves rook tempo, wins d6 pawn
- *Decision:* threat Bf4?Bxc5+ (+0->-170); threat Bd2?Bxc5+ (+0->-90); vetoed Bf4; hybrid

### 41. Rc8+  —  Stockfish +5.0 after the move, loss 17 cp (best: Rc7)
- **Thinking:** Nb7 hangs to Rd7, and the d6 pawn is attacked by Bb4. Rc7 challenges the rook: if ...Rxc7, dxc7 and the c-pawn looks unstoppable.
- **Candidates:** Rc7 (0.55) — offers rook trade, c-pawn queens; Rc8+ (0.2) — check, activates rook; Bf4 (0.13) — hits Ne5, counterattack; Bd4 (0.12) — hits Ne5, counterattack
- **Comparison:** Rc8+ gains a tempo with check and, per the engine, saves both the knight and d6, keeping the dangerous passer alive. Rc7 saves the knight but concedes d6, and the bishop moves leave both pieces hanging.
- **Threat agent on Rc8+:** Kh7 — king steps aside, Nb7 stays loose
- *Decision:* hybrid

### 42. Rc7  —  Stockfish +5.3 after the move, loss 0 cp (best: Rc7)
- **Thinking:** Nb7 is undefended and attacked by Rd7; d6 is attacked by Bb4. Rc7 counterattacks the rook, and after the rook trade on c7 the pawn recaptures and threatens to promote on c8.
- **Candidates:** Rc7 (0.45) — counterattacks rook; c-pawn threat; Rb8 (0.25) — defends knight, keeps d6 guarded; Bf4 (0.15) — guards d6, pressures e5; Bd4 (0.15) — hits knight, centralizes
- **Comparison:** Rc7 defends the knight and presses on the d7 rook, which only the knight holds. After Bd4 or Bf4 Rxb7 Bxe5, a strong bishop backs the d6 passer; Rb8 simply drops material.
- **Threat agent on Rc7:** Bxd6 — wins d6 pawn; Nd3/Nc4 counterplay on b2
- *Decision:* hybrid

### 43. Rxd7  —  Stockfish +6.0 after the move, loss 0 cp (best: Rxd7)
- **Thinking:** Rc7 is attacked twice (Rd7, Bd6) and undefended, and there are no checks. Rxd7 Nxd7 Nxd6 nets a piece; the other moves only save the rook or lose material.
- **Candidates:** Rxd7 (0.9) — wins piece after Nxd7 Nxd6; Nxd6 (0.04) — grabs bishop, but Rxc7 loses; Rc8 (0.03) — saves rook; Rc2 (0.03) — retreat rook
- *Decision:* vetoed Nxd6,Rc8,Rc2; only tactically sound candidate

### 44. Nxd6  —  Stockfish +6.0 after the move, loss 0 cp (best: Nxd6)
- **Thinking:** Black's Bd6 is undefended and attacked by Nb7, so Nxd6 wins a whole bishop for free; nothing of White's is under real threat. Alternatives are much weaker quiet moves.
- **Candidates:** Nxd6 (0.9) — wins undefended bishop; Bd4 (0.04) — centralize bishop, keep Bd6 attacked; Kf2 (0.03) — king activation; Bxh6 (0.03) — pawn grab tactic
- *Decision:* vetoed Bd4,Kf2,Bxh6; only tactically sound candidate

### 45. b4  —  Stockfish +6.3 after the move, loss 3 cp (best: Kh2)
- **Thinking:** Nothing is under attack right now, but Nd6, Be3 and Nd7 are all loose; Black threatens nothing. White is up a piece and should push the b-pawn and activate the king.
- **Candidates:** b4 (0.35) — advance passer, safe; Kf2 (0.25) — centralise king; Nb5 (0.2) — reroute knight, support b-pawn; Bd4 (0.2) — restrain Ne5, central bishop
- **Comparison:** White is a piece up, so the plan is to push the b-pawn and activate the king while keeping Black's knight out of c5 and e5. b4 gains space and takes c5 away, so it is the most purposeful move.
- **Threat agent on b4:** Nb6 — Nc4 next forks Be3 and Nd6
- *Decision:* hybrid

### 46. b5  —  Stockfish +6.4 after the move, loss 0 cp (best: b5)
- **Thinking:** Nothing of White's is hanging and Black has no threats; White is a piece up with a passed b-pawn. Pushing the b-pawn with piece support, or bringing the king in, should win.
- **Candidates:** b5 (0.4) — advance passer, Nd6 covers b7/c8; Bc5 (0.2) — support b-pawn advance; Kf1 (0.2) — centralize king; Bd4 (0.2) — pressure Ne5, activate bishop
- **Comparison:** White is a piece up, so the plan is simply to push the b-passer and activate the king. Nf3+ is harmless in every line because gxf3 wins the knight.
- **Threat agent on b5:** Nd7 — blockade b-pawn, cover b6/b8
- *Decision:* hybrid

### 47. b6  —  Stockfish +6.2 after the move, loss 16 cp (best: Kh1)
- **Thinking:** No hanging pieces; Black threatens nothing, so the plan is to push the passed b-pawn with piece support. After b6, Nxb6 loses the knight to Bxb6.
- **Candidates:** b6 (0.45) — advance passer, Nxb6 Bxb6; Ba7 (0.2) — controls b8, supports pawn; Kf2 (0.15) — activate king; Nc4 (0.2) — reroute knight to support b-pawn
- **Comparison:** White is a piece up, and the b-pawn, defended by Be3, can advance to b7 and tie Black's knight down. b6 makes immediate progress; the other moves only prepare.
- **Threat agent on b6:** Ne5 — knight centralizes, eyes c6/d3, Nd7 no longer needed on b8
- *Decision:* hybrid

### 48. Bxb6  —  Stockfish +6.1 after the move, loss 0 cp (best: Bxb6)
- **Thinking:** Black's Nb6 is undefended and attacked by Be3, so Bxb6 wins a full knight and leaves a trivially won B+N endgame. No black threats; alternatives are just quiet moves.
- **Candidates:** Bxb6 (0.9) — wins hanging knight; Bd4 (0.04) — centralize, keep pressure; Kf2 (0.03) — king activation; Nb5 (0.03) — reposition knight
- *Decision:* vetoed Bd4,Kf2,Nb5; only tactically sound candidate

### 49. Bd4  —  Stockfish +6.4 after the move, loss 6 cp (best: fxg6+)
- **Thinking:** Nothing hangs for either side and Black threatens only g6xf5, which Nd6 and e4 already cover. White is completely winning, so the simple fxg6+ trade or quiet king activation and piece improvement all keep control.
- **Candidates:** fxg6+ (0.35) — simplify, check; Kf2 (0.25) — activate king; Nf7 (0.2) — hits h6 pawn; Bd4 (0.2) — attack f6 pawn
- **Comparison:** White is up a whole bishop and knight, so every move wins; the question is which converts most smoothly. Bd4 hits f6 and wins a pawn, fxg6+ trades pawns towards an easy win, and Kf2 simply activates the king.
- **Threat agent on Bd4:** gxf5 — trade pawns before f6 falls
- *Decision:* hybrid

### 50. Ne8+  —  Stockfish +6.5 after the move, loss 13 cp (best: fxg6)
- **Thinking:** Nothing of White's is hanging and Black has no threats; Pf6 is pinned and the black king is overloaded guarding f6 and g6. Ne8+ forces the king away and then wins f6, since the knight and bishop both attack it.
- **Candidates:** Ne8+ (0.5) — check, then wins f6 pawn; fxg6 (0.2) — trade down, simplify; Kf2 (0.15) — activate king; e5 (0.15) — break open, attack f6
- **Comparison:** White is winning with two extra pieces, so the aim is simplifying toward promotion. Ne8+ forks f6 and wins a pawn cleanly, while the other moves just trade pawns or wait.
- **Threat agent on Ne8+:** Kf7 — king attacks loose knight, gains tempo
- *Decision:* hybrid

### 51. Nxf6  —  Stockfish +6.3 after the move, loss 36 cp (best: fxg6+)
- **Thinking:** The Ne8 is attacked by the king and must be saved. Nxf6 wins a pawn safely because Bd4 guards f6, while Nd6+ and Nc7 only save the knight.
- **Candidates:** Nxf6 (0.7) — wins pawn, knight protected by Bd4; Nd6+ (0.12) — saves knight with check; Nc7 (0.1) — retreats knight safely; Ng7 (0.08) — knight eyes e6/f5 squares
- **Comparison:** Nxf6 wins a pawn safely because Bd4 protects the knight, and after gxf5 exf5 White's extra pieces and passed pawns win easily. Nc7 saves the knight but is passive and gives up the f6 pawn.
- **Threat agent on Nxf6:** gxf5 — trade pawns; the knight is defended by Bd4, so Kxf6 is illegal
- *Decision:* vetoed Nd6+,Ng7; hybrid

### 52. exf5  —  Stockfish +8.1 after the move, loss 0 cp (best: e5)
- **Thinking:** Pf5 is undefended and exf5 wins it, while Bd4 keeps Nf6 protected so the king cannot take it. Nothing else of White's is hanging, and Black has no threats.
- **Candidates:** exf5 (0.6) — wins free pawn, simplifies; e5 (0.2) — passed pawn, keeps knight defended; Kf2 (0.1) — activate king; Be5 (0.1) — keeps knight defended, flexible
- **Comparison:** White is winning easily. exf5 removes Black's last central pawn and creates a protected passer, which simplifies the win most cleanly.
- **Threat agent on exf5:** Kf8 — king heads toward the corner; no tactics for Black
- *Decision:* hybrid

### 53. Nxh5  —  Stockfish +35.0 after the move, loss 0 cp (best: Nxh5)
- **Thinking:** Black's h5 pawn is undefended, and taking it leaves Black with no pawns and no pieces. After Nxh5 the knight is safe because the Black king on f7 cannot reach h5.
- **Candidates:** Nxh5 (0.7) — wins last pawn, trivial win; Kf2 (0.1) — activate king; Nd5 (0.08) — safe knight reposition; g3 (0.07) — restrict h-pawn; Nh7 (0.05) — keeps knight active
- **Comparison:** Nxh5 wins Black's last pawn cleanly, leaving a trivially winning ending. g3 also eventually wins h5 but is slower; Kf2 and Nd5 allow h4 and give up nothing but delay.
- **Threat agent on Nxh5:** Kf8 — only king moves left; no counterplay
- *Decision:* hybrid

### 54. f6+  —  Stockfish +38.0 after the move, loss 0 cp (best: g4)
- **Thinking:** White is up a bishop, a knight and three pawns against a bare king, and nothing of White's is attacked, so the only danger is stalemate. Push pawns with support, keep the Black king boxed in, and bring the White king up.
- **Candidates:** g4 (0.3) — advance connected passers; f6+ (0.25) — push with check, knight guards; Kf2 (0.2) — activate king; h4 (0.15) — advance pawns; Bc5+ (0.1) — drive king back
- **Comparison:** All four moves keep a trivially winning position, so the scores only reflect how efficiently each makes progress. f6+ gains space with a pawn on f6 guarded by both the bishop and the knight, while g4 supports the f-pawn and Kf2 activates the king.
- **Threat agent on f6+:** Kf7 — blockade f-pawn, eye g6
- *Decision:* hybrid

### 55. g4  —  Stockfish +39.5 after the move, loss 5 cp (best: Nf4)
- **Thinking:** No pieces are hanging, and Black only attacks the f6 pawn, which is defended twice. White is winning easily, so the plan is to bring the king up and push the kingside pawns.
- **Candidates:** g4 (0.3) — advance connected passers; Kf2 (0.25) — activate king; h4 (0.2) — push passer; Nf4 (0.25) — reposition knight, keep f6 covered
- **Comparison:** Everything wins trivially; best to advance the connected pawns while the pieces cover f6. g4 solidifies the knight and marches pawns, and king activation is close behind.
- **Threat agent on g4:** Kg6 — king eyes Nh5 (protected by g4)
- *Decision:* hybrid
