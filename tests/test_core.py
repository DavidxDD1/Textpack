from collections import Counter
from functools import lru_cache
from itertools import product, combinations
from pathlib import Path
import random
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from textpack.codec import ArchiveError, HEADER, ENTRY, MAGIC, MAX_BYTES, build_tree, codebook, compress, decompress, describe
from textpack.kmp import find_all, match_rows, prefix_function
from textpack.service import analyze


def naive_matches(text, pattern):
    if not pattern:
        return []
    return [i for i in range(len(text) - len(pattern) + 1) if text[i:i + len(pattern)] == pattern]


def words(max_length):
    return ["".join(chars) for n in range(max_length + 1) for chars in product("ab", repeat=n)]


@lru_cache(None)
def optimal_merge_cost(weights):
    """Exhaust all choices of two trees: independent of the greedy rule."""
    if len(weights) <= 1:
        return 0
    return min(weights[i] + weights[j] + optimal_merge_cost(tuple(sorted(
        [weights[k] for k in range(len(weights)) if k not in (i, j)] + [weights[i] + weights[j]]
    ))) for i, j in combinations(range(len(weights)), 2))


class KMPTests(unittest.TestCase):
    def test_known_overlaps(self):
        self.assertEqual(find_all("ababab", "abab"), [0, 2])
        self.assertEqual(find_all("aaaaa", "aaa"), [0, 1, 2])

    def test_empty_and_long_pattern(self):
        for text, pattern in [("", ""), ("abc", ""), ("", "a"), ("a", "aa")]:
            self.assertEqual(find_all(text, pattern), [])

    def test_unicode_offsets(self):
        self.assertEqual(find_all("🙂算法🙂算法", "🙂算法"), [0, 3])
        self.assertEqual(find_all("é e\u0301", "é"), [0])

    def test_prefix(self):
        self.assertEqual(prefix_function("ababaca"), [0, 0, 1, 2, 3, 0, 1])
        self.assertEqual(prefix_function(""), [])

    def test_exhaustive_against_naive(self):
        for text in words(7):
            for pattern in words(4):
                self.assertEqual(find_all(text, pattern), naive_matches(text, pattern), (text, pattern))

    def test_prefix_against_definition(self):
        for text in words(7):
            expected = [max([0] + [k for k in range(1, i + 1) if text[:k] == text[i + 1 - k:i + 1]]) for i in range(len(text))]
            self.assertEqual(prefix_function(text), expected)

    def test_line_columns(self):
        rows = match_rows("🙂a\na\r\na", [1, 3, 6], 1)
        self.assertEqual([(r["line"], r["column"]) for r in rows], [(1, 2), (2, 1), (3, 1)])


