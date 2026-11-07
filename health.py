"""Periodic HTTP and TCP reachability checks shown in the side bar."""
import socket
import threading
import time
import urllib.error
import urllib.request

INTERVAL = 300
TCP_TIMEOUT = 3


def probe(url, timeout=10):
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "MA4-health/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "code": None, "error": str(getattr(exc, "reason", exc))[:120]}
    return {"ok": 200 <= code < 400, "code": code, "ms": round((time.monotonic() - started) * 1000)}


class HealthPoller:
    def __init__(self, checks, check=probe, start=True, tcp_check=None):
        self.checks = checks
        self.check = check
        self.tcp_check = tcp_check or probe_tcp
        self.results = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        if start:
            self.thread.start()

    def tick(self):
        for item in self.checks:
            kind = item.get("type", "http")
            try:
                if kind == "tcp":
                    result = self.tcp_check(item["host"], item["port"])
                elif kind == "http":
                    result = self.check(item["url"])
                else:
                    raise ValueError("unsupported check type")
            except Exception:
                result = {"ok": False, "error": "检查失败"}
            result = dict(result, at=time.time())
            with self.lock:
                self.results[item["name"]] = result

    def loop(self):
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(INTERVAL)

    def snapshot(self):
        with self.lock:
            rows = []
            for item in self.checks:
                result = self.results.get(item["name"], {})
                rows.append(dict(item, **result, stale=bool(result) and time.time() - result["at"] > INTERVAL * 2 + 15))
                rows[-1]["type"] = item.get("type", "http")
            return rows

    def close(self):
        self.stop.set()


def probe_tcp(host, port, timeout=TCP_TIMEOUT):
    """Connect and close only: no SSH handshake, authentication or remote command."""
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return {"ok": False, "ms": None, "error": "TCP 连接失败或超时"}
    return {"ok": True, "ms": round((time.monotonic() - started) * 1000)}
