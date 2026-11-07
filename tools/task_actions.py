"""Finite task operations against an owned smoke fixture, never a live MA4 URL.

This is an HTTP/native-tool client, not another implementation of task policy.
Use task_scenarios.py for the opt-in native runner; importing starts no process.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, quote
import uuid

from tools.smoke_test import ROOT, doctor


def require(value, message):
    if not value:
        raise AssertionError(message)


def validate_identity(identity):
    """Check the complete descriptor before making even a read request."""
    try:
        v = identity["verification"]
        for field, scheme in ((identity["url"], "http"), (v["endpoint"], "ws")):
            u = urlsplit(field)
            require(u.scheme == scheme and u.hostname == "127.0.0.1" and
                    u.port is not None and u.port != 8764 and not u.username and
                    not u.password and not u.query and not u.fragment and not u.path,
                    "only isolated loopback endpoints are allowed")
        require(re.fullmatch(r"[a-f0-9]{32}", v["instance"]), "invalid instance ID")
        require(all(type(v[k]) is int and v[k] > 0 for k in ("ownerPid", "backendPid")),
                "complete process identity required")
        require(v["ownerPid"] == os.getpid(), "fixture belongs to another runner")
        root = Path(identity["cwd"])
        require(root.is_absolute() and root.resolve() == root and
                root.is_relative_to((ROOT / ".agent-tmp").resolve()), "external workspace refused")
        require(Path(v["codexHome"]) == root / "codex-home" and
                Path(v["dataDir"]) == root / "state", "home/data identity mismatch")
        require(isinstance(identity["backendVersion"], str) and identity["backendVersion"],
                "backend version required")
    except (KeyError, TypeError, ValueError) as exc:
        raise AssertionError("incomplete fixture identity") from exc
    return identity


def alias_value(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value),
            "use a local alias, not an ID, path, URL or code")
    return value


def timeout_value(value):
    require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 60,
            "timeout must be finite, positive and at most 60 seconds")
    return value


def validate_plan(plan):
    """Validate a bounded composition before any fixture is started."""
    require(isinstance(plan, list) and 0 < len(plan) <= 40, "plan requires 1..40 actions")
    known, workers, former, result = set(), {}, set(), []
    fields = {"create": set(), "draft": set(), "confirm": {"explicit"},
              "status": set(), "dispatch": {"worker"}, "wait": {"condition"},
              "pause": set(), "resume": set(), "handoff": set(), "reports": set(),
              "reconnect": set(), "history": {"session"}}
    for raw in plan:
        step = {"op": raw} if isinstance(raw, str) else copy.deepcopy(raw)
        require(isinstance(step, dict) and isinstance(step.get("op"), str) and
                step["op"] in fields, "unknown finite action")
        op = step["op"]
        require(set(step) <= {"op", "task"} | fields[op], "IDs/paths/URLs/code and unknown fields refused")
        name = alias_value(step.get("task", "main"))
        if op == "create":
            require(name not in known, "duplicate task alias")
            known.add(name)
            workers[name] = set()
        else:
            require(name in known, "create the task before acting on it")
        if op == "confirm":
            require(step.get("explicit") is True, "plan must explicitly confirm the draft")
        if op == "dispatch":
            alias_value(step.get("worker", "worker"))
            require(step.get("worker", "worker") not in {"host", "former"}, "reserved worker alias")
            workers[name].add(step.get("worker", "worker"))
        if op == "handoff":
            former.add(name)
        if op == "history":
            session = alias_value(step.get("session", "host"))
            require(session in {"host", "former"} or session in workers[name],
                    "history requires a worker alias created by this task in this plan")
            require(session != "former" or name in former, "history of former host requires handoff")
        if op == "wait":
            require(step.get("condition", "settled") in
                    {"settled", "host-idle", "worker-running", "paused-settled"}, "unknown wait condition")
        result.append({**step, "task": name})
    return result


def delivered_reports(histories):
    """Read actual worker_report envelopes, never count an ID mentioned in context."""
    rows = []
    for history in histories:
        for turn in history:
            for item in turn["items"]:
                message = item.get("text", "")
                if item["type"] != "userMessage" or "[MA4 source:worker_report]\n" not in message:
                    continue
                require("[MA4 content]\n" in message, "malformed report envelope")
                body = message.split("[MA4 content]\n", 1)[1]
                _, separator, raw = body.partition("\n")
                require(separator, "missing report payload")
                payload = json.loads(raw)
                require(isinstance(payload, list) and all(isinstance(r, dict) for r in payload),
                        "invalid report payload")
                rows.extend(payload)
    return rows


class TaskActions:
    """All IDs originate in this runner; no attach, arbitrary RPC or code action."""
    def __init__(self, fixture, *, timeout=30):
        self.f = fixture
        self.timeout = timeout_value(timeout)
        # Reject a supplied live/external descriptor before doctor does HTTP.
        self.identity = copy.deepcopy({"url": fixture["url"], "cwd": str(fixture["root"]),
            "verification": fixture["web"].runtime["verification"],
            "backendVersion": fixture["hub"].daemon.get("version")})
        validate_identity(self.identity)
        require(doctor(fixture) == self.identity, "fixture identity mismatch")
        self.model = fixture["model"].script
        require(self.model is not None, "controlled local model required")
        self.owned = {}
        self.steps = []
        self._creating = False
        self._transition = None
        self.guard()

    def record(self, operation, **details):
        row = {"step": len(self.steps) + 1, "operation": operation, **details}
        self.steps.append(row)
        return row

    def run(self, plan):
        plan = validate_plan(plan)
        operations = {"create": self.create, "draft": self.draft, "confirm": self.confirm,
                      "status": self.status, "dispatch": self.dispatch, "wait": self.wait,
                      "pause": self.pause, "resume": self.resume, "handoff": self.handoff,
                      "reports": self.reports, "reconnect": self.reconnect,
                      "history": self._history_step}
        for step in plan:
            operation = step.pop("op")
            name = step.pop("task")
            operations[operation](name, **step)
        return self.steps

    def status(self, name="main"):
        task = self.task(name)
        return self.record("status", task=name, taskId=task["id"], status=task["status"],
                           host=task["host"], workers=list(task["workers"]), budget=task["budget"],
                           pending=[p["id"] for p in task["pending"]])

    def _begin_transition(self, name, kind, *, new_worker=False):
        require(self._transition is None, "another owned operation is unresolved")
        task = self.task(name)
        self._transition = {"name": name, "kind": kind, "submitted": False,
                            "new_worker": new_worker, "candidate": None, "observed": None,
                            "expected": None, "workers": copy.deepcopy(task["workers"]),
                            "retries": 0, "deadline": None}

    def _submit_transition(self, kind):
        if self._transition is not None:
            require(self._transition["kind"] == kind and not self._transition["submitted"],
                    "unresolved operation: no additional writes or resends")
            self._transition.update(submitted=True, deadline=time.monotonic() + self.timeout)

    def guard(self):
        """Retry only a specific owned registration gap; never relax identity checks."""
        while True:
            tasks, unresolved = self._guard_once()
            if not unresolved:
                return tasks
            transition = self._transition
            require(transition is not None and transition["submitted"],
                    "foreign session/workspace in fixture")
            if time.monotonic() >= transition["deadline"]:
                self.record("ownership-snapshot-wait", task=transition["name"],
                            kind=transition["kind"], candidate=transition["observed"],
                            reads=transition["retries"], result="timeout", writes=0)
                raise AssertionError("timeout reconciling owned registration; foreign session remains unaccepted; no resend")
            transition["retries"] += 1
            time.sleep(.04)

    def _guard_once(self):
        validate_identity(self.identity)
        # Compare local objects first, so a changed URL never receives a request.
        require(self.f["url"] == self.identity["url"] and
                self.f["web"].runtime["verification"] == self.identity["verification"] and
                str(self.f["root"]) == self.identity["cwd"] and
                self.f["endpoint"] == self.identity["verification"]["endpoint"] and
                str(self.f["home"]) == self.identity["verification"]["codexHome"] and
                str(self.f["hub"].data_dir) == self.identity["verification"]["dataDir"] and
                self.f["hub"].socket_path == self.identity["verification"]["endpoint"] and
                self.f["hub"].codex_home == self.identity["verification"]["codexHome"] and
                self.f["process"].pid == self.identity["verification"]["backendPid"],
                "fixture descriptor changed")
        require(doctor(self.f) == self.identity, "fixture identity/version changed")
        state = self.f["api"]("/api/state")
        require(state["side"]["runtime"]["verification"] == self.identity["verification"] and
                state["side"]["runtime"]["defaultCwd"] == self.identity["cwd"] and
                state["daemon"]["version"] == self.identity["backendVersion"] and
                state["daemon"]["connected"], "HTTP instance identity changed")
        require(not state["controllers"].get("error"), "controller failed: " +
                str(state["controllers"].get("error")))
        tasks = {t["id"]: t for t in state["controllers"]["tasks"]}
        known = {o["id"] for o in self.owned.values()}
        require(self._creating or set(tasks) == known, "foreign task in fixture")
        transition = self._transition
        active = transition if transition and transition["submitted"] else None
        unresolved = False
        for name, owned in self.owned.items():
            require(owned["id"] in tasks, "owned task disappeared")
            task = tasks[owned["id"]]
            require(task["cwd"] == self.identity["cwd"], "task workspace changed")
            for grant in task.get("workspaces", []):
                require(grant["cwd"] == self.identity["cwd"], "external task grant")
            members = {task["host"], *task["formerHosts"], *task["workers"]}
            allowed = {owned["host"], *owned["former"], *owned["workers"].values()}
            if not active or active["name"] != name:
                require(members == allowed, "foreign session in task")
                require(task["host"] == owned["host"] and task["formerHosts"] == owned["former"]
                        and set(task["workers"]) == set(owned["workers"].values()), "task roles changed")
            elif active["kind"] == "dispatch":
                require(task["host"] == owned["host"] and task["formerHosts"] == owned["former"],
                        "dispatch changed controller roles")
                before = set(active["workers"])
                added = set(task["workers"]) - before
                require(before <= set(task["workers"]) and len(added) <= int(active["new_worker"]),
                        "dispatch changed unrelated worker membership")
                if added:
                    self._registration_candidate(next(iter(added)))
                if active["expected"]:
                    require(set(task["workers"]) == before | {active["expected"]},
                            "worker membership differs from native dispatch result")
            else:
                require(active["kind"] == "handoff" and task["workers"] == active["workers"],
                        "handoff changed original workers")
                if task["formerHosts"] == owned["former"]:
                    require(task["host"] == owned["host"], "handoff changed host without retirement")
                else:
                    require(task["formerHosts"] == owned["former"] + [owned["host"]],
                            "handoff changed unrelated former hosts")
                    if task["host"] is None:
                        unresolved = True
                    else:
                        self._registration_candidate(task["host"])
            for tid, worker in task["workers"].items():
                require(worker.get("cwd") == self.identity["cwd"] and worker["access"] == "read"
                        and worker["scope"] == [], "worker scope/ownership changed")
            if owned.get("budget"):
                require(task["budget"] == owned["budget"] and
                        task["target"] == owned["target"] and task["revision"] == owned["revision"],
                        "fixed budget or confirmed goal changed")
        # Every session, including not-yet-materialized empty hosts, is checked
        # against the task membership. No other user's session is adopted.
        members = {tid for t in tasks.values() for tid in
                   [t["host"], *t["formerHosts"], *t["workers"]]}
        unknown = set()
        for thread in state["threads"]:
            require(thread["cwd"] == self.identity["cwd"], "foreign session/workspace in fixture")
            if thread["id"] not in members:
                unknown.add(thread["id"])
        if unknown:
            require(active and (active["kind"] == "handoff" or active["new_worker"])
                    and len(unknown) == 1, "foreign session/workspace in fixture")
            tid = next(iter(unknown))
            require(active["observed"] in (None, tid) and active["candidate"] in (None, tid),
                    "registration changed candidate identity")
            active["observed"] = tid
            unresolved = True
        if active and active["observed"] and active["candidate"] != active["observed"]:
            unresolved = True  # disappearance alone is not proof of ownership
        return tasks, unresolved

    def _registration_candidate(self, tid):
        transition = self._transition
        owned_ids = {i for o in self.owned.values() for i in
                     [o["host"], *o["former"], *o["workers"].values()]}
        require(tid not in owned_ids and transition["candidate"] in (None, tid)
                and transition["observed"] in (None, tid), "registration changed candidate identity")
        if transition["expected"]:
            require(tid == transition["expected"], "registration differs from native dispatch result")
        transition["candidate"] = tid  # provisional only; never inserted into owned here

    def _record_registration(self, tid):
        transition = self._transition
        if transition["retries"]:
            self.record("ownership-snapshot-wait", task=transition["name"], kind=transition["kind"],
                        candidate=tid, reads=transition["retries"], result="confirmed", writes=0)

    def task(self, name="main"):
        alias_value(name)
        require(name in self.owned, "task was not created by this runner")
        return self.guard()[self.owned[name]["id"]]

    def _post(self, operation, task_alias, **data):
        if self._transition:
            require(not self._transition["submitted"], "unresolved operation: no additional writes or resends")
        task = self.task(task_alias)
        if self._transition:
            expected = "resume" if self._transition["kind"] == "dispatch" else "handoff"
            require(operation == expected and task_alias == self._transition["name"],
                    "unexpected operation during registration")
            self._submit_transition(self._transition["kind"])
        return self.f["api"]("/api/tasks/" + operation, {"task_id": task["id"], **data})

    def _until(self, predicate, label):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.08)
        raise AssertionError("timeout waiting for " + label + "; no automatic resend")

    def create(self, name="main"):
        require(self._transition is None, "another owned operation is unresolved")
        alias_value(name)
        require(name not in self.owned, "alias already created")
        self.guard()
        self._creating = True
        try:
            result = self.f["api"]("/api/tasks/create", {"cwd": self.identity["cwd"],
                "name": "任务流程验证 " + name, "request_id": uuid.uuid4().hex,
                "budget": {"durationMinutes": 10, "tokenLimit": 200000}})
            require(result["taskId"] not in {o["id"] for o in self.owned.values()}, "task reused")
            self.owned[name] = {"id": result["taskId"], "host": result["threadId"],
                                "former": [], "workers": {}}
        finally:
            self._creating = False
        self.task(name)
        return self.record("create", task=name, **result)

    def draft(self, name="main"):
        task = self.task(name)
        require(not task.get("goalConfirmed"), "draft action only prepares an unconfirmed test goal")
        result = self._post("update", name, name=task["name"],
            target="验证隔离任务的派工、暂停、交接及报告；只返回文本，不执行命令或修改文件。",
            budget=task["budget"], draft_revision=task["draftRevision"],
            workspaces=[{"cwd": self.identity["cwd"], "write_scope": []}])
        return self.record("draft", task=name, **result)

    def confirm(self, name="main", *, explicit=False, revision=None, expect_stale=False):
        require(explicit is True, "explicit confirmation required")
        task = self.task(name)
        require(task.get("draft") and task["draft"].get("target"), "draft required")
        current = task["draftRevision"]
        revision = current if revision is None else revision
        require(type(revision) is int, "integer revision required")
        require(expect_stale == (revision != current), "stale revision must be an explicit rejection probe")
        try:
            result = self._post("confirm", name, draft_revision=revision, name=task["name"],
                target=task["draft"]["target"], budget=task["draft"]["budget"], start=True,
                workspaces=task["draft"]["workspaces"])
        except AssertionError as exc:
            if not expect_stale or "HTTP 400" not in str(exc) or "草案已更新" not in str(exc):
                raise
            require(not self.task(name)["goalConfirmed"], "stale confirmation changed goal")
            return self.record("confirm-stale", task=name, status=400, error=str(exc))
        require(not expect_stale, "stale revision unexpectedly accepted")
        task = self.task(name)
        self.owned[name].update(budget=copy.deepcopy(task["budget"]), target=task["target"],
                                revision=task["revision"])
        require("deadline" in task["budget"] and "durationMinutes" not in task["budget"],
                "start did not resolve a fixed deadline")
        self.wait(name, "host-idle")
        return self.record("confirm", task=name, budget=task["budget"], **result)

    def wait(self, name="main", condition="settled"):
        require(condition in {"settled", "host-idle", "worker-running", "paused-settled"},
                "unknown finite wait condition")
        def reached():
            task = self.task(name)
            idle = not task["hostBusy"]
            workers_idle = all(w["state"] == "idle" for w in task["workers"].values())
            if idle and condition in {"host-idle", "settled"}:
                turns = self._history(self.owned[name]["host"])
                if turns and turns[-1]["status"] == "inProgress":
                    return None  # automatic report delivery started after the snapshot
                require(not turns or turns[-1]["status"] == "completed",
                        "idle host is not proof of a successful turn")
            if condition == "host-idle":
                return task if idle else None
            if condition == "worker-running":
                return task if any(w["state"] == "running" for w in task["workers"].values()) else None
            if condition == "paused-settled":
                return task if task["status"] == "paused" and idle and workers_idle else None
            return task if idle and workers_idle and not task["pending"] else None
        task = self._until(reached, condition)
        self.record("wait", task=name, condition=condition, status=task["status"],
                    pending=len(task["pending"]))
        return task

    def _history(self, tid):
        self.guard()
        allowed = {i for o in self.owned.values() for i in
                   [o["host"], *o["former"], *o["workers"].values()]}
        require(tid in allowed, "foreign history session")
        turns, cursor = [], None
        for _ in range(12):
            page = self.f["api"]("/api/history?id=" + quote(tid) +
                ("&cursor=" + quote(cursor) if cursor else ""))
            turns = page["turns"] + turns
            cursor = page.get("older")
            if not cursor:
                require(len({t["id"] for t in turns}) == len(turns), "duplicate history turn")
                return turns
        raise AssertionError("history exceeded bounded page limit")

    def history(self, name="main", session="host"):
        self.task(name)
        owned = self.owned[name]
        if session == "host":
            tid = owned["host"]
        elif session == "former":
            require(owned["former"], "no former host")
            tid = owned["former"][-1]
        else:
            alias_value(session)
            require(session in owned["workers"], "worker was not created by this runner")
            tid = owned["workers"][session]
        return self._history(tid)

    def _history_step(self, name="main", session="host"):
        """Record a compact summary only for composed reads; history() stays unchanged."""
        turns = self.history(name, session)
        owned = self.owned[name]
        tid = (owned["host"] if session == "host" else owned["former"][-1]
               if session == "former" else owned["workers"][session])
        summary = [{"id": turn["id"], "status": turn["status"],
                    "itemCount": len(turn["items"]),
                    "itemsSha256": hashlib.sha256(json.dumps(turn["items"], sort_keys=True,
                        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()}
                   for turn in turns]
        return self.record("history", task=name, session=session, threadId=tid,
                           turnCount=len(turns), itemCount=sum(t["itemCount"] for t in summary),
                           turns=summary)

    def _tool(self, name, tool, arguments, *, former=False, resume=False):
        task = self.task(name)
        require(not task["hostBusy"], "wait for host before requesting a tool")
        owned = self.owned[name]
        tid = owned["former"][-1] if former else owned["host"]
        marker = self.model.arm(tool, arguments, resume=resume)
        message = "执行本机预设验证步骤 " + marker
        self.guard()
        if resume:
            previous = {t["id"] for t in self._history(tid)}
            self._post("resume", name)
            turn_id = self._until(lambda: next((t["id"] for t in self._history(tid)
                                                if t["id"] not in previous), None), "resumed tool turn")
        elif former:
            # HTTP correctly refuses former-host sends. A separately owned native
            # client probes that the retired native dynamic tool is also refused.
            sent = self.f["client"].call("turn/start", {"threadId": tid,
                "input": [{"type": "text", "text": message, "text_elements": []}]})
            turn_id = sent["turn"]["id"]
        else:
            self._submit_transition("dispatch")
            sent = self.f["api"]("/api/send", {"id": tid, "text": message,
                                                 "request_id": uuid.uuid4().hex})
            require(sent.get("mode") == "start", "tool probe unexpectedly steered")
            turn_id = sent["turnId"]
        def result():
            turn = next((t for t in self._history(tid) if t["id"] == turn_id), None)
            if not turn or turn["status"] == "inProgress":
                return None
            require(turn["status"] == "completed", "native tool turn failed: " + str(turn.get("error")))
            calls = [i for i in turn["items"] if i["type"] == "dynamicToolCall" and i["tool"] == tool]
            require(len(calls) == 1, "expected exactly one native dynamic tool call")
            return calls[0]
        item = self._until(result, "native " + tool)
        self.record("native-tool", task=name, threadId=tid, turnId=turn_id,
                    tool=tool, success=item.get("success"), output=item.get("output"))
        return item

    def dispatch(self, name="main", worker="worker", *, hold=False, expect_rejected=False, former=False):
        require(self._transition is None, "another owned operation is unresolved")
        alias_value(worker)
        require(worker not in {"host", "former"} and
                all(type(v) is bool for v in (hold, expect_rejected, former)), "invalid dispatch options")
        task = self.task(name)
        if not expect_rejected:
            require(task["goalConfirmed"] and not task.get("draft") and
                    task["status"] in {"running", "waiting", "review", "attention"},
                    "confirm/resume the task before dispatch")
        owned = self.owned[name]
        require(not former or (expect_rejected and owned["former"]), "former-host probe requires rejection")
        args = {"name": "验证执行者 " + worker, "access": "read", "write_scope": [],
                "instruction": self.model.worker_instruction(hold=hold)}
        if worker in owned["workers"]:
            args["session_id"] = owned["workers"][worker]
        before = set(task["workers"])
        # An idle controller naturally becomes attention. Resume is an explicit
        # action of this finite combination, using the existing fixed budget.
        if not expect_rejected:
            self._begin_transition(name, "dispatch", new_worker=worker not in owned["workers"])
        try:
            item = self._tool(name, "ma4_dispatch", args, former=former,
                              resume=not expect_rejected and task["status"] == "attention")
            current = self.task(name)
            if expect_rejected:
                require(item.get("success") is False and set(current["workers"]) == before,
                        "rejected dispatch changed workers or succeeded")
                error = json.loads(item["output"]).get("error")
                require(error == ("仅当前中控可调用本任务工具" if former else "任务未启动、已暂停或正在交接"),
                        "dispatch failed for an unexpected reason: " + str(error))
            else:
                require(item.get("success") is True, "dispatch rejected: " + str(item.get("output")))
                result = json.loads(item["output"])
                tid = result["session_id"]
                self._transition["expected"] = tid
                current = self.task(name)
                require(set(current["workers"]) == before | {tid} and
                        (tid == owned["workers"].get(worker) or tid not in before), "invalid new worker identity")
                require(not self._transition["new_worker"] or self._transition["candidate"] == tid,
                        "new worker does not match native dispatch result")
                self._record_registration(tid)
                owned["workers"][worker] = tid
        finally:
            self._transition = None
        self.task(name)
        return item

    def pause(self, name="main"):
        result = self._post("pause", name, reason="具名场景暂停")
        require(result.get("paused") and not result.get("interruptErrors"), "pause interruption unconfirmed")
        self.record("pause", task=name, **result)
        return result

    def resume(self, name="main"):
        task = self.task(name)
        require(task["goalConfirmed"] and not task.get("draft") and not task["hostBusy"] and
                all(w["state"] == "idle" for w in task["workers"].values()), "resume preconditions not met")
        result = self._post("resume", name)
        self.record("resume", task=name, **result)
        self.wait(name, "host-idle")
        return result

    def handoff(self, name="main"):
        require(self._transition is None, "another owned operation is unresolved")
        task = self.task(name)
        require(not task["hostBusy"] and not task.get("handoff"), "handoff requires idle host")
        owned = self.owned[name]
        old = owned["host"]
        self._begin_transition(name, "handoff")
        try:
            self._post("handoff", name, summary="TASK-FLOW-HANDOFF：保留原任务、固定预算、执行者和已有报告；逐项核对后继续。")
            current = self._until(lambda: (t if (t := self.task(name))["host"] != old else None), "replacement host")
            require(current["host"] and old in current["formerHosts"] and
                    current["workers"] == task["workers"] and current["pending"] == task["pending"],
                    "handoff did not preserve workers/reports")
            require(current["host"] == self._transition["candidate"], "handoff host not confirmed")
            self._record_registration(current["host"])
            owned["former"].append(old)
            owned["host"] = current["host"]
        finally:
            self._transition = None
        self.record("handoff", task=name, previous=old, current=owned["host"],
                    retainedReports=[p["id"] for p in current["pending"]])
        return current

    def reports(self, name="main"):
        task = self.task(name)
        result = {}
        host_histories = [self._history(tid) for tid in
                          [self.owned[name]["host"], *self.owned[name]["former"]]]
        delivered_rows = delivered_reports(host_histories)
        for worker, tid in self.owned[name]["workers"].items():
            for turn in self._history(tid):
                if turn["status"] not in {"completed", "interrupted", "failed"}:
                    continue
                report_id = tid + ":" + turn["id"]
                delivered = sum(row["id"] == report_id for row in delivered_rows)
                pending = sum(p["id"] == report_id for p in task["pending"])
                require(delivered + pending == 1, "report missing/duplicated: " + report_id)
                row = next(r for r in delivered_rows + task["pending"] if r["id"] == report_id)
                require(row["threadId"] == tid and row["turnId"] == turn["id"] and
                        row["status"] == turn["status"] and row["cwd"] == task["cwd"] and
                        row["targetRevision"] == task["revision"] and row["access"] == "read" and
                        row["write_scope"] == [], "report ownership/status/revision mismatch")
                final = "\n".join(i.get("text", "") for i in turn["items"]
                                  if i["type"] == "agentMessage" and i.get("phase") != "commentary")
                if final:
                    require(row["report"] == final, "delivered report differs from native final response")
                result[report_id] = {"worker": worker, "status": turn["status"],
                                     "delivered": delivered, "pending": pending,
                                     "contentMatchesNative": bool(final)}
        require(result, "no completed worker reports to verify")
        self.record("reports", task=name, reports=result)
        return result

    def reconnect(self, name="main"):
        before = self.task(name)
        client = self.f["hub"].client
        require(client is not None and not client.closed, "owned connection already closed")
        client.close()
        self._until(lambda: self.f["hub"].client is not None and self.f["hub"].client is not client and
                    not self.f["hub"].client.closed and self.f["hub"].daemon["connected"] and
                    not self.f["hub"].controllers.snapshot().get("recovering"), "owned reconnect")
        after = self.task(name)
        require(after["host"] == before["host"] and set(after["workers"]) == set(before["workers"]),
                "reconnect changed ownership")
        self.record("reconnect", task=name, backendPid=self.f["process"].pid,
                    independentClientStillConnected=not self.f["client"].closed)
        return after
