"""Application operations shared by CLI and local web interface."""

from .codec import compress, decompress, describe
from .kmp import find_all, match_rows, prefix_function


def analyze(text: str, pattern: str) -> dict:
    data = text.encode("utf-8")
    archive = compress(data)
    positions = find_all(text, pattern)
    return {
        "characters": len(text), "pattern_characters": len(pattern),
        "match_count": len(positions), "positions": positions[:200],
        "positions_truncated": len(positions) > 200,
        "matches": match_rows(text, positions, len(pattern)),
        "prefix": prefix_function(pattern)[:100],
        "prefix_truncated": len(pattern) > 100,
        "compression": describe(data, archive),
        "roundtrip_ok": decompress(archive) == data,
    }
