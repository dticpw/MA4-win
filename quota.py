"""Thirty-minute quota polling (from MA3). The source URL lives in a private local file."""
import datetime as dt
import json
import math
import threading
import time
import urllib.request

INTERVAL = 1800
WEEK = 7 * 86400


def normalize(data):
    used = data.get('d7_used')
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or not 0 <= used <= 100:
        raise ValueError('invalid usage')
    reset = data.get('d7_reset')
    if isinstance(reset, bool) or not isinstance(reset, (int, float)) or not math.isfinite(reset) or reset <= 0:
        reset = None
    updated = data.get('updated')
    if isinstance(updated, str):
        try:
            parsed = dt.datetime.fromisoformat(updated.replace('Z', '+00:00'))
            updated = parsed.isoformat() if parsed.tzinfo else None
        except ValueError:
            updated = None
    else:
        updated = None
    return dict(used=used, reset_at=reset, updated=updated)


class QuotaPoller:
    def __init__(self, directory, source_file=None, fetch=None, clock=time.time, start=True):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.source_file = source_file or directory/'quota-source.json'
        self.clock = clock
        self.fetch = fetch or self.download
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.cache = {}
        try:
            self.cache = json.loads((directory/'quota-cache.json').read_text())
        except (OSError, ValueError):
            pass
        self.thread = threading.Thread(target=self.loop, daemon=True)
        if start:
            self.thread.start()

    def download(self):
        source = json.loads(self.source_file.read_text())['url']
        if not source.startswith('https://'):
            raise ValueError('HTTPS required')
        with urllib.request.urlopen(source, timeout=20) as response:
            return json.loads(response.read(65536))

    def tick(self):
        now = self.clock()
        with self.lock:
            if now < self.cache.get('next_poll', 0):
                return
            self.cache['next_poll'] = now + INTERVAL
        try:
            value = normalize(self.fetch())
            with self.lock:
                self.cache.update(value, fetched_at=self.clock(), error=None)
        except Exception:
            # Never expose HTTP exception text (which can contain the source key).
            with self.lock:
                self.cache['error'] = '额度查询失败，保留上次结果'
        with self.lock:
            tmp = self.directory/'quota-cache.tmp'
            tmp.write_text(json.dumps(self.cache)+'\n')
            tmp.replace(self.directory/'quota-cache.json')

    def snapshot(self):
        with self.lock:
            result = dict(self.cache)
        now = self.clock()
        result['stale'] = bool(result.get('error')) or now-result.get('fetched_at', 0) > INTERVAL+60
        reset = result.get('reset_at')
        result['reset_pending'] = bool(reset and reset <= now)
        return result

    def loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except OSError:
                with self.lock:
                    self.cache['error'] = '额度缓存保存失败'
            self.stop.wait(5)

    def close(self):
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=21)
