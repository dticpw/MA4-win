"""Quota polling for the side bar. The source URL (it carries an access key) lives in a
private local file and never reaches the browser, the logs or Git.

Two source formats are understood:
- quota-detail: {"families": [{"key", "label", "account": {h5_used, h5_reset, d7_used,
  d7_reset, fable_used, fable_reset, updated}}], "generated_at"}  (Codex and Claude)
- legacy codex-quota: {"d7_used", "d7_reset", "updated"}  (Codex only, from MA3)
"""
import datetime as dt
import json
import math
import threading
import time
import urllib.request

INTERVAL = 300
WINDOWS = (("h5", "5 小时"), ("d7", "7 天"), ("fable", "Fable 周"))


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if 0 <= value <= 100 else None


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return value


def iso(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.isoformat() if parsed.tzinfo else None


def family(key, label, account):
    windows = []
    for name, title in WINDOWS:
        used = percent(account.get(name + '_used'))
        if used is not None:
            windows.append(dict(key=name, label=title, used=used, reset_at=timestamp(account.get(name + '_reset'))))
    return dict(key=key, label=label, windows=windows, updated=iso(account.get('updated')))


def normalize(data):
    if isinstance(data.get('families'), list):
        families = [family(str(f.get('key', '')), str(f.get('label') or f.get('key', '')), f.get('account') or {})
                    for f in data['families'] if isinstance(f, dict)]
        families = [f for f in families if f['windows']]
        updated = iso(data.get('generated_at'))
    else:
        families = [family('codex', 'Codex', data)]
        updated = families[0]['updated']
    if not families or not any(f['windows'] for f in families):
        raise ValueError('no usage figures')
    return dict(families=families, updated=updated)


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
        if 'families' not in self.cache:
            self.cache = {}  # older single-figure cache: refetch now
        self.thread = threading.Thread(target=self.loop, daemon=True)
        if start:
            self.thread.start()

    def download(self):
        source = json.loads(self.source_file.read_text())['url']
        if not source.startswith('https://'):
            raise ValueError('HTTPS required')
        with urllib.request.urlopen(source, timeout=20) as response:
            return json.loads(response.read(500_000))

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
            tmp.write_text(json.dumps(self.cache, ensure_ascii=False)+'\n')
            tmp.replace(self.directory/'quota-cache.json')

    def snapshot(self):
        with self.lock:
            result = dict(self.cache)
        result['stale'] = bool(result.get('error')) or self.clock()-result.get('fetched_at', 0) > INTERVAL+60
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
