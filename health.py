"""Periodic reachability checks for public URLs shown in the side bar."""
import threading
import time
import urllib.error
import urllib.request

INTERVAL = 300


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
    def __init__(self, checks, check=probe, start=True):
        self.checks = checks
        self.check = check
        self.results = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        if start:
            self.thread.start()

    def tick(self):
        for item in self.checks:
            result = dict(self.check(item["url"]), at=time.time())
            with self.lock:
                self.results[item["name"]] = result

    def loop(self):
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(INTERVAL)

    def snapshot(self):
        with self.lock:
            return [dict(item, **self.results.get(item["name"], {})) for item in self.checks]

    def close(self):
        self.stop.set()
