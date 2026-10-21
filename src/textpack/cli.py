"""Command-line entry points; no implicit file overwrite."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .codec import MAX_BYTES, compress, decompress, describe
from .kmp import find_all
from .service import analyze


def read_limited(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("输入文件超过大小限制。")
    return data


def write_output(path: Path, data: bytes, source: Path, force: bool) -> None:
    if path.resolve() == source.resolve():
        raise ValueError("输入和输出不能是同一个文件。")
    with path.open("wb" if force else "xb") as stream:
        stream.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TextPack: KMP 检索与 Huffman 压缩工具")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="启动本地界面（仅监听 127.0.0.1）")
    serve.add_argument("--port", type=int, default=8765)
    for name in ("compress", "decompress"):
        sub = commands.add_parser(name)
        sub.add_argument("input", type=Path)
        sub.add_argument("output", type=Path)
        sub.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")
    search = commands.add_parser("search")
    search.add_argument("input", type=Path)
    search.add_argument("pattern")
    inspect = commands.add_parser("analyze")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--pattern", default="")
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "serve"):
            from .server import run
            run(getattr(args, "port", 8765))
        elif args.command in ("compress", "decompress"):
            limit = MAX_BYTES if args.command == "compress" else MAX_BYTES * 2 + 4096
            data = read_limited(args.input, limit)
            output = compress(data) if args.command == "compress" else decompress(data)
            write_output(args.output, output, args.input, args.force)
            result = {"operation": args.command, "input_bytes": len(data), "output_bytes": len(output), "output": str(args.output)}
            if args.command == "compress":
                stats = describe(data, output)
                result["saving_percent"] = stats["saving_percent"]
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            text = read_limited(args.input, MAX_BYTES).decode("utf-8")
            if args.command == "search":
                positions = find_all(text, args.pattern)
                result = {"count": len(positions), "positions": positions, "offset_unit": "Unicode code point, zero based"}
            else:
                result = analyze(text, args.pattern)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

