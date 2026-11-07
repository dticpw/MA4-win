"""Named, opt-in task flows: real HTTP + independent native Codex + local model.

list: no processes. run NAME... --scratch-root .agent-tmp/<task>/executor
Only fixed scenarios; no URL, code, RPC, external model or arbitrary plan input.
"""
import argparse
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.smoke_test import fixture
from tools.task_actions import TaskActions, require, timeout_value


class ControlledTaskModel:
    """Small Responses script. It cannot emit shell/code/file tools."""
    def __init__(self):
        self.lock = threading.Lock()
        self.commands = {}
        self.workers = {}
        self.calls = []
        self.tool_names = []

    def arm(self, tool, arguments, *, resume=False):
        require(tool in {"ma4_dispatch", "ma4_control"}, "unapproved mock tool")
        if tool == "ma4_control":
            require(arguments.get("action") in {"status", "wait"}, "unapproved control action")
        else:
            require(set(arguments) <= {"name", "instruction", "access", "write_scope", "session_id"}
                    and arguments.get("access") == "read" and arguments.get("write_scope") == [],
                    "mock dispatch may only create an isolated read-only worker")
            require(any(arguments.get("instruction") == w["instruction"] for w in self.workers.values()),
                    "only a registered fixed worker instruction is allowed")
        marker = "TASK-FLOW-COMMAND-" + uuid.uuid4().hex
        with self.lock:
            self.commands[marker] = {"tool": tool, "arguments": copy.deepcopy(arguments), "resume": resume}
        return marker

    def worker_instruction(self, *, hold=False):
        require(type(hold) is bool, "hold must be boolean")
        marker = "TASK-FLOW-WORKER-" + uuid.uuid4().hex
        instruction = "本机验证，只回复报告标记，不读取文件、不调用工具：" + marker
        gate = threading.Event()
        if not hold:
            gate.set()
        with self.lock:
            self.workers[marker] = {"instruction": instruction, "gate": gate,
                                    "started": threading.Event()}
        return instruction

    def release_all(self):
        for worker in self.workers.values():
            worker["gate"].set()

    @staticmethod
    def last_user(payload):
        inputs = payload.get("input", [])
        if not isinstance(inputs, list):
            return ""
        for row in reversed(inputs):
            if row.get("role") == "user":
                content = row.get("content", [])
                return content if isinstance(content, str) else "\n".join(
                    c.get("text", "") for c in content if isinstance(c, dict))
        return ""

    def response(self, payload):
        user = self.last_user(payload)
        tools = payload.get("tools", [])
        names = [t.get("name") or t.get("function", {}).get("name") for t in tools]
        self.tool_names = [n for n in names if n]
        with self.lock:
            for marker, command in list(self.commands.items()):
                if marker in user or (command["resume"] and "用户启动/恢复本任务" in user):
                    del self.commands[marker]
                    name = command["tool"]
                    # Native CLI versions may use a namespace in the wire name.
                    wire = next((n for n in names if n == name or (n and n.endswith("." + name))), name)
                    self.calls.append({"marker": marker, "tool": name, "wireName": wire})
                    return {"type": "function_call", "id": "fc_" + uuid.uuid4().hex,
                            "call_id": "call_" + uuid.uuid4().hex, "name": wire,
                            "arguments": json.dumps(command["arguments"], ensure_ascii=False),
                            "status": "completed"}, None
            gate = None
            text = "TASK-FLOW-ACK：本机模拟响应；未判定目标完成。"
            if "本次执行任务：" in user:
                for marker, worker in self.workers.items():
                    if marker in user:
                        worker["started"].set()
                        gate = worker["gate"]
                        text = "TASK-FLOW-REPORT " + marker
                        break
        return {"id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text", "text": text,
                                                        "annotations": []}]}, gate


def prepared(a):
    a.create()
    a.draft()
    a.confirm(explicit=True)


def confirmation(a):
    a.create()
    a.dispatch(expect_rejected=True)
    old = a.draft()["draftRevision"]
    a.draft()
    a.confirm(explicit=True, revision=old, expect_stale=True)
    a.confirm(explicit=True)
    a.pause()
    a.wait(condition="paused-settled")
    a.resume()
    a.pause()
    a.wait(condition="paused-settled")
    a.handoff()
    a.resume()
    a.record("fixed-budget-preserved", budget=a.task()["budget"], taskId=a.task()["id"])


