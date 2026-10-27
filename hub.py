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
from urllib.parse import unquote, urlsplit

from appserver import AppServer, DEFAULT_SOCKET, Disconnected, RpcError
from controllers import Controllers, HOST_INSTRUCTIONS, HOST_TOOL_SETTINGS
from os_adapters import current as os_adapter
from runtime import ensure_daemon, open_terminal as launch_terminal

LIST_LIMIT = 80
OUTPUT_LIMIT = 4000
TEXT_LIMIT = 60000
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
    return "\n".join(parts)


def tool_text(value, limit=20000):
    """Bound display payloads and omit embedded image bytes before serialization."""
    def clean(v, depth=0):
        if depth > 12:
            return "[嵌套内容省略]"
        if isinstance(v, str):
            if v.startswith("data:image/"):
                return "[图片数据省略]"
            return v[:limit] + ("…（内容省略）" if len(v) > limit else "")
        if isinstance(v, dict):
            if v.get("type") in ("image", "inputImage"):
                return "[图片返回值，原始内容见 Codex 会话]"
            return {k: clean(x, depth + 1) for k, x in list(v.items())[:100]}
        if isinstance(v, list):
            return [clean(x, depth + 1) for x in v[:100]]
        return v
    rendered = clean(value)
    rendered = rendered if isinstance(rendered, str) else json.dumps(rendered, ensure_ascii=False, indent=2)
    return rendered[:limit] + ("\n…（内容省略，完整内容见 Codex 会话）" if len(rendered) > limit else "")


def normalize_item(item):
    """Reduce a ThreadItem to what the page shows; unknown types keep a label."""
    kind = item.get("type")
    base = {"id": item.get("id"), "type": kind}
    if kind == "userMessage":
        content = item.get("content") or []
        attachments = [{"type": c["type"], "name": str(c.get("name") or ""), "path": c.get("path")}
                       for c in content if c.get("type") in ("skill", "mention")]
        return {**base, "text": clip(user_text(content), TEXT_LIMIT), "attachments": attachments}
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
        content = item.get("contentItems")
        return {**base, "tool": item.get("tool"), "status": item.get("status"),
                "success": item.get("success"), "durationMs": item.get("durationMs"),
                "arguments": tool_text(item.get("arguments")),
                "output": "\n".join(tool_text(c.get("text", "")) if c.get("type") == "inputText"
                                    else "[图片返回值，原始内容见 Codex 会话]" for c in (content or [])[:100])[:24000]
                          if content is not None else None}
    if kind == "webSearch":
        return {**base, "query": item.get("query")}
    if kind in ("imageView", "imageGeneration"):
        return {**base, "path": item.get("path") or item.get("savedPath")}
    if kind in ("collabAgentToolCall", "subAgentActivity"):
        return {**base, "tool": item.get("tool") or item.get("kind"), "status": item.get("status")}
    return base


def describe(item):
    """One-line "what is it doing now" text for a started item, or None."""
    kind = item.get("type")
    if kind == "commandExecution":
        return "执行 " + (item.get("command") or "")[:120]
    if kind == "fileChange":
        paths = [c.get("path", "").replace("\\", "/").rsplit("/", 1)[-1] for c in item.get("changes") or []]
        return "修改 " + "、".join(paths[:3]) + ("等" if len(paths) > 3 else "") if paths else "修改文件"
    if kind in ("mcpToolCall", "dynamicToolCall"):
        return "调用 " + str(item.get("tool") or "")
    if kind == "webSearch":
        return "搜索 " + str(item.get("query") or "")[:80]
    if kind == "reasoning":
        return "思考中"
    if kind == "agentMessage":
        return "回复中"
    if kind in ("collabAgentToolCall", "subAgentActivity"):
        return "子 Agent 工作中"
    if kind == "contextCompaction":
        return "压缩上下文"
    return None


