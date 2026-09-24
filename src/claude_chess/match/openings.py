"""Small set of balanced opening starts (SAN), 4-8 plies, used to vary games."""

OPENINGS: dict[str, list[str]] = {
    "Ruy Lopez": ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"],
    "Italian": ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"],
    "Sicilian Najdorf": ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6"],
    "French": ["e4", "e6", "d4", "d5", "Nc3", "Nf6"],
    "Caro-Kann": ["e4", "c6", "d4", "d5", "Nc3", "dxe4", "Nxe4", "Bf5"],
    "QGD": ["d4", "d5", "c4", "e6", "Nc3", "Nf6"],
    "King's Indian": ["d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6"],
    "English": ["c4", "e5", "Nc3", "Nf6", "Nf3", "Nc6"],
}
