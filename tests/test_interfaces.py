from contextlib import redirect_stdout, redirect_stderr
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from textpack.cli import main
from textpack.codec import compress
from textpack.server import make_server


class CLITests(unittest.TestCase):
    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_roundtrip_files(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b, c = [Path(folder) / name for name in ["input.bin", "packed.tpk", "restored.bin"]]
            a.write_bytes(bytes(range(256)) * 4)
            self.assertEqual(self.run_cli(["compress", str(a), str(b)])[0], 0)
            self.assertEqual(self.run_cli(["decompress", str(b), str(c)])[0], 0)
            self.assertEqual(a.read_bytes(), c.read_bytes())

    def test_no_implicit_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a", Path(folder) / "b"
            a.write_bytes(b"hello"); b.write_bytes(b"keep")
            self.assertEqual(self.run_cli(["compress", str(a), str(b)])[0], 2)
            self.assertEqual(b.read_bytes(), b"keep")
            self.assertEqual(self.run_cli(["compress", str(a), str(a), "--force"])[0], 2)
            self.assertEqual(a.read_bytes(), b"hello")

    def test_search_and_analyze(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "text.txt"
            path.write_text("ababab", encoding="utf-8")
            code, output, _ = self.run_cli(["search", str(path), "abab"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["positions"], [0, 2])
            self.assertTrue(json.loads(self.run_cli(["analyze", str(path)])[1])["roundtrip_ok"])

    def test_missing_and_non_utf8(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.txt"
            self.assertEqual(self.run_cli(["search", str(path), "x"])[0], 2)
            path.write_bytes(b"\xff")
            self.assertEqual(self.run_cli(["search", str(path), "x"])[0], 2)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request("GET" if body is None else "POST", path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def post_json(self, path, data):
        return self.request(path, json.dumps(data).encode(), {"Content-Type": "application/json"})

    def test_static_and_health(self):
        for path in ["/", "/style.css", "/app.js", "/api/health", "/api/sample"]:
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request("/../main.py")[0], 404)

    def test_analyze(self):
        code, body = self.post_json("/api/analyze", {"text": "🙂a🙂a", "pattern": "🙂a"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["positions"], [0, 2])

    def test_archive_roundtrip(self):
        code, archive = self.post_json("/api/compress", {"text": "你好\r\n🙂"})
        self.assertEqual(code, 200)
        code, raw = self.request("/api/decompress", archive)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["text"], "你好\r\n🙂")

    def test_reject_invalid_and_binary(self):
        for archive in [b"bad", compress(b"\xff")]:
            code, _ = self.request("/api/decompress", archive)
            self.assertEqual(code, 400)
        self.assertEqual(self.post_json("/api/analyze", {"text": 1})[0], 400)
        self.assertEqual(self.post_json("/api/analyze", {"text": "a", "pattern": []})[0], 400)
        self.assertEqual(self.request("/api/analyze", b"{", {"Content-Type": "application/json"})[0], 400)

    def test_limits(self):
        self.assertEqual(self.post_json("/api/analyze", {"text": "a" * (1024 * 1024 + 1)})[0], 413)
        self.assertEqual(self.post_json("/api/analyze", {"text": "a", "pattern": "a" * 16385})[0], 400)

    def test_origin_and_host(self):
        self.assertEqual(self.request("/", headers={"Host": "other.example"})[0], 403)
        self.assertEqual(self.request("/api/analyze", b"{}", {"Origin": "https://other.example", "Content-Type": "application/json"})[0], 403)


if __name__ == "__main__":
    unittest.main()
