import chess
import numpy as np
import torch

from claude_chess.explainer import sae as S


def test_topk_sae_keeps_exactly_k_active_and_unit_decoder():
    sae = S.TopKSAE(m=16, n=64, k=4)
    z = sae.encode(torch.randn(10, 16))
    assert ((z > 0).sum(-1) <= 4).all()
    assert torch.allclose(sae.dec.norm(dim=1), torch.ones(64), atol=1e-5)


def test_corr_matrix_finds_the_matching_label():
    rng = np.random.default_rng(0)
    labels = rng.normal(size=(500, 3))
    acts = np.stack([labels[:, 2] * 2 + 0.01 * rng.normal(size=500), rng.normal(size=500)], axis=1)
    feats = S.analyse(acts, labels, ["a", "b", "c"])
    assert feats[0]["match"][0][0] == "c" and feats[0]["max_abs_corr"] > 0.99


def test_line_end_keeps_side_to_move():
    fen = chess.STARTING_FEN
    b = S.line_end(fen, "e2e4 e7e5 g1f3", plies=6)  # odd line is cut to an even length
    assert b.turn == chess.WHITE and b.fullmove_number == 2
