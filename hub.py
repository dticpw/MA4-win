"""State hub between the Codex app-server daemon and the web page.

Owns the daemon connection (reconnecting and starting the daemon when
needed), a cached thread list, subscriptions for opened threads, pending
approval requests and a small preference file. Every change becomes an event
that the HTTP layer streams to browsers.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

from appserver import AppServer, DEFAULT_SOCKET, Disconnected, RpcError

LIST_LIMIT = 80
OUTPUT_LIMIT = 4000
TEXT_LIMIT = 60000
# "$name" as typed in the terminal UI; not preceded by a word character or another "$".
SKILL_MENTION = re.compile(r"(?<![\w$])\$([A-Za-z0-9][A-Za-z0-9_:-]*)")
APPROVAL_METHODS = {
    "item/commandExecution/requestApproval": "command",
    "item/fileChange/requestApproval": "file",
    "execCommandApproval": "command",
    "applyPatchApproval": "file",
}


def clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else "…（前面省略 %d 字）\n" % (len(text) - limit) + text[-limit:]


def user_text(content):
    parts = []
    for c in content or []:
        kind = c.get("type")
        if kind == "text":
            parts.append(c.get("text", ""))
        elif kind in ("image", "localImage"):
            parts.append("[图片]")
        elif kind in ("skill", "mention"):
            parts.append("@" + str(c.get("name", "")))
    return "\n".join(parts)


def normalize_item(item):
    """Reduce a ThreadItem to what the page shows; unknown types keep a label."""
    kind = item.get("type")
    base = {"id": item.get("id"), "type": kind}
    if kind == "userMessage":
        return {**base, "text": clip(user_text(item.get("content")), TEXT_LIMIT)}
    if kind == "agentMessage":
        return {**base, "text": clip(item.get("text"), TEXT_LIMIT), "phase": item.get("phase")}
    if kind == "reasoning":
        summary = item.get("summary") or []
        text = "\n".join(s if isinstance(s, str) else s.get("text", "") for s in summary)
        return {**base, "text": clip(text, OUTPUT_LIMIT)}
    if kind == "plan":
        return {**base, "text": clip(item.get("text"), OUTPUT_LIMIT)}
    if kind == "commandExecution":
        return {**base, "command": item.get("command"), "status": item.get("status"),
                "exitCode": item.get("exitCode"), "durationMs": item.get("durationMs"),
                "output": clip(item.get("aggregatedOutput"), OUTPUT_LIMIT)}
    if kind == "fileChange":
        changes = [{"path": c.get("path"), "kind": (c.get("kind") or {}).get("type") if isinstance(c.get("kind"), dict) else c.get("kind"),
                    "diff": clip(c.get("diff"), OUTPUT_LIMIT)} for c in item.get("changes") or []]
        return {**base, "status": item.get("status"), "changes": changes}
    if kind == "mcpToolCall":
        return {**base, "tool": "%s.%s" % (item.get("server"), item.get("tool")),
                "status": item.get("status"), "error": (item.get("error") or {}).get("message") if isinstance(item.get("error"), dict) else item.get("error")}
    if kind == "dynamicToolCall":
        return {**base, "tool": item.get("tool"), "status": item.get("status")}
    if kind == "webSearch":
        return {**base, "query": item.get("query")}
    if kind in ("imageView", "imageGeneration"):
        return {**base, "path": item.get("path") or item.get("savedPath")}
    if kind in ("collabAgentToolCall", "subAgentActivity"):
        return {**base, "tool": item.get("tool") or item.get("kind"), "status": item.get("status")}
    return base


def status_of(thread):
    status = thread.get("status") or {}
    kind = status.get("type", "notLoaded")
    flags = status.get("activeFlags") or []
    if kind == "active" and "waitingOnApproval" in flags:
        return "approval"
    if kind == "active" and "waitingOnUserInput" in flags:
        return "input"
    return {"active": "running", "idle": "idle", "systemError": "error"}.get(kind, "offline")


class Prefs:
    """Pins and last-seen timestamps; small JSON written atomically."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.pinned = set(data.get("pinned", []))
        self.seen = dict(data.get("seen", {}))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"pinned": sorted(self.pinned), "seen": self.seen},
                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


