import os

# Keep the suite offline and deterministic: no Lichess tablebase requests from tests.
os.environ.setdefault("CLAUDE_CHESS_TB_ONLINE", "0")

# Never write test games into the real dataset (db/games.sqlite is tracked research data).
import tempfile  # noqa: E402

os.environ["CLAUDE_CHESS_DB"] = os.path.join(tempfile.mkdtemp(prefix="cc_testdb_"), "games.sqlite")
