"""The human concept vocabulary: what a coach would name, linked to detectors and puzzle themes.

The teacher (Claude) tags each explanation with 1-3 of these ids. Each id lists the
detector keys (`concepts.KEYS`, without the us./them. prefix) and Lichess puzzle themes it
corresponds to, so tags can be cross-checked against the board and the puzzle labels.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Human:
    id: str
    name: str
    gloss: str
    detectors: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()


VOCAB: tuple[Human, ...] = (
    # tactics
    Human("win_material", "Winning material", "the line simply nets material", ("material", "hanging", "hanging_value"),
          ("advantage", "crushing", "hangingPiece")),
    Human("hanging_piece", "Loose / hanging piece", "a piece is undefended or insufficiently defended",
          ("hanging", "hanging_value"), ("hangingPiece",)),
    Human("fork", "Fork", "one piece attacks two targets", ("forks",), ("fork",)),
    Human("pin", "Pin / skewer", "a piece can't move without exposing something bigger", ("pins",),
          ("pin", "skewer")),
    Human("discovered_attack", "Discovered attack", "moving one piece unmasks another", ("discovered",),
          ("discoveredAttack", "doubleCheck")),
    Human("overloaded_defender", "Overloaded defender / deflection", "a defender has too many jobs",
          ("overloaded_enemy",), ("deflection", "attraction", "capturingDefender", "interference")),
    Human("trapped_piece", "Trapped piece", "a piece has no safe squares", ("trapped_enemy",), ("trappedPiece",)),
    Human("back_rank", "Back-rank weakness", "the king is boxed in on its first rank", ("back_rank_weak",),
          ("backRankMate",)),
    Human("mating_attack", "Mating attack", "forcing play against the king that ends in or threatens mate",
          ("mate_threat", "king_zone_attacks", "king_attackers"),
          ("mate", "mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5", "smotheredMate", "anastasiaMate",
           "arabianMate", "bodenMate", "doubleBishopMate", "dovetailMate", "hookMate")),
    Human("sacrifice", "Sacrifice", "material is given up for something bigger", (), ("sacrifice",)),
    Human("zwischenzug", "In-between move", "an unexpected intermediate move before the obvious one", (),
          ("intermezzo",)),
    Human("defence", "Defence / parrying a threat", "the move meets a concrete threat", (),
          ("defensiveMove",)),
    # king
    Human("king_safety", "King safety", "pawn cover, open lines and attackers around a king",
          ("king_shield", "king_open_files", "king_zone_attacks", "king_attackers", "king_escape", "castled",
           "king_center"), ("exposedKing", "kingsideAttack", "queensideAttack")),
    Human("king_activity", "Active king", "in the endgame the king is a fighting piece", ("king_activity",)),
    # pawns
    Human("passed_pawn", "Passed pawn", "a pawn no enemy pawn can stop; push it or blockade it",
          ("passed_pawns", "passer_rank", "protected_passers", "connected_passers"),
          ("advancedPawn", "promotion", "underPromotion")),
    Human("pawn_weakness", "Pawn weaknesses", "isolated, doubled or backward pawns as targets",
          ("isolated_pawns", "doubled_pawns", "backward_pawns", "pawn_islands")),
    Human("pawn_majority", "Pawn majority", "extra pawns on one wing that can make a passer",
          ("majority_qs", "majority_ks")),
    Human("pawn_break", "Pawn break", "a pawn advance that opens lines or attacks the chain"),
    Human("space", "Space", "pawns that cramp the opponent and give our pieces room", ("space",)),
    Human("iqp", "Isolated queen pawn", "dynamic d-pawn: attack for one side, target for the other", ("iqp",)),
    # pieces
    Human("piece_activity", "Piece activity", "better squares, more mobility, coordination",
          ("mobility", "centralization")),
    Human("outpost", "Outpost", "a protected square no enemy pawn can attack", ("outposts",)),
    Human("open_file", "Open file / rook activity", "rooks on open files or the seventh rank",
          ("rook_open_file", "rook_semi_open", "rook_seventh", "doubled_rooks")),
    Human("bad_bishop", "Good vs bad bishop", "a bishop hemmed in by its own pawns", ("bad_bishop",)),
    Human("bishop_pair", "Bishop pair", "two bishops in an open position", ("bishop_pair",)),
    Human("development", "Development / tempo", "getting pieces out and castling before the fight",
          ("undeveloped",)),
    # strategy
    Human("simplify", "Trade when ahead", "exchanges that bring a winning advantage closer", ("phase",)),
    Human("avoid_trades", "Avoid trades when worse / attacking", "keep pieces on to keep chances"),
    Human("prophylaxis", "Prophylaxis", "stopping the opponent's plan before it starts"),
    Human("initiative", "Initiative", "forcing moves that keep the opponent reacting",
          ("checks_available",)),
    Human("endgame_technique", "Endgame technique", "known winning/drawing methods (opposition, Lucena...)",
          (), ("endgame", "pawnEndgame", "rookEndgame", "queenEndgame", "bishopEndgame", "knightEndgame",
               "queenRookEndgame", "zugzwang")),
    Human("counterplay", "Counterplay", "creating threats elsewhere instead of passive defence"),
)
IDS: tuple[str, ...] = tuple(h.id for h in VOCAB)
BY_ID = {h.id: h for h in VOCAB}


def render_vocab() -> str:
    return "\n".join(f"- {h.id}: {h.name} — {h.gloss}" for h in VOCAB)
