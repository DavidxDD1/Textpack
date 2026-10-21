"""Deterministic byte Huffman codec and a small, strictly validated container.

TPK1: magic(4), original size(u32), payload bits(u32), symbol count(u16),
CRC32(u32), sorted (symbol:u8, frequency:u32) entries, packed payload.
All integers are big-endian. Padding bits at the end must be zero.
"""

from collections import Counter
from dataclasses import dataclass
import heapq
import struct
import zlib

MAGIC = b"TPK1"
HEADER = struct.Struct(">4sIIHI")
ENTRY = struct.Struct(">BI")
MAX_BYTES = 8 * 1024 * 1024


class ArchiveError(ValueError):
    """The archive is invalid or exceeds the permitted output size."""


@dataclass(frozen=True, slots=True)
class Node:
    weight: int
    symbol: int | None = None
    left: "Node | None" = None
    right: "Node | None" = None


def build_tree(frequencies: dict[int, int]) -> tuple[Node | None, list[dict]]:
    """Break frequency ties by the minimum byte in each disjoint subtree."""
    heap = [(weight, symbol, Node(weight, symbol)) for symbol, weight in frequencies.items()]
    heapq.heapify(heap)
    merges = []
    while len(heap) > 1:
        wa, sa, a = heapq.heappop(heap)
        wb, sb, b = heapq.heappop(heap)
        merges.append({"left": wa, "right": wb, "sum": wa + wb})
        heapq.heappush(heap, (wa + wb, min(sa, sb), Node(wa + wb, left=a, right=b)))
    return (heap[0][2] if heap else None), merges


def codebook(root: Node | None) -> dict[int, str]:
    codes = {}
    def visit(node: Node, prefix: str) -> None:
        if node.symbol is not None:
            codes[node.symbol] = prefix or "0"
        else:
            visit(node.left, prefix + "0")
            visit(node.right, prefix + "1")
    if root is not None:
        visit(root, "")
    return codes


def compress(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise ValueError("输入超过 8 MiB 上限。")
    frequencies = dict(Counter(data))
    root, _ = build_tree(frequencies)
    codes = codebook(root)
    numeric = {symbol: (int(bits, 2), len(bits)) for symbol, bits in codes.items()}
    bit_length = sum(frequencies[symbol] * len(bits) for symbol, bits in codes.items())
    archive = bytearray(HEADER.pack(MAGIC, len(data), bit_length, len(frequencies), zlib.crc32(data)))
    for symbol in sorted(frequencies):
        archive.extend(ENTRY.pack(symbol, frequencies[symbol]))
    pending = 0
    count = 0
    for symbol in data:
        value, width = numeric[symbol]
        pending = (pending << width) | value
        count += width
        while count >= 8:
            count -= 8
            archive.append((pending >> count) & 255)
        pending &= (1 << count) - 1
    if count:
        archive.append(pending << (8 - count))
    return bytes(archive)


def decompress(archive: bytes, max_output: int = MAX_BYTES) -> bytes:
    if len(archive) < HEADER.size:
        raise ArchiveError("文件过短，缺少 TPK1 文件头。")
    magic, size, bits, symbols, checksum = HEADER.unpack_from(archive)
    if magic != MAGIC:
        raise ArchiveError("不是受支持的 TPK1 文件。")
    if size > min(max_output, MAX_BYTES):
        raise ArchiveError("声明的还原大小超过上限。")
    if symbols > 256:
        raise ArchiveError("符号数量不能超过 256。")
    offset = HEADER.size + symbols * ENTRY.size
    if len(archive) < offset:
        raise ArchiveError("频率表被截断。")
    frequencies = {}
    previous = -1
    for i in range(symbols):
        symbol, frequency = ENTRY.unpack_from(archive, HEADER.size + i * ENTRY.size)
        if symbol <= previous or frequency == 0:
            raise ArchiveError("频率表必须按字节递增，且频次为正。")
        frequencies[symbol] = frequency
        previous = symbol
    if sum(frequencies.values()) != size or (size == 0) != (symbols == 0):
        raise ArchiveError("原始大小与频率表不一致。")
    root, _ = build_tree(frequencies)
    codes = codebook(root)
    expected_bits = sum(frequencies[s] * len(code) for s, code in codes.items())
    if bits != expected_bits:
        raise ArchiveError("有效位数与频率表不一致。")
    payload = memoryview(archive)[offset:]
    if len(payload) != (bits + 7) // 8:
        raise ArchiveError("数据被截断或包含多余字节。")
    if bits % 8 and payload[-1] & ((1 << (8 - bits % 8)) - 1):
        raise ArchiveError("末尾补齐位必须为 0。")
    if root is None:
        output = b""
    elif root.symbol is not None:
        if any(payload):
            raise ArchiveError("单符号编码只能包含 0。")
        output = bytes([root.symbol]) * size
    else:
        decoded = bytearray()
        current = root
        for i in range(bits):
            bit = (payload[i // 8] >> (7 - i % 8)) & 1
            current = current.right if bit else current.left
            if current.symbol is not None:
                decoded.append(current.symbol)
                if len(decoded) > size:
                    raise ArchiveError("解码长度超过声明值。")
                current = root
        if current is not root:
            raise ArchiveError("数据结束在不完整的码字中。")
        output = bytes(decoded)
    if len(output) != size or dict(Counter(output)) != frequencies:
        raise ArchiveError("解码长度或字节频次校验失败。")
    if zlib.crc32(output) != checksum:
        raise ArchiveError("CRC32 校验失败，文件可能已损坏。")
    return output


def describe(data: bytes, archive: bytes | None = None) -> dict:
    if archive is None:
        archive = compress(data)
    frequencies = dict(Counter(data))
    root, merges = build_tree(frequencies)
    codes = codebook(root)
    bit_count = sum(frequencies[s] * len(code) for s, code in codes.items())
    metadata = HEADER.size + len(frequencies) * ENTRY.size
    entries = []
    for symbol in sorted(frequencies, key=lambda s: (-frequencies[s], s)):
        label = {10: "LF 换行", 13: "CR 回车", 9: "TAB", 32: "空格"}.get(symbol)
        if label is None:
            label = chr(symbol) if 33 <= symbol <= 126 else f"0x{symbol:02X}"
        entries.append({"byte": symbol, "label": label, "frequency": frequencies[symbol], "code": codes[symbol], "length": len(codes[symbol])})
    return {
        "original_bytes": len(data), "archive_bytes": len(archive),
        "metadata_bytes": metadata, "payload_bytes": len(archive) - metadata,
        "payload_bits": bit_count, "unique_bytes": len(frequencies),
        "saving_percent": round((1 - len(archive) / len(data)) * 100, 2) if data else None,
        "average_bits": round(bit_count / len(data), 4) if data else 0,
        "crc32": f"{zlib.crc32(data):08x}", "codebook": entries, "merges": merges,
    }
