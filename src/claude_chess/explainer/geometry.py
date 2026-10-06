"""Geometry fact checker: piece references and attack/defence claims in explanation text.

The v1 student's errors were almost all geometry ("Rd8 guards f6", "the c1 bishop" when there is
none, "the d5 pawn attacks the queen"). The move/material verifier in teacher.py can't see these.
This module extracts two kinds of claims and checks them on real boards:

- piece references: "the c4 knight", "knight on c4", "c4-knight", "Nc4" (as a piece, not a move);
- relations: "<piece ref> attacks|hits|guards|defends|protects|covers|eyes|pins <square|piece ref>".

A claim passes if it holds in the root position or in any of the first `plies` positions of the
best/alternative lines (explanations talk about "after the move" as often as "now"). Lenient on
purpose: it should only fire on claims that are false everywhere nearby.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chess

PIECE_WORDS = {"king": chess.KING, "queen": chess.QUEEN, "rook": chess.ROOK, "bishop": chess.BISHOP,
               "knight": chess.KNIGHT, "pawn": chess.PAWN}
LETTER = {"K": chess.KING, "Q": chess.QUEEN, "R": chess.ROOK, "B": chess.BISHOP, "N": chess.KNIGHT}
SQ = r"[a-h][1-8]"
PW = r"(king|queen|rook|bishop|knight|pawn)s?"
VERBS = r"(attacks?|attacking|hits?|hitting|guards?|guarding|defends?|defending|protects?|protecting|covers?|" \
        r"covering|eyes|eyeing|targets?|targeting|pins?|pinning|controls?|controlling)"

# a reference to a piece standing on a square, in the forms club-player prose uses
_REF = rf"(?:(?:the\s+)?({SQ})[-\s]{PW}|{PW}\s+on\s+({SQ})|\b([KQRBN])({SQ})\b)"
_REF_RE = re.compile(_REF, re.I)
_CLAIM_RE = re.compile(rf"{_REF}\s+(?:now\s+|also\s+|then\s+|still\s+)?{VERBS}\s+(?:the\s+)?(?:{_REF}|({SQ}))", re.I)


@dataclass
class Ref:
    piece: int
    square: int
    text: str


def _ref_from(groups: tuple, off: int = 0) -> Ref | None:
    g = groups[off:off + 6]
    sq1, w1, w2, sq2, letter, sq3 = g
    if sq1 and w1:
        return Ref(PIECE_WORDS[w1.lower()], chess.parse_square(sq1.lower()), f"{sq1} {w1}")
    if w2 and sq2:
        return Ref(PIECE_WORDS[w2.lower()], chess.parse_square(sq2.lower()), f"{w2} on {sq2}")
    if letter and sq3 and letter in LETTER:  # case-sensitive: "Bd4" is a bishop, "bd4" is nothing
        return Ref(LETTER[letter], chess.parse_square(sq3), f"{letter}{sq3}")
    return None


def boards_near(fen: str, lines: list[list[str]], plies: int = 2) -> list[chess.Board]:
    root = chess.Board(fen)
    out = [root.copy(stack=False)]
    for line in lines:
        b = root.copy(stack=False)
        for u in line[:plies]:
            mv = chess.Move.from_uci(u)
            if not b.is_legal(mv):
                break
            b.push(mv)
            out.append(b.copy(stack=False))
    return out


def _exists(ref: Ref, boards: list[chess.Board]) -> bool:
    return any(b.piece_type_at(ref.square) == ref.piece for b in boards)


def _relation_holds(src: Ref, target_sq: int, boards: list[chess.Board]) -> bool:
    for b in boards:
        if b.piece_type_at(src.square) != src.piece:
            continue
        if target_sq in b.attacks(src.square):
            return True
        # x-ray / battery: a slider "attacks" through one piece of either colour (pins, skewers)
        if src.piece in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            ray = chess.ray(src.square, target_sq)
            between = chess.SquareSet(chess.between(src.square, target_sq))
            if ray and len(between & chess.SquareSet(b.occupied)) <= 1:
                fr, ff = chess.square_rank(src.square), chess.square_file(src.square)
                tr, tf = chess.square_rank(target_sq), chess.square_file(target_sq)
                straight = fr == tr or ff == tf
                if src.piece == chess.QUEEN or (src.piece == chess.ROOK) == straight:
                    return True
    return False


def check(text: str, fen: str, lines: list[list[str]], plies: int = 4) -> dict:
    """Returns {"refs": n, "claims": n, "bad_refs": [...], "bad_claims": [...], "ok": bool}."""
    boards = boards_near(fen, lines, plies)
    bad_refs, bad_claims = [], []
    refs = claims = 0
    for m in _REF_RE.finditer(text):
        ref = _ref_from(m.groups())
        # bare SAN ("Re8") is usually a move, often a later or hypothetical one: only prose
        # references ("the e8 rook", "rook on e8") are checked as claims about the board
        if ref is None or (ref.text[0].isupper() and len(ref.text) == 3):
            continue
        refs += 1
        if not _exists(ref, boards):
            bad_refs.append(ref.text)
    for m in _CLAIM_RE.finditer(text):
        src = _ref_from(m.groups(), 0)
        verb = m.group(7)
        tgt_ref = _ref_from(m.groups(), 7)
        tgt_sq = tgt_ref.square if tgt_ref else (chess.parse_square(m.group(14).lower()) if m.group(14) else None)
        if src is None or tgt_sq is None or not verb:
            continue
        claims += 1
        if not _relation_holds(src, tgt_sq, boards):
            bad_claims.append(m.group(0))
    return {"refs": refs, "claims": claims, "bad_refs": sorted(set(bad_refs)), "bad_claims": bad_claims,
            "ok": not bad_refs and not bad_claims}