def permissions(sandbox, approval):
    """Normalize sandbox/approval settings to short strings (None when unknown)."""
    if isinstance(sandbox, dict):
        sandbox = sandbox.get("type")
    if isinstance(approval, dict):
        approval = "granular"
    return {"sandbox": sandbox, "approval": approval}


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
                 connect=AppServer, auto_start_daemon=True, codex_home=None):
        self.data_dir = Path(data_dir)
        self.codex_bin = codex_bin
        self.socket_path = str(socket_path)
        if "://" not in self.socket_path:
            self.socket_path = "unix://" + self.socket_path
        self.auto_start_daemon = auto_start_daemon
        self.codex_home = codex_home
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
        self.pending_subscriptions = set()  # accepted first turns awaiting a persisted rollout
        self.approvals = {}        # key -> approval summary (+ rid)
        self.sent = {}             # request_id -> result, to make retries harmless
        self.skill_cache = {}      # cwd -> (fetched_at, skills)
        self.managed_metadata = {}  # loaded/opened session metadata, refreshed at most once a minute
        self.removed_threads = set()  # ignore stale in-flight reads after archive/delete notifications
        self.model_override = {}   # id -> model chosen with /model for later turns
        self.events = []           # (seq, event)
        self.seq = 0
        self.refresh_soon = threading.Event()
        self.stop = threading.Event()
        self.last_daemon_start = 0
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.controllers = Controllers(self, self.data_dir)

    def start(self):
        self.controllers.start()
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
        try:
            client = self.connect_factory(self.socket_path, on_notification=self.on_notification,
                                          on_request=self.on_request, on_disconnect=self.on_disconnect, experimental=True)
        except (OSError, Disconnected, TimeoutError, RpcError) as exc:
            self.set_daemon(error="连接 Codex 守护进程失败：" + str(exc)[:200])
            if (self.auto_start_daemon and not self.socket_path.startswith("ws://")
                    and time.monotonic() - self.last_daemon_start > 30):
                self.last_daemon_start = time.monotonic()
                try:
                    ensure_daemon(self.codex_bin, self.socket_path, self.codex_home)
                except (OSError, subprocess.SubprocessError) as start_error:
                    self.set_daemon(error="启动 Codex 守护进程失败：" + str(start_error)[:200])
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
        self.controllers.disconnected()
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
        started = time.monotonic()
        result = self.call("thread/list", {"limit": LIST_LIMIT, "sortKey": "updated_at"})
        fresh = {}
        for t in result.get("data", []):
            if t.get("parentThreadId") or t.get("ephemeral"):
                continue
            fresh[t["id"]] = t
        # Empty threads may only exist in daemon memory, not in thread/list yet.
        loaded, cursor = set(), None
        while True:
            page = self.call("thread/loaded/list", {"limit": LIST_LIMIT, **({"cursor": cursor} if cursor else {})})
            loaded.update(page.get("data") or [])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        watched = self.controllers.watched_ids()
        with self.lock:
            retained = set(self.managed_metadata)
        for tid in (loaded | watched | retained) - fresh.keys():
            try:
                with self.lock:
                    if tid in self.removed_threads:
                        continue
                    cached = self.managed_metadata.get(tid)
                cached_at, saved = cached or (0, None)
                if saved is None or time.monotonic() - cached_at > 60:
                    saved = self.call("thread/read", {"threadId": tid, "includeTurns": False}).get("thread")
                    with self.lock:
                        if tid not in self.removed_threads and self.managed_metadata.get(tid) is cached:
                            self.managed_metadata[tid] = (time.monotonic(), saved)
                if saved:
                    fresh[tid] = saved
            except RpcError:
                pass
        with self.lock:
            # Creation/open/rename can finish while the list RPC is in flight.
            # Merge again under the lock, so an older list cannot erase it.
            for tid, (cached_at, saved) in self.managed_metadata.items():
                if saved and (tid not in fresh or cached_at >= started):
                    fresh[tid] = saved
                elif tid in fresh:
                    self.managed_metadata[tid] = (time.monotonic(), fresh[tid])
            fresh = {tid: t for tid, t in fresh.items() if tid not in self.removed_threads
                     and not t.get("parentThreadId") and not t.get("ephemeral")}
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
            busy = [tid for tid, r in summaries.items()
                    if r["status"] in ("running", "approval", "input") and tid not in self.subscribed]
        # Follow threads that are working elsewhere (e.g. in a terminal) so the list can
        # show what they are doing and for how long. They are already loaded.
        with self.lock:
            to_subscribe = set(busy) | self.pending_subscriptions
        for tid in to_subscribe:
            try:
                self.subscribe(tid)
                self.current_turn(tid)
            except (RpcError, Disconnected, TimeoutError):
                pass

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
                rows.append(dict(r, **live.get("settings", {}), tokens=live.get("tokens"),
                                 run=live.get("run") if r["status"] in ("running", "approval", "input") else None))
        return sorted(rows, key=lambda r: -r["updatedAt"])

    def set_run(self, tid, run):
        """Track the in-progress turn (start time and current activity) for lists and headers."""
        with self.lock:
            self.live.setdefault(tid, {})["run"] = run
        self.emit("run", threadId=tid, run=run)

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
            cached = self.managed_metadata.get(tid)
            if cached and cached[1]:
                self.managed_metadata[tid] = (time.monotonic(), dict(cached[1], status=status,
                                                                    updatedAt=new["updatedAt"]))
        if new["status"] in ("running", "approval", "input") and tid not in self.subscribed:
            self.refresh_soon.set()
        self.emit("threads", threads=self.thread_list())

    # ---- daemon callbacks (reader thread) ------------------------------
    def on_notification(self, method, params):
        self.controllers.post(method, params)
        tid = params.get("threadId")
        if method == "thread/status/changed":
            self.update_status(tid, params.get("status"))
        elif method in ("thread/archived", "thread/deleted"):
            self.forget_thread(tid)
        elif method in ("thread/started", "thread/name/updated", "thread/unarchived", "thread/closed"):
            with self.lock:
                if method == "thread/unarchived":
                    self.removed_threads.discard(tid)
                if method == "thread/closed":
                    self.managed_metadata.pop(tid, None)
                    self.subscribed.discard(tid)
                    self.pending_subscriptions.discard(tid)
                if method == "thread/name/updated":
                    # Invalidate cached metadata so renames from other clients appear too.
                    cached = self.managed_metadata.get(tid)
                    if cached:
                        self.managed_metadata[tid] = (0, cached[1])
            self.refresh_soon.set()
        elif method == "turn/started":
            turn = params["turn"]
            with self.lock:
                self.live.setdefault(tid, {})["turn"] = turn["id"]
            self.set_run(tid, {"turnId": turn["id"], "startedAt": turn.get("startedAt") or int(time.time()),
                               "activity": None})
            self.emit("turn", threadId=tid, turnId=turn["id"], state="started", startedAt=turn.get("startedAt"))
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            with self.lock:
                self.live.setdefault(tid, {})["turn"] = None
            self.set_run(tid, None)
            self.emit("turn", threadId=tid, turnId=turn.get("id"), state=turn.get("status"),
                      startedAt=turn.get("startedAt"), durationMs=turn.get("durationMs"),
                      error=(turn.get("error") or {}).get("message") if isinstance(turn.get("error"), dict) else None)
            self.refresh_soon.set()
        elif method in ("item/started", "item/completed"):
            item = params.get("item") or {}
            with self.lock:
                run = dict(self.live.get(tid, {}).get("run") or {})
            if run:
                if method == "item/started" and describe(item):
                    run.update(activity=describe(item), activityItem=item.get("id"))
                    self.set_run(tid, run)
                elif method == "item/completed" and run.get("activityItem") == item.get("id"):
                    run.update(activity=None, activityItem=None)
                    self.set_run(tid, run)
            self.emit("item", threadId=tid, turnId=params.get("turnId"),
                      done=method == "item/completed", item=normalize_item(item))
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
                self.live.setdefault(tid, {})["settings"] = {
                    "model": settings.get("model"), "effort": settings.get("effort"),
                    **permissions(settings.get("sandboxPolicy"), settings.get("approvalPolicy"))}
            self.emit("threads", threads=self.thread_list())
        elif method == "serverRequest/resolved":
            key = str(params.get("requestId"))
            with self.lock:
                gone = self.approvals.pop(key, None)
            if gone:
                self.emit("approvals", approvals=self.approval_list())

    def on_request(self, rid, method, params):
        if method == "item/tool/call" and str(params.get("tool", "")).startswith("ma4_"):
            self.controllers.request(self.client, rid, params)
            return
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
                return True
        params = {"threadId": tid, "excludeTurns": True}
        is_host = self.is_controller_host(tid)
        if is_host:
            # Cold resume also replaces the old host's read-only instructions.
            # No user message or model turn is created by this operation.
            params.update(sandbox="danger-full-access", approvalPolicy="never",
                          developerInstructions=HOST_INSTRUCTIONS,
                          config={"features.multi_agent": False})
        try:
            resumed = self.call("thread/resume", params, timeout=60)
        except RpcError as exc:
            if "no rollout found" not in str(exc) and "not materialized" not in str(exc):
                raise
            # After reconnect, an empty thread can still be loaded in memory but
            # cannot be resumed from disk until its first user turn is saved.
            metadata = self.call("thread/read", {"threadId": tid, "includeTurns": False}).get("thread")
            if not metadata or status_of(metadata) == "offline":
                raise exc
            return False  # addressable, but do not claim to be subscribed yet
        # Loaded threads can ignore resume overrides. Explicitly update their
        # subsequent-turn settings too, without interrupting an active turn.
        if is_host and (resumed.get("sandbox") != HOST_TOOL_SETTINGS["sandboxPolicy"]
                        or resumed.get("approvalPolicy") != "never"):
            self.call("thread/settings/update", {"threadId": tid, **HOST_TOOL_SETTINGS})
            resumed.update(sandbox=HOST_TOOL_SETTINGS["sandboxPolicy"], approvalPolicy="never")
        with self.lock:
            self.subscribed.add(tid)
            catch_up = tid in self.pending_subscriptions
            self.pending_subscriptions.discard(tid)
            if resumed.get("model"):
                self.live.setdefault(tid, {})["settings"] = {
                    "model": resumed["model"], "effort": resumed.get("reasoningEffort"),
                    **permissions(resumed.get("sandbox"), resumed.get("approvalPolicy"))}
        if catch_up:
            self.emit("history", threadId=tid)  # recover any items before subscription
        return True

    def read_turns(self, params, timeout=30):
        # Windows can briefly publish the rollout before its first bytes arrive.
        for attempt in range(4):
            try:
                return self.call("thread/turns/list", params, timeout=timeout)
            except RpcError as exc:
                if "rollout" not in str(exc) or "is empty" not in str(exc) or attempt == 3:
                    raise
                time.sleep((.05, .15, .4)[attempt])

    def current_turn(self, tid):
        with self.lock:
            known = self.live.get(tid, {}).get("turn")
        if known:
            return known
        try:
            page = self.read_turns({"threadId": tid, "limit": 1, "sortDirection": "desc",
                                                   "itemsView": "notLoaded"})
        except RpcError as exc:
            if "not materialized" in str(exc):
                return None  # brand-new thread: no turns before the first message
            raise
        turns = page.get("data") or []
        if turns and turns[0].get("status") == "inProgress":
            with self.lock:
                known_run = self.live.get(tid, {}).get("run")
            if not known_run:
                self.set_run(tid, {"turnId": turns[0]["id"], "activity": None,
                                   "startedAt": turns[0].get("startedAt") or int(time.time())})
            return turns[0]["id"]
        return None

    def open(self, tid):
        """Mark as seen and follow live events when the thread is already running."""
        if tid not in self.managed_metadata:
            result = self.call("thread/read", {"threadId": tid, "includeTurns": False})
            if result.get("thread"):
                with self.lock:
                    if tid in self.removed_threads:
                        raise ValueError("会话已归档或删除")
                    self.threads[tid] = self.summarize(result["thread"])
                    self.managed_metadata[tid] = (time.monotonic(), result["thread"])
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
        return {"thread": next((t for t in self.thread_list() if t["id"] == tid), None),
                "turn": self.current_turn(tid) if row and row["status"] != "offline" else None,
                "tokens": live.get("tokens"), "override": override}

    def history(self, tid, cursor=None, limit=8):
        params = {"threadId": tid, "limit": limit, "sortDirection": "desc", "itemsView": "full"}
        if cursor:
            params["cursor"] = cursor
        try:
            page = self.read_turns(params, timeout=60)
        except RpcError as exc:
            if "not materialized" in str(exc):
                return {"turns": [], "older": None}
            raise
        turns = []
        for turn in reversed(page.get("data") or []):
            turns.append({"id": turn["id"], "status": turn.get("status"), "startedAt": turn.get("startedAt"),
                          "completedAt": turn.get("completedAt"),
                          "durationMs": turn.get("durationMs"),
                          "error": (turn.get("error") or {}).get("message") if isinstance(turn.get("error"), dict) else None,
                          "items": [normalize_item(i) for i in turn.get("items") or []]})
        # A short page means there is nothing older, even if a cursor comes back.
        return {"turns": turns, "older": page.get("nextCursor") if len(turns) >= limit else None}

    def usage_snapshot(self, tid):
        """Recover only token counters from this known session's bounded rollout tail.

        The public thread read API currently has no cumulative usage field. Missing
        or changed local formats return None; callers must not invent a bill.
        """
        metadata = self.call("thread/read", {"threadId": tid, "includeTurns": False}).get("thread") or {}
        raw_path = metadata.get("path")
        if not raw_path:
            return None
        path = Path(raw_path).resolve()
        codex_home = Path(self.codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
        if not path.is_relative_to(codex_home):
            return None
        try:
            with path.open("rb") as f:
                f.seek(max(0, path.stat().st_size - 1024 * 1024))
                lines = f.read().splitlines()
            for line in reversed(lines):
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                payload = item.get("payload") or {}
                if item.get("type") == "event_msg" and payload.get("type") == "token_count":
                    total = (payload.get("info") or {}).get("total_token_usage")
                    if total:
                        return {camel: int(total.get(snake, 0)) for camel, snake in (
                            ("totalTokens", "total_tokens"), ("inputTokens", "input_tokens"),
                            ("cachedInputTokens", "cached_input_tokens"), ("outputTokens", "output_tokens"))}
        except (OSError, TypeError, ValueError):
            return None
        return None

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

    def skill_inputs(self, tid, selections):
        """Resolve explicitly selected attachments; message text is never parsed."""
        if selections is None:
            return []
        if not isinstance(selections, list) or len(selections) > 20:
            raise ValueError("Skill 附件需为列表，最多 20 项")
        if not selections:
            return []
        for choice in selections:
            if (not isinstance(choice, dict) or set(choice) != {"name", "path"}
                    or not all(isinstance(choice[k], str) and choice[k] for k in ("name", "path"))):
                raise ValueError("Skill 附件需包含已选技能的名称和路径")
        with self.lock:
            cwd = (self.threads.get(tid) or {}).get("cwd")
        if not cwd:
            raise ValueError("会话目录尚未载入，请重新打开后选择 Skill")
        available = {(s["name"], s["path"]) for s in self.skills(cwd)}
        result, seen = [], set()
        for choice in selections:
            key = (choice["name"], choice["path"])
            if key not in available:
                raise ValueError("所选 Skill 已不可用，请刷新页面后重新选择")
            if key not in seen:
                result.append({"type": "skill", **choice})
                seen.add(key)
        return result

    def send(self, tid, text, request_id, skills=None):
        if tid in self.controllers.member_ids():
            return self.controllers.invoke("send", tid=tid, message=text, request_id=request_id, skills=skills)
        return self.send_raw(tid, text, request_id, skills=skills)

    def send_raw(self, tid, text, request_id, *, skills=None):
        """Send verbatim text plus validated, explicitly selected attachments."""
        if not isinstance(text, str) or not text.strip() or len(text) > 50000:
            raise ValueError("消息需为 1–50000 个字符")
        with self.lock:
            if request_id in self.sent:
                return self.sent[request_id]
        subscribed = self.subscribe(tid)
        turn = self.current_turn(tid)
        message = [{"type": "text", "text": text, "text_elements": []}] + self.skill_inputs(tid, skills)
        if turn:
            self.call("turn/steer", {"threadId": tid, "expectedTurnId": turn, "input": message,
                                     "clientUserMessageId": request_id})
            result = {"mode": "steer", "turnId": turn}
        else:
            params = {"threadId": tid, "input": message, "clientUserMessageId": request_id}
            if self.is_controller_host(tid):
                params.update(HOST_TOOL_SETTINGS)
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
            if not subscribed:
                self.pending_subscriptions.add(tid)
            if len(self.sent) > 200:
                self.sent.pop(next(iter(self.sent)))
        self.refresh_soon.set()
        return result

    def is_controller_host(self, tid):
        return any(t.get("host") == tid for t in self.controllers.snapshot().get("tasks", []))

    def steer_only(self, tid, turn_id, text, request_id):
        """Deadline notice for exactly this turn; never start a new turn on a race."""
        return self.call("turn/steer", {"threadId": tid, "expectedTurnId": turn_id,
                                       "input": [{"type": "text", "text": text, "text_elements": []}],
                                       "clientUserMessageId": request_id})

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
            if tid in self.controllers.member_ids():
                raise ValueError("中控任务暂不支持会话内切换模型，以免金额单价失真；请使用普通会话切换")
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

    def new_thread(self, cwd, text=None, developer_instructions=None, dynamic_tools=None, sandbox=None, model=None,
                   approval_policy=None):
        path = Path(os.path.expanduser(cwd or "")).resolve()
        if not path.is_dir():
            raise ValueError("工作目录不存在：" + str(path))
        params = {"cwd": str(path)}
        if model:
            params["model"] = model
        if developer_instructions is not None:
            params["developerInstructions"] = developer_instructions
            params["config"] = {"features.multi_agent": False}
        if dynamic_tools is not None:
            params["dynamicTools"] = dynamic_tools
        if sandbox is not None:
            params["sandbox"] = sandbox
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        started = self.call("thread/start", params, timeout=60)
        tid = started["thread"]["id"]
        with self.lock:
            metadata = dict(started["thread"], cwd=str(path))
            self.threads[tid] = self.summarize(metadata)
            self.managed_metadata[tid] = (time.monotonic(), metadata)
            self.subscribed.add(tid)
            self.live.setdefault(tid, {})["settings"] = {
                "model": started.get("model"), "effort": started.get("reasoningEffort"),
                **permissions(started.get("sandbox"), started.get("approvalPolicy"))}
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
        with self.lock:
            if tid in self.threads:
                self.threads[tid]["name"] = name
            if tid in self.managed_metadata and self.managed_metadata[tid][1]:
                self.managed_metadata[tid] = (time.monotonic(), dict(self.managed_metadata[tid][1], name=name))
        self.emit("threads", threads=self.thread_list())
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

    def open_file(self, tid, reference):
        """Open a clicked local reference with the desktop, never via a shell or HTTP file server."""
        with self.lock:
            row = self.threads.get(tid)
        if not row:
            raise ValueError("未知会话")
        if not isinstance(reference, str) or not reference.strip() or len(reference) > 8192:
            raise ValueError("文件路径无效")
        path = reference.strip()
        if any(ord(c) < 32 for c in path):
            raise ValueError("文件路径含无效字符")
        if path.lower().startswith("file://"):
            uri = urlsplit(path)
            if uri.netloc not in ("", "localhost") or uri.query:
                raise ValueError("只支持本机文件")
            path = unquote(uri.path) + ("#" + uri.fragment if uri.fragment else "")
            if os.name == "nt" and re.match(r"^/[a-zA-Z]:/", path):
                path = path[1:]
        elif re.match(r"^[a-zA-Z]:[\\/]", path):
            if os.name != "nt":
                path = "/mnt/" + path[0].lower() + "/" + path[3:].replace("\\", "/")
        elif (re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", path)
              and not re.fullmatch(r"[^:]+:\d+(?::\d+)?(?:-\d+)?", path)):
            raise ValueError("只支持本地文件路径")
        if path.startswith(("//", "\\\\")):
            raise ValueError("只支持本机文件")

        def local(value):
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                if not row.get("cwd"):
                    raise ValueError("会话没有项目目录，无法解析相对路径")
                candidate = Path(row["cwd"]) / candidate
            return candidate.resolve()

        # Preserve actual filenames first; :line[:column] and #Lline are citations.
        target = local(path)
        if not target.exists():
            path = re.sub(r"(?::\d+(?::\d+)?(?:-\d+)?|#L\d+(?:C\d+)?(?:-L?\d+(?:C\d+)?)?)$", "", path)
            target = local(path)
        if not target.exists() and "%" in path:
            target = local(unquote(path))
        if not target.exists():
            raise ValueError("文件不存在，可能已移动或清理：" + str(target))
        if not (target.is_file() or target.is_dir()):
            raise ValueError("只能打开普通文件或目录")
        os_adapter().open_file(target)
        return {"opened": True}

    def open_terminal(self, tid):
        with self.lock:
            row = self.threads.get(tid)
        if not row:
            raise ValueError("未知会话")
        # A remote TUI must attach to exactly the same daemon as the page.
        self.current_turn(tid)
        return launch_terminal(self.codex_bin, self.socket_path,
                               row["cwd"] or str(Path.home()), tid, self.codex_home)

    def archive_thread(self, tid):
        if self.current_turn(tid):
            raise ValueError("会话仍在运行，不能归档")
        self.call("thread/archive", {"threadId": tid})
        self.forget_thread(tid)

    def forget_thread(self, tid):
        with self.lock:
            self.removed_threads.add(tid)
            self.threads.pop(tid, None)
            self.live.pop(tid, None)
            self.subscribed.discard(tid)
            self.pending_subscriptions.discard(tid)
            self.managed_metadata.pop(tid, None)
            self.model_override.pop(tid, None)
            self.prefs.seen.pop(tid, None)
            self.prefs.pinned.discard(tid)
            self.prefs.save()
        self.emit("threads", threads=self.thread_list())
        self.refresh_soon.set()

    def state(self):
        with self.lock:
            return {"threads": self.thread_list(), "approvals": self.approval_list(),
                    "daemon": dict(self.daemon), "seq": self.seq, "controllers": self.controllers.snapshot()}

    def close(self):
        self.controllers.close()
        self.stop.set()
        self.refresh_soon.set()
        if self.client:
            self.client.close()
