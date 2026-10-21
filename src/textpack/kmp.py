"""KMP over Python Unicode code points; matches may overlap."""


def prefix_function(pattern: str) -> list[int]:
    """pi[i] is the longest proper border length of pattern[:i + 1]."""
    pi = [0] * len(pattern)
    for i in range(1, len(pattern)):
        j = pi[i - 1]
        while j and pattern[i] != pattern[j]:
            j = pi[j - 1]
        if pattern[i] == pattern[j]:
            j += 1
        pi[i] = j
    return pi


def find_all(text: str, pattern: str) -> list[int]:
    """Return zero-based code-point offsets. Empty pattern returns []."""
    if not pattern:
        return []
    pi = prefix_function(pattern)
    positions = []
    j = 0
    for i, char in enumerate(text):
        while j and char != pattern[j]:
            j = pi[j - 1]
        if char == pattern[j]:
            j += 1
        if j == len(pattern):
            positions.append(i - len(pattern) + 1)
            # Keep the longest border, otherwise overlapping matches are lost.
            j = pi[j - 1]
    return positions


def match_rows(text: str, positions: list[int], width: int, limit: int = 200) -> list[dict]:
    """Add 1-based line/column numbers in a single forward scan."""
    rows = []
    cursor = 0
    line = 1
    line_start = 0
    for pos in positions[:limit]:
        while cursor < pos:
            if text[cursor] == "\n":
                line += 1
                line_start = cursor + 1
            cursor += 1
        rows.append({
            "offset": pos, "line": line, "column": pos - line_start + 1,
            "context": text[max(0, pos - 14):min(len(text), pos + width + 24)],
        })
    return rows
