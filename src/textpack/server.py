"""Small loopback-only HTTP adapter; domain algorithms live in other modules."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .codec import compress, decompress, describe
from .service import analyze

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
MAX_TEXT = 1024 * 1024
MAX_BODY = 2 * MAX_TEXT + 4096


class RequestError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "TextPack/1.0"

    def send_data(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, obj: dict, status: int = 200) -> None:
        self.send_data(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def check_local(self) -> None:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            raise RequestError("仅允许本机访问。", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in hosts}:
            raise RequestError("不接受来自其他站点的请求。", 403)

    def do_GET(self) -> None:
        try:
            self.check_local()
            path = urlsplit(self.path).path
            if path == "/api/health":
                self.send_json({"ok": True, "version": __version__})
            elif path == "/api/sample":
                self.send_json({"text": (ROOT / "examples" / "study_notes.txt").read_text(encoding="utf-8"), "pattern": "算法"})
            else:
                files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
                if path not in files:
                    raise RequestError("页面不存在。", 404)
                name, mime = files[path]
                self.send_data((WEB / name).read_bytes(), mime)
        except RequestError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except OSError:
            self.send_json({"error": "本地资源缺失，请保留完整项目目录。"}, 500)

    def read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError as exc:
            raise RequestError("无效的请求长度。") from exc
        if length < 0 or length > MAX_BODY:
            raise RequestError("请求大小超出限制。", 413)
        self.connection.settimeout(10)
        data = self.rfile.read(length)
        if len(data) != length:
            raise RequestError("请求数据不完整。")
        return data

    def do_POST(self) -> None:
        try:
            self.check_local()
            path = urlsplit(self.path).path
            if path not in {"/api/analyze", "/api/compress", "/api/decompress"}:
                raise RequestError("接口不存在。", 404)
            body = self.read_body()
            if path == "/api/decompress":
                raw = decompress(body, max_output=MAX_TEXT)
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise RequestError("文件已还原，但不是 UTF-8 文本；请使用命令行还原二进制文件。") from exc
                self.send_json({"text": text, "compression": describe(raw, body), "verified": True})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise RequestError("请求必须使用 JSON 格式。", 415)
            obj = json.loads(body)
            if not isinstance(obj, dict) or not isinstance(obj.get("text"), str):
                raise RequestError("text 必须是字符串。")
            text = obj["text"]
            raw = text.encode("utf-8")
            if len(raw) > MAX_TEXT:
                raise RequestError("界面最多处理 1 MiB 的 UTF-8 文本。", 413)
            if path == "/api/compress":
                self.send_data(compress(raw), "application/octet-stream")
                return
            pattern = obj.get("pattern", "")
            if not isinstance(pattern, str) or len(pattern.encode("utf-8")) > 16384:
                raise RequestError("模式串必须是字符串，且不超过 16 KiB。")
            self.send_json(analyze(text, pattern))
        except RequestError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except (ValueError, UnicodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except (OSError, TimeoutError):
            self.send_json({"error": "请求读取失败，请重试。"}, 400)


def make_server(port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def run(port: int = 8765) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("端口须在 1 到 65535 之间。")
    with make_server(port) as server:
        print(f"TextPack {__version__}: http://127.0.0.1:{port}", flush=True)
        print("按 Ctrl+C 结束。文本仅在本机内存中处理。", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
