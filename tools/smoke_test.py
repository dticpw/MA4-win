"""Offline end-to-end check: real Codex, a local mock model, Hub and HTTP/SSE.

Never uses the user's CODEX_HOME, credentials, model quota or existing threads.
--serve leaves the isolated fixture available briefly for browser/terminal QA.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from appserver import AppServer
from hub import Hub
from runtime import child_environment, find_codex
from server import Server


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError("condition not reached within %ss" % timeout)


class MockModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.request_count += 1
        script = getattr(self.server, "script", None)
        if script is not None:
            return self.scripted_response(script, json.loads(body))
        message_id = "msg_" + uuid.uuid4().hex
        response_id = "resp_" + uuid.uuid4().hex
        text = "本机模拟回复：Windows 共享会话连接成功。"
        item = {"id": message_id, "type": "message", "role": "assistant",
                "status": "completed", "content": [
                    {"type": "output_text", "text": text, "annotations": []}]}
        events = [
            {"type": "response.created", "response": {"id": response_id, "object": "response",
                "status": "in_progress", "output": []}},
            {"type": "response.output_item.added", "output_index": 0,
                "item": dict(item, status="in_progress", content=[])},
            {"type": "response.content_part.added", "item_id": message_id, "output_index": 0,
                "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}},
        ]
        events += [{"type": "response.output_text.delta", "item_id": message_id,
                    "output_index": 0, "content_index": 0, "delta": chunk}
                   for chunk in ("本机模拟回复：", "Windows 共享会话", "连接成功。")]
        events += [
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {
                "id": response_id, "object": "response", "status": "completed",
                "output": [item], "usage": {"input_tokens": 1, "output_tokens": 8, "total_tokens": 9}}},
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in events:
                self.wfile.write(("event: " + event["type"] + "\ndata: " +
                                  json.dumps(event, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
                if event["type"] == "response.created":
                    self.server.request_started.set()
                    # Keep the steer test active until it explicitly interrupts.
                    # A fixed sleep is not a reliable turn boundary across CLI versions.
                    if not self.server.release_response.wait(15):
                        return
                time.sleep(self.server.delay)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        self.close_connection = True

    def scripted_response(self, script, payload):
        """Opt-in local model hook; the ordinary smoke response is unchanged."""
        response_id = "resp_" + uuid.uuid4().hex
        item, gate = script.response(payload)
        events = [
            {"type": "response.created", "response": {"id": response_id,
                "object": "response", "status": "in_progress", "output": []}},
            {"type": "response.output_item.added", "output_index": 0,
                "item": dict(item, status="in_progress")},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": response_id,
                "object": "response", "status": "completed", "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 8, "total_tokens": 9}}},
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in events:
                self.wfile.write(("event: " + event["type"] + "\ndata: " +
                    json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                if event["type"] == "response.created" and gate is not None:
                    if not gate.wait(45):
                        return
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        self.close_connection = True


class Side:
    def __init__(self, value):
        self.value = value

    def snapshot(self):
        return self.value


def stop_owned_process(process):
    """Only the Popen handle created by this fixture; never discover other PIDs."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextlib.contextmanager
