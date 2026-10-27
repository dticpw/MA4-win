"""Current service activity only: no visit history or credentials are written to disk."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import ipaddress
import json
import math
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

SERVICES = (("texas", "德州扑克", "在线玩家", 15),
            ("ace21", "王牌21点", "在线玩家", 15),
            ("chat", "Chat / 代理", "近 5 分钟活跃 IP", 60))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the stats credential to a redirect target.


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid number")
    return value


def count(value):
    if number(value) < 0 or int(value) != value:
        raise ValueError("invalid count")
    return int(value)


def game_activity(data, game):
    if data.get("game") != game or not isinstance(data.get("tables"), list) or not data["tables"]:
        raise ValueError("invalid tables")
    players = set()
    for table in data["tables"]:
        if table.get("game") != game or not isinstance(table.get("seats"), list):
            raise ValueError("invalid table")
        for seat in table["seats"]:
            if seat is None:
                continue
            if not isinstance(seat, dict) or not isinstance(seat.get("online"), bool) or not seat.get("id"):
                raise ValueError("invalid seat")
            if seat["online"]:
                players.add(seat["id"])
    return {"count": len(players)}  # No player names, IPs, tokens or cards reach MA4.


def chat_activity(data, now):
    if data.get("window_seconds") != 300 or not isinstance(data.get("visitors"), list):
        raise ValueError("active stats endpoint required")
    generated = number(data.get("generated_at")) / 1000
    if abs(now - generated) > 120:
        raise ValueError("outdated stats")
    total = count(data.get("total_ips"))
    if not isinstance(data.get("truncated"), bool):
        raise ValueError("missing completeness")
    rows = []
    for row in data["visitors"]:
        ip = str(ipaddress.ip_address(row.get("ip")))
        seen = number(row.get("last_seen")) / 1000
        if not generated - 300 <= seen <= generated:
            raise ValueError("visitor outside window")
        location = {k: str(row.get(k) or "").strip()[:200] for k in ("country", "region", "city")}
        rows.append(dict(ip=ip, last_seen=seen, requests=count(row.get("requests")), **location))
    if len(rows) > 200 or len({r["ip"] for r in rows}) != len(rows) or total < len(rows):
        raise ValueError("invalid visitors")
    if data["truncated"] != (total > len(rows)):
        raise ValueError("incomplete visitors")
    return {"count": total, "visitors": rows, "truncated": data["truncated"], "observed_at": generated}


class ActivityPoller:
    def __init__(self, config, fetch=None, clock=time.time, start=True):
        self.config, self.clock = config or {}, clock
        self.enabled = bool(config)
        self.fetch = fetch or self.download
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.values, self.due = {}, {}
        self.observer = secrets.token_urlsafe(32)  # Unseated observer; never counted as a player.
        self.password = None
        self.thread = threading.Thread(target=self.loop, daemon=True)
        if start and self.enabled:
            self.thread.start()

    def credential(self):
        if self.password is None:
            result = subprocess.run(
                [sys.executable, self.config["credential_cli"], "get", self.config["stats_credential"]],
                env={**os.environ, "AGENTFLOW_CREDENTIALS_FILE": self.config["credential_file"]},
                capture_output=True, text=True, timeout=10, check=True)
            value = json.loads(result.stdout)
            if value.get("credential_status") != "ok":
                raise ValueError("credential unavailable")
            match = re.search(r"^\s*Password:\s*(.+)$", value["content"], re.M)
            if not match:
                raise ValueError("credential unavailable")
            self.password = match.group(1).strip().strip("`")
        return self.password

    def download(self, key):
        base = self.config["stats_url"] if key == "chat" else self.config["games_url"]
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("HTTPS endpoint without credentials required")
        url = base + "?view=active" if key == "chat" else base.rstrip("/") + "/tables/" + key
        token = self.credential() if key == "chat" else self.observer
        request = urllib.request.Request(url, headers={"User-Agent": "MA4-service-activity/1.0", "Authorization": "Bearer " + token})
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(request, timeout=10) as response:
                body = response.read(250_001)
                if len(body) > 250_000:
                    raise ValueError("response too large")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if key == "chat" and exc.code in (401, 403):
                self.password = None
            raise

    def collect(self, key):
        try:
            raw = self.fetch(key)
            value = chat_activity(raw, self.clock()) if key == "chat" else game_activity(raw, key)
            value.update(fetched_at=self.clock(), error=None)
            with self.lock:
                self.values[key] = value
        except Exception:
            # Network errors may contain credentials/URLs; return only a fixed message.
            with self.lock:
                self.values.setdefault(key, {})["error"] = "查询失败，暂无法确认"

    def tick(self):
        if not self.enabled:
            return
        now = self.clock()
        due = [key for key, _, _, _ in SERVICES if now >= self.due.get(key, 0)]
        if not due:
            return
        for key, _, _, interval in SERVICES:
            if key in due:
                self.due[key] = now + interval
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.collect, key) for key in due]
            for future in as_completed(futures):
                future.result()

    def snapshot(self):
        if not self.enabled:
            return []
        with self.lock:
            values = copy.deepcopy(self.values)
        rows = []
        for key, label, metric, interval in SERVICES:
            value = values.get(key, {})
            stale = bool(value.get("error")) or self.clock() - value.get("fetched_at", 0) > interval * 2 + 15
            if stale:
                value["count"] = None
                value.pop("visitors", None)
                value.pop("truncated", None)
            rows.append(dict(value, key=key, label=label, metric=metric, stale=stale))
        return rows

    def loop(self):
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(5)

    def close(self):
        self.stop.set()