def dispatch_report(a):
    prepared(a)
    a.dispatch()
    a.wait()
    reports = a.reports()
    require(len(reports) == 1 and all(r["delivered"] == 1 and r["status"] == "completed"
                                    for r in reports.values()), "one completed automatic report required")
    require(any("TASK-FLOW-REPORT" in i.get("text", "") for t in a.history(session="worker")
                for i in t["items"] if i["type"] == "agentMessage"), "worker final response absent")


def held_worker(a):
    prepared(a)
    a.dispatch(hold=True)
    a.wait(condition="worker-running")
    require(any(w["started"].is_set() and not w["gate"].is_set() for w in a.model.workers.values()),
            "mock did not hold an actual worker response")
    a.pause()
    a.wait(condition="paused-settled")
    a.model.release_all()
    rows = a.reports()
    require(len(rows) == 1 and all(r["pending"] == 1 and r["status"] == "interrupted"
                                 for r in rows.values()), "interrupted report must remain pending while paused")
    return rows


def pause_resume(a):
    held_worker(a)
    a.resume()
    a.wait()
    require(all(r["delivered"] == 1 for r in a.reports().values()), "resume lost pending report")
    a.dispatch(worker="worker")
    a.wait()
    rows = a.reports()
    require(len(a.task()["workers"]) == 1 and len(rows) == 2 and
            sorted(r["status"] for r in rows.values()) == ["completed", "interrupted"] and
            all(r["delivered"] == 1 for r in rows.values()), "worker reuse/report dedup failed")


def handoff(a):
    held_worker(a)
    a.handoff()
    a.dispatch(worker="retired-probe", expect_rejected=True, former=True)
    a.resume()
    a.wait()
    task = a.task()
    text = "\n".join(i.get("text", "") for t in a.history() for i in t["items"]
                     if i["type"] == "userMessage")
    require("TASK-FLOW-HANDOFF" in text and task["target"] in text and
            str(task["budget"]["deadline"]) in text and
            all(tid in text for tid in task["workers"]), "replacement missing necessary context")
    require(all(r["delivered"] == 1 for r in a.reports().values()), "handoff lost report")
    a.record("replacement-context", target=True, budget=True, workers=True, handoffSummary=True)


def reconnect_dedup(a):
    dispatch_report(a)
    before = a.reports()
    a.reconnect()
    require(a.reports() == before, "reconnect duplicated report")
    # Inject only the reply loss after a real native send succeeds. No task
    # dictionary, outbox, usage, status or report is assigned by this probe.
    # This is logic-boundary fault injection, NOT a real provider outage.
    a.pause()
    a.wait(condition="paused-settled")
    hub = a.f["hub"]
    original = hub.send_raw
    observed = []
    def lose_reply(tid, message, request_id, **kwargs):
        require(tid == a.owned["main"]["host"], "injection reached a foreign session")
        result = original(tid, message, request_id, **kwargs)
        observed.append({"requestId": request_id, "turnId": result["turnId"]})
        raise TimeoutError("TASK-FLOW injected lost acknowledgement after native acceptance")
    a.guard()
    hub.send_raw = lose_reply
    try:
        try:
            a.f["api"]("/api/tasks/resume", {"task_id": a.owned["main"]["id"]})
        except AssertionError as exc:
            require("HTTP 503" in str(exc) and "TASK-FLOW injected" in str(exc), str(exc))
        else:
            raise AssertionError("lost acknowledgement did not return HTTP 503")
    finally:
        hub.send_raw = original
    require(len(observed) == 1, "fault injected more than once")
    # Normal disconnect notification asks the production reconciler to inspect
    # native history. No direct reconcile/tick invocation is used.
    a.reconnect()
    a.wait(condition="host-idle")
    a._until(lambda: a.task()["diagnosis"]["code"] != "sending", "send reconciliation")
    marker = "[MA4 message:" + observed[0]["requestId"] + "]"
    matching = [t for t in a.history() if any(marker in i.get("text", "") for i in t["items"]
                                             if i["type"] == "userMessage")]
    require(len(matching) == 1 and matching[0]["id"] == observed[0]["turnId"], "uncertain send duplicated")
    require(a.reports() == before, "uncertain send changed existing reports")
    a.record("uncertain-send-reconciled", evidenceLayer="logic injection after real native acceptance",
             httpStatus=503, nativeTurns=1, automaticResends=0, **observed[0])


def failure_cleanup(a):
    a.create()
    a.record("intentional-failure", reason="verify nonzero CLI exit and owned fixture cleanup")
    raise AssertionError("TASK-FLOW intentional failure; this scenario must exit 1")


