"""本機／教室區網版練習站。功能比 GitHub Pages 版多三項：

1. robots.txt 位於網域根目錄（符合規範）。
2. 速率限制：同一 IP 短時間超過 --burst 個請求、且持續超過每秒 --rate 個，就回 429 與 Retry-After。
3. 會員專區與會員 API 由伺服器檢查 cookie，未登入回 401／導回登入頁。
另外提供 ETag／Last-Modified，可練習條件式請求（304 Not Modified）。

用法：
    python server.py                      # http://127.0.0.1:8000
    python server.py --host 0.0.0.0       # 教室區網，學員連老師電腦
只用 Python 標準函式庫。啟動前會自動以 base=/ 重建 dist/。
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import os
import pathlib
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent
DIST = ROOT / "dist-local"
SESSION_COOKIE = "pg_session=demo-session-token"
PROTECTED_PAGES = ("/v1/members/index.html", "/v1/members/")
PROTECTED_API = "/v1/api/members/"


class RateLimiter:
    """Token bucket：瀏覽器開一頁會瞬間發出約 10 個請求（HTML、CSS、JS、API），
    所以容許短暫爆量（burst），但持續快速請求會被擋下。"""

    def __init__(self, rate: float, burst: int):
        self.rate, self.burst = rate, burst
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, ip: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(ip, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.buckets[ip] = (tokens, now)
                return False, max(1, int((1 - tokens) / self.rate + 0.999))
            self.buckets[ip] = (tokens - 1, now)
            return True, 0


class Handler(http.server.SimpleHTTPRequestHandler):
    limiter: RateLimiter
    quiet: bool = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    # ---- 共用
    def _path(self) -> str:
        return self.path.split("?", 1)[0].split("#", 1)[0]

    def _has_session(self) -> bool:
        cookies = self.headers.get("Cookie", "")
        return any(c.strip() == SESSION_COOKIE for c in cookies.split(";"))

    def _send_text(self, code: int, text: str, extra: dict[str, str] | None = None) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _guard(self) -> bool:
        """回傳 True 代表已回應（被擋下）。"""
        ok, retry = self.limiter.allow(self.client_address[0])
        if not ok:
            self._send_text(429, "429 Too Many Requests：請放慢速度（每秒最多 1～2 個請求）。\n",
                            {"Retry-After": str(retry)})
            return True
        path = self._path()
        if path.startswith(PROTECTED_API) and not self._has_session():
            self._send_text(401, "401 Unauthorized：請先登入會員。\n")
            return True
        if path in PROTECTED_PAGES and not self._has_session():
            self.send_response(302)
            self.send_header("Location", "/v1/members/login.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        if path.startswith(("/v1/admin/", "/v2/admin/")):
            ua = self.headers.get("User-Agent", "-")
            sys.stderr.write(f"[robots] {self.client_address[0]} 抓了 Disallow 路徑 {path}（UA: {ua}）\n")
        return False

    # ---- 條件式請求
    def send_head(self):
        path = pathlib.Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / "index.html"
        if path.is_file():
            st = path.stat()
            etag = '"' + hashlib.sha1(path.read_bytes()).hexdigest()[:16] + '"'
            self._etag = etag
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return None
        else:
            self._etag = None
        return super().send_head()

    def end_headers(self):
        etag = getattr(self, "_etag", None)
        if etag and not self._headers_buffer_has(b"ETag"):
            self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _headers_buffer_has(self, name: bytes) -> bool:
        return any(line.lower().startswith(name.lower() + b":") for line in getattr(self, "_headers_buffer", []))

    def do_GET(self):
        self._etag = None
        if self._guard():
            return
        super().do_GET()

    def do_HEAD(self):
        self._etag = None
        if self._guard():
            return
        super().do_HEAD()

    def log_message(self, fmt, *args):
        if not self.quiet:
            ua = self.headers.get("User-Agent", "-") if hasattr(self, "headers") and self.headers else "-"
            sys.stderr.write(f"{self.client_address[0]} [{self.log_date_time_string()}] {fmt % args} UA={ua}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--rate", type=float, default=5, help="同一 IP 每秒補充幾個請求額度（預設 5）")
    ap.add_argument("--burst", type=int, default=20, help="同一 IP 可瞬間發出的請求數（預設 20）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-build", action="store_true", help="不要重建 dist-local/")
    args = ap.parse_args()

    site_url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}"
    if not args.no_build:
        subprocess.run([sys.executable, str(ROOT / "build.py"), "--base", "/", "--site-url", site_url,
                        "--out", str(DIST)], check=True)
    Handler.limiter = RateLimiter(rate=args.rate, burst=args.burst)
    Handler.quiet = args.quiet
    os.chdir(DIST)
    with http.server.ThreadingHTTPServer((args.host, args.port), Handler) as httpd:
        print(f"練習站：{site_url}/   （Ctrl+C 結束）")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