def fixture(port=0, *, model_script=None):
    temp_parent = Path(os.environ.get("MA4_TEST_SCRATCH", ROOT / ".agent-tmp")).resolve()
    if not temp_parent.is_relative_to((ROOT / ".agent-tmp").resolve()):
        raise ValueError("fixture scratch must stay under project .agent-tmp")
    if port == 8764:
        raise ValueError("fixture refuses live port 8764")
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smoke-", dir=temp_parent) as directory, contextlib.ExitStack() as resources:
        work = Path(directory).resolve()
        assert work.is_relative_to(temp_parent.resolve())
        home = work / "codex-home"
        home.mkdir()
        model = ThreadingHTTPServer(("127.0.0.1", 0), MockModel)
        model.daemon_threads = True
        model.request_count = 0
        model.script = model_script
        model.delay = .04
        model.request_started = threading.Event()
        model.release_response = threading.Event()
        model.release_response.set()
        threading.Thread(target=model.serve_forever, daemon=True).start()
        resources.callback(model.server_close)
        resources.callback(model.shutdown)
        (home / "config.toml").write_text(
            'model = "gpt-5"\nmodel_provider = "mock"\napproval_policy = "never"\n'
            'sandbox_mode = "read-only"\n[features]\nplugins = false\napps = false\ncode_mode_host = false\n[model_providers.mock]\nname = "MA4 local test"\n'
            'base_url = "http://127.0.0.1:%d/v1"\nwire_api = "responses"\n'
            'requires_openai_auth = false\n' % model.server_port, encoding="utf-8", newline="\n")
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            endpoint = "ws://127.0.0.1:%d" % free.getsockname()[1]
        binary = find_codex()
        with (work / "backend.log").open("w", encoding="utf-8", newline="\n") as log:
            env = child_environment(binary, home)
            # Opt-in task scenarios must not inherit credentials or global homes.
            if model_script is not None:
                env = {k: v for k, v in env.items() if k.upper() in {
                    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                    "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}}
                profile = work / "profile"
                profile.mkdir()
                env.update(CODEX_HOME=str(home), HOME=str(profile), USERPROFILE=str(profile),
                           APPDATA=str(profile / "AppData/Roaming"),
                           LOCALAPPDATA=str(profile / "AppData/Local"),
                           TEMP=str(work), TMP=str(work), TMPDIR=str(work))
            options = {"env": env, "stdin": subprocess.DEVNULL,
                       "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen([binary, "app-server", "--listen", endpoint], **options)
            resources.callback(stop_owned_process, process)
            client = hub = web = None
            try:
                for _ in range(100):
                    try:
                        client = AppServer(endpoint, client_name="ma4_smoke_terminal")
                        resources.callback(client.close)
                        break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError("test backend exited")
                        time.sleep(.05)
                if client is None:
                    raise RuntimeError("test backend did not start")
                hub = Hub(work / "state", binary, endpoint, poll_seconds=.1, codex_home=str(home))
                resources.callback(hub.close)
                hub.start()
                wait_for(lambda: hub.daemon["connected"])
                web = Server(("127.0.0.1", port), hub,
                             Side({"families": [], "error": "测试未连接额度来源"}),
                             Side([]), [{"name": "muQ", "url": "https://muq.koa-ol.com"}],
                             runtime={"home": str(Path.home()), "defaultCwd": str(work), "platform": os.name,
                                      "verification": {"instance": uuid.uuid4().hex, "ownerPid": os.getpid(),
                                                       "backendPid": process.pid, "endpoint": endpoint,
                                                       "codexHome": str(home), "dataDir": str(work / "state")}})
                threading.Thread(target=web.serve_forever, daemon=True).start()
                resources.callback(web.server_close)
                resources.callback(web.shutdown)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                base = "http://127.0.0.1:%d" % web.server_port

                def api(path, data=None):
                    req = urllib.request.Request(base + path,
                        data=json.dumps(data).encode() if data is not None else None,
                        headers={"X-MA4-Request": "1", "Content-Type": "application/json"})
                    try:
                        with opener.open(req, timeout=15) as response:
                            return json.load(response)
                    except urllib.error.HTTPError as exc:
                        raise AssertionError("HTTP " + str(exc.code) + " " + path + " " + exc.read().decode()) from exc

                yield {"root": work, "home": home, "binary": binary, "endpoint": endpoint,
                       "client": client, "hub": hub, "web": web, "model": model, "api": api, "url": base,
                       "process": process}
            finally:
                model.release_response.set()
                if model_script is not None:
                    model_script.release_all()


def checks(f):
    api, client, hub = f["api"], f["client"], f["hub"]
    # Empty new threads must remain visible until their first turn is persisted.
    tid = api("/api/new", {"cwd": str(f["root"]), "text": ""})["threadId"]
    wait_for(lambda: any(t["id"] == tid for t in api("/api/state")["threads"]))
    assert api("/api/history?id=" + tid)["turns"] == []
    first = api("/api/send", {"id": tid, "text": "离线端到端验证", "request_id": "smoke-first"})
    wait_for(lambda: len(api("/api/history?id=" + tid)["turns"]) >= 1)
    wait_for(lambda: api("/api/history?id=" + tid)["turns"][-1]["status"] == "completed")
    assert api("/api/send", {"id": tid, "text": "离线端到端验证", "request_id": "smoke-first"}) == first
    assert client.call("thread/resume", {"threadId": tid, "excludeTurns": True})["thread"]["id"] == tid

    # A second client starts a turn; the real Hub gets deltas and completion.
    since = hub.seq
    notes = []
    client.on_notification = lambda m, p: notes.append((m, p))
    client.call("turn/start", {"threadId": tid, "input": [
        {"type": "text", "text": "从第二个客户端发起", "text_elements": []}]})
    wait_for(lambda: any(m == "turn/completed" for m, p in notes))
    events = [e for seq, e in hub.events if seq > since]
    assert any(e["kind"] == "delta" for e in events)
    assert any(e["kind"] == "turn" and e["state"] == "completed" for e in events)
    assert any(m == "item/agentMessage/delta" for m, p in notes)

    # Send during an active turn -> steer, then interrupt that same turn.
    f["model"].request_started.clear()
    f["model"].release_response.clear()
    try:
        result = api("/api/send", {"id": tid, "text": "测试插话和中断", "request_id": "smoke-slow"})
        assert result["mode"] == "start", result
        assert f["model"].request_started.wait(10), "mock request did not start"
        wait_for(lambda: hub.current_turn(tid) == result["turnId"])
        steered = api("/api/send", {"id": tid, "text": "追加一条输入", "request_id": "smoke-steer"})
        assert steered["mode"] == "steer", {"started": result, "steered": steered}
        assert steered["turnId"] == result["turnId"]
        api("/api/interrupt", {"id": tid})
    finally:
        f["model"].release_response.set()
    wait_for(lambda: api("/api/history?id=" + tid)["turns"][-1]["status"] == "interrupted")
    api("/api/rename", {"id": tid, "name": "Windows 接入验证 · 本机模拟回复"})
    api("/api/pin", {"id": tid, "pinned": True})

    # Disconnect/reconnect only the workbench. The separate client's thread stays loaded.
    hub.client.close()
    wait_for(lambda: hub.daemon["connected"] and hub.client is not None and not hub.client.closed)
    assert tid in client.call("thread/loaded/list", {})["data"]
    api("/api/send", {"id": tid, "text": "重连后继续", "request_id": "smoke-after-reconnect"})
    wait_for(lambda: api("/api/history?id=" + tid)["turns"][-1]["status"] == "completed")

    # Verify actual SSE serialization through the HTTP server.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f["url"] + "/api/events?since=" + str(hub.seq), timeout=3) as stream:
        hub.emit("smoke_check", threadId=tid)
        line = stream.readline()
        assert line.startswith(b"id:"), line
        assert b"smoke_check" in stream.readline()

    summary = {"result": "passed", "backend": client.info["userAgent"],
               "tests": ["empty_thread", "http_send_history", "send_deduplication",
                         "shared_stream", "steer", "interrupt", "rename_pin",
                         "reconnect_preserves_backend", "http_sse"],
               "model": "local mock; no external model calls"}
    return tid, summary


def doctor(f):
    """Check objects owned by this fixture and the same identity over real HTTP."""
    state = f["api"]("/api/state")
    runtime = state["side"]["runtime"]
    identity = f["web"].runtime["verification"]
    if (f["process"].poll() is not None or identity["backendPid"] != f["process"].pid
            or identity["ownerPid"] != os.getpid()):
        raise RuntimeError("验证实例的进程归属不符或后台已退出")
    if (f["web"].server_port == 8764 or f["url"] != f"http://127.0.0.1:{f['web'].server_port}"
            or not f["root"].is_relative_to(ROOT / ".agent-tmp")
            or f["hub"].data_dir != f["root"] / "state"
            or f["home"] != f["root"] / "codex-home"
            or identity["endpoint"] != f["endpoint"]
            or identity["dataDir"] != str(f["hub"].data_dir)
            or identity["codexHome"] != str(f["home"])):
        raise RuntimeError("验证实例的端口、后台或数据目录不符")
    if (runtime.get("verification") != identity or runtime.get("defaultCwd") != str(f["root"])
            or not state["daemon"].get("connected") or not state["daemon"].get("version")):
        raise RuntimeError("HTTP 实例身份不符或后台未就绪")
    return {"url": f["url"], "cwd": str(f["root"]), "verification": identity,
            "backendVersion": state["daemon"]["version"]}


def browser_checks(f, output, plan=None, message=None):
    output.mkdir(parents=True, exist_ok=True)
    identity = doctor(f)
    env = os.environ.copy()
    env["MA4_VERIFY_INSTANCE"] = json.dumps(identity)
    env.pop("MA4_SESSION_PLAN", None)
    env.pop("MA4_SESSION_MESSAGE", None)
    if plan:
        env["MA4_SESSION_PLAN"] = plan
    if message:
        env["MA4_SESSION_MESSAGE"] = message
    command = ["node", str(ROOT / "tools/ui_check.mjs"), "", str(output), f["url"], "--exercise"]
    result = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL)
    report_file = output / "report.json"
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
    passed = result.returncode == 0 and report.get("result") == "passed" and bool(report.get("journeys"))
    doctor(f)
    return {"result": "passed" if passed else "failed", "browserExitCode": result.returncode,
            "instance": identity, "journeys": report.get("journeys", []), "argv": command,
            "compatibility": report.get("compatibility"),
            "modelRequests": f["model"].request_count,
            "model": "local mock; no external model calls; excludes the real executor's model use", "ui_report": "ui/report.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ui-output", type=Path, help="仅运行隔离真实页面流程，输出审查证据")
    parser.add_argument("--session-plan", help="有限 JSON 动作数组，由 session_actions 校验")
    parser.add_argument("--message", help="动作 send 的默认消息")
    parser.add_argument("--scratch-root", type=Path, help="项目临时区内新目录；fixture/cache 退出自动回收")
    args = parser.parse_args()
    if args.ui_output and (args.serve or args.port):
        parser.error("--ui-output 只使用本次随机端口，不与 --serve/--port 合用")
    if (args.session_plan or args.message or args.scratch_root) and not args.ui_output:
        parser.error("session options require --ui-output")
    with contextlib.ExitStack() as stack:
        runtime = None
        if args.ui_output:
            parent = (args.scratch_root or Path(os.environ.get("MA4_TEST_SCRATCH", ROOT / ".agent-tmp"))).resolve()
            if not parent.is_relative_to((ROOT / ".agent-tmp").resolve()):
                parser.error("scratch must be inside project .agent-tmp")
            if args.scratch_root and parent.exists():
                parser.error("--scratch-root must be new")
            if args.scratch_root:
                parent.parent.mkdir(parents=True, exist_ok=True)
                runtime = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix=parent.name + "-", dir=parent.parent)))
            else:
                parent.mkdir(parents=True, exist_ok=True)
                runtime = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="session-runtime-", dir=parent)))
            os.environ.update(MA4_TEST_SCRATCH=str(runtime), TEMP=str(runtime), TMP=str(runtime), TMPDIR=str(runtime))
        f = stack.enter_context(fixture(args.port))
        if args.ui_output:
            summary = browser_checks(f, args.ui_output, args.session_plan, args.message)
        else:
            tid, summary = checks(f)
        if not args.ui_output:
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        if args.output and not args.ui_output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
        if args.serve:
            descriptor = ROOT / ".agent-tmp/ui-fixture.json"
            stop = ROOT / ".agent-tmp/ui-fixture.stop"
            if stop.exists():
                stop.unlink()
            descriptor.write_text(json.dumps({
                "url": f["url"], "endpoint": f["endpoint"], "threadId": tid,
                "codexHome": str(f["home"]), "binary": f["binary"],
                "cwd": str(f["root"]), "ownerPid": os.getpid()},
                ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
            print("FIXTURE " + f["url"] + " · stop via .agent-tmp/ui-fixture.stop; max 20 minutes", flush=True)
            deadline = time.monotonic() + 1200
            try:
                while not stop.exists() and time.monotonic() < deadline:
                    time.sleep(.2)
            finally:
                descriptor.unlink(missing_ok=True)
                stop.unlink(missing_ok=True)
    if args.ui_output:
        summary["cleanup"] = {"backendExited": f["process"].poll() is not None,
                              "ownWebClosed": f["web"].fileno() == -1,
                              "scratchRemoved": not f["root"].exists(),
                              "runtimeRemoved": runtime is not None and not runtime.exists()}
        if not all(summary["cleanup"].values()):
            raise RuntimeError("真实页面检查结束后仍有本次实例资源未回收")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        if args.output:
            args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
        if summary["result"] != "passed":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