SCENARIOS = {
    "confirmation": (confirmation, "未确认拒绝、旧修订拒绝、固定预算跨暂停/恢复/交接"),
    "dispatch-report": (dispatch_report, "HTTP → 原生动态派工 → 执行者 → 自动报告"),
    "pause-resume": (pause_resume, "在途暂停、中断报告、恢复及同执行者续派"),
    "handoff": (handoff, "保留待回报/预算/执行者，拒绝前任工具，接任上下文"),
    "reconnect-dedup": (reconnect_dedup, "自有重连及接受后丢应答的逻辑注入核对去重"),
}
DEFAULT_SCENARIOS = tuple(SCENARIOS)
SCENARIOS["failure-cleanup"] = (failure_cleanup, "故意失败；应退出 1 并回收实例（不包含在 all）")


def local_directory(path):
    path = Path(path).absolute()
    require(path.resolve() == path and path.is_relative_to((ROOT / ".agent-tmp").resolve()),
            "scratch must be a non-linked directory under project .agent-tmp")
    require(path != ROOT / ".agent-tmp", "select your own task subdirectory")
    return path


@contextlib.contextmanager
def local_environment(path):
    names = ("MA4_TEST_SCRATCH", "TEMP", "TMP", "TMPDIR")
    previous = {k: os.environ.get(k) for k in names}
    old_temp = tempfile.tempdir
    for k in names:
        os.environ[k] = str(path)
    tempfile.tempdir = str(path)
    try:
        yield
    finally:
        tempfile.tempdir = old_temp
        for k, value in previous.items():
            if value is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = value


def run_scenario(name, scratch, timeout):
    require(name in SCENARIOS, "unknown scenario")
    result = {"name": name, "result": "failed", "steps": [],
              "modelBoundary": "real HTTP/native Codex; local scripted model; no external supplier"}
    f = a = None
    model = ControlledTaskModel()
    try:
        with local_environment(scratch), fixture(model_script=model) as f:
            a = TaskActions(f, timeout=timeout)
            result["instance"] = a.identity
            SCENARIOS[name][0](a)
            a.guard()
            result["result"] = "passed"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if a:
            result["steps"] = a.steps
        result["modelToolCalls"] = model.calls
        result["advertisedTaskTools"] = [n for n in model.tool_names if "ma4_" in n]
        if f:
            result["modelRequests"] = f["model"].request_count
            result["cleanup"] = {"backendExited": f["process"].poll() is not None,
                                 "webClosed": f["web"].fileno() == -1,
                                 "fixtureRemoved": not f["root"].exists()}
            if not all(result["cleanup"].values()):
                result["result"] = "failed"
                result["cleanupError"] = "owned fixture resources remain"
        else:
            result["cleanup"] = {"fixtureNotAcquired": True}
    return result


def source_versions():
    names = ["tools/task_actions.py", "tools/task_scenarios.py", "tools/smoke_test.py",
             "controllers.py", "hub.py", "server.py", "task_policy.py", "appserver.py", "runtime.py"]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "run"])
    parser.add_argument("scenarios", nargs="*", help="named scenarios or all")
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--output", type=Path, help="optional JSON under scratch-root")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    if args.command == "list":
        for name, (_, description) in SCENARIOS.items():
            print(name + "\t" + description)
        return 0
    try:
        timeout_value(args.timeout)
        require(args.scenarios and (args.scenarios == ["all"] or
                all(n in SCENARIOS for n in args.scenarios)), "choose named scenarios or all")
        require(len(set(args.scenarios)) == len(args.scenarios), "duplicate scenario")
        require(args.scratch_root is not None, "--scratch-root required")
        scratch = local_directory(args.scratch_root)
        output = args.output.absolute() if args.output else None
        if output:
            require(output.resolve() == output and output.is_relative_to(scratch) and
                    output.suffix == ".json" and not output.exists(), "output must be a new JSON inside scratch-root")
        scratch.mkdir(parents=True, exist_ok=True)
    except (AssertionError, OSError) as exc:
        parser.error(str(exc))
    names = list(DEFAULT_SCENARIOS) if args.scenarios == ["all"] else args.scenarios
    report = {"schemaVersion": 1, "python": sys.version.split()[0], "platform": sys.platform,
              "sources": source_versions(), "scenarios": [], "result": "passed"}
    for name in names:
        result = run_scenario(name, scratch, args.timeout)
        report["scenarios"].append(result)
        if result["result"] != "passed":
            report["result"] = "failed"
            report["notRun"] = names[len(report["scenarios"]):]
            break
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
