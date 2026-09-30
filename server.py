"""MA4 HTTP server: static page, JSON API and an SSE event stream (127.0.0.1 only)."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import threading
from urllib.parse import parse_qs, urlsplit

from appserver import Disconnected, RpcError
from health import HealthPoller
from hub import Hub
from quota import QuotaPoller

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = ROOT / ".ma4"
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js",
          "/markdown.js": "markdown.js", "/style.css": "style.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8"}


def find_codex(configured):
    if configured:
        return configured
    found = shutil.which("codex")
    if found:
        return found
    # Services do not load nvm; fall back to the newest nvm-installed CLI.
    candidates = sorted(Path.home().glob(".nvm/versions/node/*/bin/codex"))
    if candidates:
        return str(candidates[-1])
    raise SystemExit("找不到 codex 命令，请在 config.json 设置 codex_bin")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, hub, quota, health, links):
        super().__init__(address, Handler)
        self.hub, self.quota, self.health, self.links = hub, quota, health, links


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep message text and paths out of the journal

    def guard(self, write):
        port = self.server.server_port
        hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
        if self.headers.get("Host") not in hosts:
            raise PermissionError("invalid Host")
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in hosts}:
            raise PermissionError("cross-origin request refused")
        page = self.command == "GET" and urlsplit(self.path).path in ("/", "/index.html")
        if self.headers.get("Sec-Fetch-Site") == "cross-site" and not page:
            raise PermissionError("cross-site request refused")
        if write and self.headers.get("X-MA4-Request") != "1":
            raise PermissionError("missing X-MA4-Request header")

    def send(self, code, body, mime="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if code >= 400:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def fail(self, exc):
        if isinstance(exc, PermissionError):
            return self.send(403, {"error": str(exc)})
        if isinstance(exc, (ValueError, KeyError, TypeError)):
            return self.send(400, {"error": str(exc)})
        if isinstance(exc, RpcError):
            return self.send(502, {"error": "Codex：" + str(exc)})
        if isinstance(exc, (Disconnected, TimeoutError, OSError)):
            return self.send(503, {"error": str(exc) or "Codex 守护进程不可用"})
        raise exc

    def side(self):
        return {"quota": self.server.quota.snapshot(), "health": self.server.health.snapshot(),
                "links": self.server.links}

    def do_GET(self):
        try:
            self.guard(False)
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            hub = self.server.hub
            if url.path in STATIC:
                name = STATIC[url.path]
                return self.send(200, (WEB / name).read_bytes(), TYPES[Path(name).suffix])
            if url.path == "/api/state":
                return self.send(200, dict(hub.state(), side=self.side()))
            if url.path == "/api/side":
                return self.send(200, self.side())
            if url.path == "/api/skills":
                row = hub.threads.get(query["id"][0]) or {}
                return self.send(200, {"skills": hub.skills(row.get("cwd") or str(Path.home()))})
            if url.path == "/api/models":
                return self.send(200, {"models": hub.models()})
            if url.path == "/api/history":
                return self.send(200, hub.history(query["id"][0], (query.get("cursor") or [None])[0]))
            if url.path == "/api/events":
                return self.stream(int((query.get("since") or [self.headers.get("Last-Event-ID") or 0])[0]))
            self.send(404, {"error": "not found"})
        except Exception as exc:
            self.fail(exc)

    def do_POST(self):
        try:
            self.guard(True)
            length = int(self.headers.get("Content-Length") or 0)
            if length > 200_000:
                raise ValueError("请求太大")
            data = json.loads(self.rfile.read(length) or b"{}")
            hub = self.server.hub
            path = urlsplit(self.path).path
            actions = {
                "/api/open": lambda: hub.open(data["id"]),
                "/api/send": lambda: hub.send(data["id"], data.get("text"), str(data["request_id"])),
                "/api/interrupt": lambda: hub.interrupt(data["id"]),
                "/api/command": lambda: hub.command(data["id"], data["name"], data.get("arg")),
                "/api/new": lambda: hub.new_thread(data.get("cwd"), data.get("text")),
                "/api/rename": lambda: hub.rename(data["id"], data.get("name")),
                "/api/pin": lambda: hub.pin(data["id"], bool(data.get("pinned"))),
                "/api/approval": lambda: hub.decide(data["key"], data.get("decision")),
                "/api/terminal": lambda: hub.open_terminal(data["id"]),
            }
            if path not in actions:
                return self.send(404, {"error": "not found"})
            self.send(200, actions[path]())
        except Exception as exc:
            self.fail(exc)

    def stream(self, since):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                events = self.server.hub.events_after(since, timeout=20)
                if events is None:
                    self.wfile.write(b"event: resync\ndata: {}\n\n")
                    since = self.server.hub.seq
                elif not events:
                    self.wfile.write(b": keep-alive\n\n")
                for seq, event in events or []:
                    self.wfile.write(("id: %d\ndata: %s\n\n" % (seq, json.dumps(event, ensure_ascii=False))).encode())
                    since = seq
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    codex = find_codex(config.get("codex_bin"))
    # The npm wrapper runs through node; keep its directory on PATH for child processes.
    os.environ["PATH"] = os.path.dirname(codex) + os.pathsep + os.environ.get("PATH", "")
    hub = Hub(DATA, codex)
    quota_source = Path(config["quota_source"]) if config.get("quota_source") else None
    quota = QuotaPoller(DATA, source_file=quota_source)
    health = HealthPoller(config.get("health", []))
    server = Server(("127.0.0.1", args.port or config.get("port", 8764)), hub, quota, health,
                    config.get("links", []))
    hub.start()

    def shutdown(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print("MA4 listening on http://127.0.0.1:%d" % server.server_port, flush=True)
    try:
        server.serve_forever()
    finally:
        hub.close()
        quota.close()
        health.close()
        server.server_close()


if __name__ == "__main__":
    main()