class CodecTests(unittest.TestCase):
    def test_empty(self):
        archive = compress(b"")
        self.assertEqual(len(archive), 18)
        self.assertEqual(decompress(archive), b"")
        self.assertIsNone(describe(b"")["saving_percent"])

    def test_single_byte(self):
        for size in [1, 7, 8, 9, 5000]:
            raw = b"x" * size
            self.assertEqual(decompress(compress(raw)), raw)
            self.assertEqual(describe(raw)["payload_bits"], size)

    def test_all_bytes(self):
        raw = bytes(range(256))
        self.assertEqual(decompress(compress(raw)), raw)
        self.assertEqual(len(compress(raw)), 1554)
        self.assertEqual(describe(raw)["average_bits"], 8)

    def test_known_banana_encoding(self):
        raw = b"banana"
        tree, _ = build_tree(dict(Counter(raw)))
        self.assertEqual(codebook(tree), {97: "0", 98: "10", 110: "11"})
        self.assertEqual(compress(raw)[-2:], b"\x9b\x00")
        self.assertEqual(len(compress(raw)), 35)

    def test_crc_known_vector(self):
        self.assertEqual(describe(b"123456789")["crc32"], "cbf43926")

    def test_deterministic(self):
        data = b"dcba" * 64
        self.assertEqual(compress(data), compress(data))
        a, _ = build_tree({3: 1, 2: 1, 1: 1, 0: 1})
        b, _ = build_tree({0: 1, 1: 1, 2: 1, 3: 1})
        self.assertEqual(codebook(a), codebook(b))

    def test_random_roundtrips(self):
        rng = random.Random(2300013109)
        for _ in range(180):
            alphabet = rng.sample(range(256), rng.randint(1, 256))
            raw = bytes(rng.choice(alphabet) for _ in range(rng.randrange(2500)))
            self.assertEqual(decompress(compress(raw)), raw)

    def test_unicode_roundtrip(self):
        raw = "数据结构\r\n算法🙂\u0000e\u0301".encode("utf-8")
        self.assertEqual(decompress(compress(raw)), raw)

    def test_prefix_free(self):
        codes = list(codebook(build_tree(dict(Counter(bytes(range(256)) + b"a" * 300)))[0]).values())
        self.assertTrue(all(not a.startswith(b) for a in codes for b in codes if a != b))

    def test_optimality_against_exhaustive_merges(self):
        rng = random.Random(2026)
        for _ in range(40):
            weights = tuple(sorted(rng.randint(1, 10) for _ in range(rng.randint(2, 6))))
            root, merges = build_tree(dict(enumerate(weights)))
            cost = sum(weights[s] * len(c) for s, c in codebook(root).items())
            self.assertEqual(cost, optimal_merge_cost(weights))
            self.assertEqual(cost, sum(m["sum"] for m in merges))

    def test_true_total_size(self):
        result = describe(b"abc")
        self.assertLess(result["saving_percent"], 0)
        self.assertEqual(result["archive_bytes"], result["metadata_bytes"] + result["payload_bytes"])

    def test_all_truncation_points(self):
        archive = compress(b"hello world" * 3)
        for cut in range(len(archive)):
            with self.assertRaises(ArchiveError, msg=str(cut)):
                decompress(archive[:cut])

    def test_wrong_magic_and_extra_bytes(self):
        for value in [b"ZIP!" + compress(b"test")[4:], compress(b"test") + b"\x00"]:
            with self.assertRaises(ArchiveError):
                decompress(value)

    def test_padding(self):
        archive = bytearray(compress(b"xxx"))
        archive[-1] |= 1
        with self.assertRaisesRegex(ArchiveError, "补齐"):
            decompress(archive)

    def test_invalid_single_symbol_bit(self):
        archive = bytearray(compress(b"xxxxxxxx"))
        archive[-1] = 128
        with self.assertRaisesRegex(ArchiveError, "单符号"):
            decompress(archive)

    def test_crc_catches_reordering(self):
        archive = bytearray(compress(b"ABAB"))
        archive[-1] ^= 0b11000000
        with self.assertRaisesRegex(ArchiveError, "CRC32"):
            decompress(archive)

    def test_frequency_table_validation(self):
        archive = bytearray(compress(b"AB"))
        for change in [lambda a: a.__setitem__(23, 65), lambda a: a.__setitem__(slice(19, 23), b"\0\0\0\0")]:
            broken = archive.copy()
            change(broken)
            with self.assertRaises(ArchiveError):
                decompress(broken)

    def test_header_limits(self):
        for header in [HEADER.pack(MAGIC, MAX_BYTES + 1, 0, 0, 0), HEADER.pack(MAGIC, 0, 0, 257, 0), HEADER.pack(MAGIC, 1, 0, 0, 0)]:
            with self.assertRaises(ArchiveError):
                decompress(header)
        with self.assertRaisesRegex(ArchiveError, "超过上限"):
            decompress(compress(b"1234"), max_output=3)

    def test_bit_length_mismatch(self):
        archive = bytearray(compress(b"abc"))
        archive[8:12] = struct.pack(">I", 999)
        with self.assertRaisesRegex(ArchiveError, "有效位数"):
            decompress(archive)


class ServiceTests(unittest.TestCase):
    def test_pipeline_and_limit(self):
        result = analyze("a" * 300, "aa")
        self.assertEqual(result["match_count"], 299)
        self.assertEqual(len(result["positions"]), 200)
        self.assertTrue(result["positions_truncated"])
        self.assertTrue(result["roundtrip_ok"])

    def test_empty_pipeline(self):
        result = analyze("", "")
        self.assertEqual(result["match_count"], 0)
        self.assertTrue(result["roundtrip_ok"])


if __name__ == "__main__":
    unittest.main()