class Hub:
    def __init__(self, data_dir, codex_bin, socket_path=DEFAULT_SOCKET, poll_seconds=3,
                 connect=AppServer):
        self.data_dir = Path(data_dir)
        self.codex_bin = codex_bin
        self.socket_path = Path(socket_path)
        self.poll_seconds = poll_seconds
        self.connect_factory = connect
        self.prefs = Prefs(self.data_dir / "prefs.json")
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.client = None
        self.daemon = {"connected": False, "error": None, "version": None}
        self.threads = {}          # id -> summary
        self.live = {}             # id -> {"turn": id|None, "tokens": {...}}
        self.subscribed = set()
        self.approvals = {}        # key -> approval summary (+ rid)
        self.sent = {}             # request_id -> result, to make retries harmless
        self.skill_cache = {}      # cwd -> (fetched_at, skills)
        self.model_override = {}   # id -> model chosen with /model for later turns
        self.events = []           # (seq, event)
        self.seq = 0
        self.refresh_soon = threading.Event()
        self.stop = threading.Event()
        self.last_daemon_start = 0
        self.worker = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.worker.start()

    # ---- events -------------------------------------------------------
    def emit(self, kind, **data):
        with self.changed:
            self.seq += 1
            self.events.append((self.seq, {"kind": kind, **data}))
            del self.events[:-500]
            self.changed.notify_all()

    def events_after(self, seq, timeout=20):
        """Block until events newer than seq exist; None means the client must resync."""
        with self.changed:
            if self.events and seq < self.events[0][0] - 1:
                return None
            if self.seq <= seq:
                self.changed.wait(timeout)
            return [e for e in self.events if e[0] > seq]

    # ---- connection ---------------------------------------------------
    def run(self):
        while not self.stop.is_set():
            if self.client is None or self.client.closed:
                self.try_connect()
            if self.client is not None and not self.client.closed:
                try:
                    self.refresh()
                except (Disconnected, OSError, TimeoutError, RpcError) as exc:
                    self.set_daemon(error="读取会话列表失败：" + str(exc)[:200])
            self.refresh_soon.wait(self.poll_seconds)
            self.refresh_soon.clear()

    def try_connect(self):
        if not self.socket_path.exists():
            # The daemon starts on demand; after a reboot nothing else may start it.
            if time.time() - self.last_daemon_start > 30:
                self.last_daemon_start = time.time()
                try:
                    subprocess.run([self.codex_bin, "app-server", "daemon", "start"],
                                   capture_output=True, timeout=60)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self.set_daemon(error="启动 Codex 守护进程失败：" + str(exc)[:200])
                    return
            if not self.socket_path.exists():
                self.set_daemon(error="Codex 守护进程未运行")
                return
        try:
            client = self.connect_factory(self.socket_path, on_notification=self.on_notification,
                                          on_request=self.on_request, on_disconnect=self.on_disconnect)
        except (OSError, Disconnected, TimeoutError, RpcError) as exc:
            self.set_daemon(error="连接 Codex 守护进程失败：" + str(exc)[:200])
            return
        with self.lock:
            self.client = client
            stale = list(self.subscribed)
            self.subscribed.clear()
            self.approvals.clear()
        self.set_daemon(connected=True, error=None, version=(client.info or {}).get("userAgent"))
        for tid in stale:
            try:
                self.subscribe(tid)
            except (RpcError, Disconnected, TimeoutError):
                pass

    def on_disconnect(self, reason):
        with self.lock:
            self.client = None
            self.approvals.clear()
        self.set_daemon(connected=False, error="与 Codex 守护进程断开：" + reason[:200])
        self.emit("approvals", approvals=[])
        self.refresh_soon.set()

    def set_daemon(self, **changes):
        with self.lock:
            before = dict(self.daemon)
            self.daemon.update(changes)
            if before == self.daemon:
                return
        self.emit("daemon", daemon=dict(self.daemon))

    def call(self, method, params, timeout=30):
        client = self.client
        if client is None or client.closed:
            raise Disconnected("Codex 守护进程未连接")
        return client.call(method, params, timeout)

    # ---- thread list --------------------------------------------------
    def refresh(self):
        result = self.call("thread/list", {"limit": LIST_LIMIT, "sortKey": "updated_at"})
        fresh = {}
        for t in result.get("data", []):
            if t.get("parentThreadId") or t.get("ephemeral"):
                continue
            fresh[t["id"]] = t
        with self.lock:
            seen_dirty = False
            summaries = {}
            for tid, t in fresh.items():
                updated = t.get("updatedAt") or 0
                if tid not in self.prefs.seen:
                    # First sighting is quiet: only later activity counts as unread.
                    self.prefs.seen[tid] = updated
                    seen_dirty = True
                summaries[tid] = self.summarize(t)
            if seen_dirty:
                self.prefs.save()
            if summaries != self.threads:
                self.threads = summaries
                self.emit("threads", threads=self.thread_list())

    def summarize(self, t):
        tid = t["id"]
        state = status_of(t)
        updated = t.get("updatedAt") or 0
        return {"id": tid, "name": t.get("name") or "", "preview": (t.get("preview") or "")[:120],
                "cwd": t.get("cwd") or "", "status": state, "updatedAt": updated,
                "source": t.get("source") if isinstance(t.get("source"), str) else "other",
                "model": t.get("model"), "effort": t.get("reasoningEffort"),
                "branch": (t.get("gitInfo") or {}).get("branch"), "pinned": tid in self.prefs.pinned,
                "unread": state in ("idle", "offline", "error") and updated > self.prefs.seen.get(tid, 0)}

    def thread_list(self):
        with self.lock:
            rows = []
            for r in self.threads.values():
                live = self.live.get(r["id"], {})
                # Settings reported by the daemon for a loaded thread beat the list snapshot.
                rows.append(dict(r, **live.get("settings", {}), tokens=live.get("tokens")))
        return sorted(rows, key=lambda r: -r["updatedAt"])

    def update_status(self, tid, status):
        with self.lock:
            row = self.threads.get(tid)
            if not row:
                self.refresh_soon.set()
                return
            new = self.summarize({"id": tid, "status": status, "name": row["name"], "preview": row["preview"],
                                  "cwd": row["cwd"], "updatedAt": max(row["updatedAt"], int(time.time())),
                                  "source": row["source"], "model": row["model"],
                                  "reasoningEffort": row["effort"], "gitInfo": {"branch": row["branch"]}})
            self.threads[tid] = new
        self.emit("threads", threads=self.thread_list())

    # ---- daemon callbacks (reader thread) ------------------------------
    def on_notification(self, method, params):
        tid = params.get("threadId")
        if method == "thread/status/changed":
            self.update_status(tid, params.get("status"))
        elif method in ("thread/started", "thread/name/updated", "thread/archived", "thread/deleted",
                        "thread/unarchived", "thread/closed"):
            self.refresh_soon.set()
        elif method == "turn/started":
            with self.lock:
                self.live.setdefault(tid, {})["turn"] = params["turn"]["id"]
            self.emit("turn", threadId=tid, turnId=params["turn"]["id"], state="started")
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            with self.lock:
                self.live.setdefault(tid, {})["turn"] = None
            self.emit("turn", threadId=tid, turnId=turn.get("id"), state=turn.get("status"),
                      error=(turn.get("error") or {}).get("message") if isinstance(turn.get("error"), dict) else None)
            self.refresh_soon.set()
        elif method in ("item/started", "item/completed"):
            self.emit("item", threadId=tid, turnId=params.get("turnId"),
                      done=method == "item/completed", item=normalize_item(params.get("item") or {}))
        elif method == "item/agentMessage/delta":
            self.emit("delta", threadId=tid, itemId=params.get("itemId"), delta=params.get("delta", ""))
        elif method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage") or {}
            tokens = {"used": (usage.get("last") or {}).get("totalTokens"),
                      "window": usage.get("modelContextWindow")}
            with self.lock:
                self.live.setdefault(tid, {})["tokens"] = tokens
            self.emit("tokens", threadId=tid, tokens=tokens)
        elif method == "thread/settings/updated":
            settings = params.get("threadSettings") or {}
            with self.lock:
                self.live.setdefault(tid, {})["settings"] = {"model": settings.get("model"),
                                                             "effort": settings.get("effort")}
            self.emit("threads", threads=self.thread_list())
        elif method == "serverRequest/resolved":
            key = str(params.get("requestId"))
            with self.lock:
                gone = self.approvals.pop(key, None)
            if gone:
                self.emit("approvals", approvals=self.approval_list())

    def on_request(self, rid, method, params):
        kind = APPROVAL_METHODS.get(method)
        entry = {"key": str(rid), "rid": rid, "method": method, "threadId": params.get("threadId") or params.get("conversationId"),
                 "kind": kind or "other", "reason": params.get("reason"), "at": time.time()}
        if kind == "command":
            command = params.get("command")
            entry["command"] = " ".join(command) if isinstance(command, list) else command
            entry["cwd"] = params.get("cwd")
        elif kind == "file":
            entry["paths"] = [c.get("path") for c in params.get("changes", []) if isinstance(c, dict)] \
                if isinstance(params.get("changes"), list) else list((params.get("fileChanges") or {}).keys())
        with self.lock:
            self.approvals[entry["key"]] = entry
        self.emit("approvals", approvals=self.approval_list())

    def approval_list(self):
        with self.lock:
            return [{k: v for k, v in a.items() if k != "rid"} for a in self.approvals.values()]

    # ---- actions -------------------------------------------------------
    def subscribe(self, tid):
        with self.lock:
            if tid in self.subscribed:
                return
        resumed = self.call("thread/resume", {"threadId": tid, "excludeTurns": True}, timeout=60)
        with self.lock:
            self.subscribed.add(tid)
            if resumed.get("model"):
                self.live.setdefault(tid, {})["settings"] = {"model": resumed["model"],
                                                             "effort": resumed.get("reasoningEffort")}

    def current_turn(self, tid):
        with self.lock:
            known = self.live.get(tid, {}).get("turn")
        if known:
            return known
        try:
            page = self.call("thread/turns/list", {"threadId": tid, "limit": 1, "sortDirection": "desc",
                                                   "itemsView": "notLoaded"})
        except RpcError as exc:
            if "not materialized" in str(exc):
                return None  # brand-new thread: no turns before the first message
            raise
        turns = page.get("data") or []
        if turns and turns[0].get("status") == "inProgress":
            return turns[0]["id"]
        return None

    def open(self, tid):
        """Mark as seen and follow live events when the thread is already running."""
        with self.lock:
            row = self.threads.get(tid)
            if row:
                self.prefs.seen[tid] = max(row["updatedAt"], int(time.time()))
                self.prefs.save()
                row["unread"] = False
        if row and row["status"] != "offline":
            self.subscribe(tid)
        self.emit("threads", threads=self.thread_list())
        with self.lock:
            live = dict(self.live.get(tid, {}))
        with self.lock:
            override = self.model_override.get(tid)
        return {"turn": self.current_turn(tid) if row and row["status"] != "offline" else None,
                "tokens": live.get("tokens"), "override": override}

    def history(self, tid, cursor=None, limit=8):
        params = {"threadId": tid, "limit": limit, "sortDirection": "desc", "itemsView": "full"}
        if cursor:
            params["cursor"] = cursor
        try:
            page = self.call("thread/turns/list", params, timeout=60)
        except RpcError as exc:
            if "not materialized" in str(exc):
                return {"turns": [], "older": None}
            raise
        turns = []
        for turn in reversed(page.get("data") or []):
            turns.append({"id": turn["id"], "status": turn.get("status"), "startedAt": turn.get("startedAt"),
                          "durationMs": turn.get("durationMs"),
                          "error": (turn.get("error") or {}).get("message") if isinstance(turn.get("error"), dict) else None,
                          "items": [normalize_item(i) for i in turn.get("items") or []]})
        return {"turns": turns, "older": page.get("nextCursor")}

    def skills(self, cwd):
        """Enabled skills for a working directory, cached for a minute."""
        with self.lock:
            cached = self.skill_cache.get(cwd)
        if cached and time.time() - cached[0] < 60:
            return cached[1]
        entries = self.call("skills/list", {"cwds": [cwd]}).get("data") or []
        found = [{"name": s["name"], "path": s["path"],
                  "description": s.get("shortDescription") or s.get("description", "")}
                 for e in entries for s in e.get("skills", []) if s.get("enabled", True)]
        found.sort(key=lambda s: s["name"])
        with self.lock:
            self.skill_cache[cwd] = (time.time(), found)
        return found

    def models(self):
        data = self.call("model/list", {}).get("data") or []
        def effort_name(e):
            return e if isinstance(e, str) else (e.get("reasoningEffort") or e.get("effort") or "")
        return [{"id": m["id"], "name": m.get("displayName") or m["id"], "default": m.get("isDefault", False),
                 "description": m.get("description", ""), "defaultEffort": m.get("defaultReasoningEffort"),
                 "efforts": [effort_name(e) for e in m.get("supportedReasoningEfforts") or []]}
                for m in data if not m.get("hidden")]

    def skill_inputs(self, tid, text):
        """Turn $name mentions of known skills into explicit skill inputs, like the terminal UI."""
        names = set(SKILL_MENTION.findall(text))
        if not names:
            return []
        with self.lock:
            cwd = (self.threads.get(tid) or {}).get("cwd")
        if not cwd:
            return []
        return [{"type": "skill", "name": s["name"], "path": s["path"]}
                for s in self.skills(cwd) if s["name"] in names]

    def send(self, tid, text, request_id):
        if not isinstance(text, str) or not text.strip() or len(text) > 50000:
            raise ValueError("消息需为 1–50000 个字符")
        with self.lock:
            if request_id in self.sent:
                return self.sent[request_id]
        self.subscribe(tid)
        turn = self.current_turn(tid)
        message = [{"type": "text", "text": text, "text_elements": []}] + self.skill_inputs(tid, text)
        if turn:
            self.call("turn/steer", {"threadId": tid, "expectedTurnId": turn, "input": message,
                                     "clientUserMessageId": request_id})
            result = {"mode": "steer", "turnId": turn}
        else:
            params = {"threadId": tid, "input": message, "clientUserMessageId": request_id}
            with self.lock:
                override = self.model_override.get(tid) or {}
                if override.get("model"):
                    params["model"] = override["model"]
                if override.get("effort"):
                    params["effort"] = override["effort"]
            started = self.call("turn/start", params)
            result = {"mode": "start", "turnId": (started.get("turn") or {}).get("id")}
        with self.lock:
            self.sent[request_id] = result
            if len(self.sent) > 200:
                self.sent.pop(next(iter(self.sent)))
        return result

    def command(self, tid, name, arg=""):
        """Slash commands that the terminal UI handles itself, mapped to app-server calls."""
        arg = (arg or "").strip()
        if name == "rename":
            return self.rename(tid, arg)
        if name == "stop":
            return self.interrupt(tid)
        if name == "compact":
            self.subscribe(tid)
            if self.current_turn(tid):
                raise ValueError("Agent 正在工作，等这一轮结束再压缩")
            self.call("thread/compact/start", {"threadId": tid})
            return {"message": "已开始压缩上下文"}
        if name == "review":
            self.subscribe(tid)
            if self.current_turn(tid):
                raise ValueError("Agent 正在工作，等这一轮结束再审查")
            target = {"type": "baseBranch", "branch": arg} if arg else {"type": "uncommittedChanges"}
            self.call("review/start", {"threadId": tid, "target": target})
            return {"message": "已开始审查" + ("与 " + arg + " 分支的差异" if arg else "未提交的改动")}
        if name == "model":
            parts = arg.split()
            if not parts or len(parts) > 2:
                raise ValueError("用法：/model 模型名 [思考深度]")
            models = {m["id"]: m for m in self.models()}
            if parts[0] not in models:
                raise ValueError("没有这个模型，可选：" + "、".join(models))
            efforts = models[parts[0]]["efforts"]
            effort = parts[1] if len(parts) == 2 else None
            if effort and efforts and effort not in efforts:
                raise ValueError(parts[0] + " 支持的思考深度：" + "、".join(efforts))
            override = {"model": parts[0], "effort": effort}
            with self.lock:
                self.model_override[tid] = override
            return {"message": "下一轮起使用 " + parts[0] + ("，思考 " + effort if effort else ""),
                    "override": override}
        raise ValueError("不支持的命令：/" + name)

    def interrupt(self, tid):
        turn = self.current_turn(tid)
        if not turn:
            raise ValueError("这个会话当前没有在运行的回合")
        self.call("turn/interrupt", {"threadId": tid, "turnId": turn})
        return {"interrupted": turn}

    def new_thread(self, cwd, text=None):
        path = Path(os.path.expanduser(cwd or "")).resolve()
        if not path.is_dir():
            raise ValueError("工作目录不存在：" + str(path))
        started = self.call("thread/start", {"cwd": str(path)}, timeout=60)
        tid = started["thread"]["id"]
        with self.lock:
            self.subscribed.add(tid)
            self.prefs.seen[tid] = int(time.time())
            self.prefs.save()
        if text and text.strip():
            self.send(tid, text, "new-" + uuid.uuid4().hex)
        self.refresh_soon.set()
        return {"threadId": tid}

    def rename(self, tid, name):
        name = (name or "").strip()
        if not name or len(name) > 100:
            raise ValueError("名称需为 1–100 个字符")
        self.call("thread/name/set", {"threadId": tid, "name": name})
        self.refresh_soon.set()
        return {"renamed": True}

    def pin(self, tid, pinned):
        with self.lock:
            (self.prefs.pinned.add if pinned else self.prefs.pinned.discard)(tid)
            self.prefs.save()
            if tid in self.threads:
                self.threads[tid]["pinned"] = bool(pinned)
        self.emit("threads", threads=self.thread_list())
        return {"pinned": bool(pinned)}

    def decide(self, key, decision):
        if decision not in ("accept", "acceptForSession", "decline", "cancel"):
            raise ValueError("未知的审批决定")
        with self.lock:
            entry = self.approvals.get(key)
        if not entry:
            raise ValueError("这条审批已处理或已失效")
        if entry["kind"] == "other":
            raise ValueError("这类请求请在终端里处理")
        if entry["method"] in ("execCommandApproval", "applyPatchApproval"):
            legacy = {"accept": "approved", "acceptForSession": "approved_for_session",
                      "decline": "denied", "cancel": "abort"}
            answer = {"decision": legacy[decision]}
        else:
            answer = {"decision": decision}
        self.client.respond(entry["rid"], answer)
        with self.lock:
            self.approvals.pop(key, None)
        self.emit("approvals", approvals=self.approval_list())
        return {"decided": decision}

    def open_terminal(self, tid, terminal="/usr/bin/gnome-terminal"):
        with self.lock:
            row = self.threads.get(tid)
        if not row:
            raise ValueError("未知会话")
        title = "MA4 | " + (row["name"] or row["preview"][:30] or tid[:8])
        subprocess.Popen([terminal, "--title=" + title, "--", self.codex_bin, "resume", tid,
                          "-C", row["cwd"] or str(Path.home())],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"opened": True}

    def state(self):
        with self.lock:
            return {"threads": self.thread_list(), "approvals": self.approval_list(),
                    "daemon": dict(self.daemon), "seq": self.seq}

    def close(self):
        self.stop.set()
        self.refresh_soon.set()
        if self.client:
            self.client.close()
