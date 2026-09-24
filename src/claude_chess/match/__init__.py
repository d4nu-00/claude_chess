"""Match layer: baselines, game/match runner, post-game analysis."""

from claude_chess.match.baselines import RandomPlayer, StockfishPlayer
from claude_chess.match.openings import OPENINGS
from claude_chess.match.runner import GameRecord, play_game, play_match

__all__ = ["RandomPlayer", "StockfishPlayer", "OPENINGS", "GameRecord", "play_game", "play_match"]
