import os

# Keep the suite offline and deterministic: no Lichess tablebase requests from tests.
os.environ.setdefault("CLAUDE_CHESS_TB_ONLINE", "0")
