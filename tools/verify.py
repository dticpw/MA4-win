"""Run existing MA4 checks by feature; never connects to the live workbench."""
import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Explicit lists: discovery would also run image-preview tests requiring a
# separately authorized MA4 task directory. Keep that prerequisite intact.
PROFILES = {
    "sessions": ("会话创建、发送、历史、审批、Skill 与文件链接",
                 ("test_hub", "test_server"),
                 ("test_markdown.mjs", "test_paths.mjs"),
                 ("session_creation_check", "skill_selection_check")),
    "tasks": ("目标确认、预算、派工、报告回传与恢复",
              ("test_controllers", "test_task_policy"), ("test_controllers.mjs",),
              ("controller_discussion_check", "controller_details_check")),
    "side": ("活动、健康、额度；使用模拟来源",
             ("test_activity", "test_health", "test_quota", "test_server"), (),
             ("service_activity_check",)),
    "platform": ("传输、配置、路径与启动器；含隔离本机进程测试",
                 ("test_appserver", "test_runtime", "test_platform", "test_desktop"),
                 ("test_paths.mjs",), ()),
    "tooling": ("验证入口的选择、失败传播、输出和静态服务边界",
                ("test_verify", "test_feature_map", "test_task_actions", "test_task_scenarios", "test_maintenance"),
                ("test_session_actions.mjs",), ()),
    "architecture": ("任务规则层的依赖方向与副作用入口检查",
                     ("test_architecture",), (), ()),
}


def selection(names, ui=False):
    selected = list(PROFILES) if "core" in names or "ci" in names else []
    selected += [name for name in names if name in PROFILES]
    groups = [[], [], []]
    for name in dict.fromkeys(selected):
        for result, entries in zip(groups, PROFILES[name][1:]):
            result.extend(entry for entry in entries if entry not in result)
    if "ci" in names and not {"core", "platform"}.intersection(names):
        # Keep launcher unit checks, but leave native Codex process integration
        # to the explicitly selected platform/core profiles on a prepared host.
        groups[0] = ["test_desktop.NativeLauncherTest" if entry == "test_desktop" else entry
                     for entry in groups[0]]
    if not ui:
        groups[2] = []
    return groups


def make_plan(names, ui, output):
    python, node, pages = selection(names, ui)
    plan = []
    if python:
        plan.append(("python", [sys.executable, "-B", "-X", "utf8", "-m", "unittest", "-v", *python]))
    if node:
        # Fix the reporter so CI and interactive terminals share one summary format.
        plan.append(("node", ["node", "--test", "--test-reporter=tap", *node]))
    for page in pages:
        command = ["node", "tools/" + page + ".mjs"]
        if page != "session_creation_check":
            command.append(str(output / page))
        plan.append((page, command))
    if "transport" in names:
        plan.append(("transport", [sys.executable, "-B", "-X", "utf8", "tools/smoke_test.py",
                                   "--output", str(output / "transport.json")]))
    if "live-ui" in names:
        plan.append(("live-ui", [sys.executable, "-B", "-X", "utf8", "tools/smoke_test.py",
                                 "--ui-output", str(output / "ui"), "--output", str(output / "live-ui.json")]))
    if "task-flows" in names:
        scratch = output / "task-flows"
        plan.append(("task-flows", [sys.executable, "-B", "-X", "utf8", "tools/task_scenarios.py",
                                    "run", "all", "--scratch-root", str(scratch),
                                    "--output", str(scratch / "result.json")]))
    if "map" in names or "ci" in names:
        plan.append(("map", [sys.executable, "-B", "-X", "utf8", "tools/feature_map.py",
                             "--output", str(output / "map.json")]))
    return plan


def checked_output(value):
    """Only new directories within this project's scratch area; no overwrites."""
    base = ROOT / ".agent-tmp"
    if not base.resolve().is_relative_to(ROOT):
        raise ValueError("项目 .agent-tmp 指向外部位置，拒绝写入")
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if path == base.resolve() or not path.is_relative_to(base.resolve()):
        raise ValueError("--output 必须是本项目 .agent-tmp 下的新子目录")
    if path.exists():
        raise ValueError("--output 已存在；不会覆盖旧结果，请指定本任务的新子目录")
    return path


@contextmanager
def output_directory(value):
    if value:
        folder = checked_output(value)
        folder.mkdir(parents=True, exist_ok=False)
        yield folder
    else:
        base = Path(os.environ.get("MA4_TEST_SCRATCH", ROOT / ".agent-tmp"))
        checked_output(base / "verify-output-boundary")
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="verify-", dir=base) as folder:
            yield Path(folder)


@contextmanager
def static_site():
    # Reuse the production asset allowlist, not its API handler or startup path.
    # Importing constants does not construct Hub, pollers or an AppServer.
    from server import STATIC, TYPES, WEB

    class StaticHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            host = self.headers.get("Host")
            if host not in {f"127.0.0.1:{self.server.server_port}",
                            f"localhost:{self.server.server_port}"}:
                self.send_error(403)
                return
            asset = STATIC.get(urlsplit(self.path).path)
            if asset is None:
                self.send_error(404)
                return
            path = WEB / asset
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES[path.suffix])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def check_environment(output, url):
    env = os.environ.copy()
    # Do not inherit a live MA4_URL or a narrowed/deferred panel fixture.
    for key in ("MA4_URL", "MA4_PANEL_LAYOUT", "MA4_PANEL_DEFERRED", "MA4_VERIFY_INSTANCE"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cache = output / "process-temp"
    cache.mkdir()
    env.update(TMP=str(cache), TEMP=str(cache), TMPDIR=str(cache))
    env["MA4_TEST_SCRATCH"] = str(cache)
    if url:
        env["MA4_URL"] = url
    return env


def execute(plan, output, env):
    results = []
    failed = False
    for name, command in plan:
        item = {"check": name, "argv": command, "status": "not_run"}
        results.append(item)
        if failed:
            item["reason"] = "前项失败；先定点诊断，再选择相关检查"
            continue
        print(f"\n>>> {name}", flush=True)
        started = time.monotonic()
        log = output / (name + ".log")
        try:
            with log.open("w", encoding="utf-8", newline="\n") as handle:
                with subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace") as child:
                    for line in child.stdout:
                        print(line, end="", flush=True)
                        handle.write(line)
                    code = child.wait()
            item.update(status="passed" if code == 0 else "failed", exit_code=code,
                        log=log.name)
            if name == "python":
                output_text = log.read_text(encoding="utf-8")
                total = re.search(r"^Ran (\d+) tests? in ", output_text, re.MULTILINE)
                skipped = re.search(r"^(?:OK|FAILED) \([^\n]*\bskipped=(\d+)[,)]", output_text, re.MULTILINE)
                if total:
                    item["counts"] = {"total": int(total[1]), "skipped": int(skipped[1]) if skipped else 0}
                    if int(total[1]) == 0:
                        item.update(status="failed", error="未执行任何 Python 测试")
                    elif code == 0 and skipped:
                        item["status"] = "passed_with_skips"
            elif name == "node":
                summary = dict(re.findall(r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$",
                                          log.read_text(encoding="utf-8"), re.MULTILINE))
                fields = {"tests": "total", "pass": "passed", "fail": "failed",
                          "cancelled": "cancelled", "skipped": "skipped", "todo": "todo"}
                if not fields.keys() <= summary.keys():
                    item.update(status="failed", error="缺少完整 Node TAP 测试统计，不能确认检查结果")
                else:
                    counts = {field: int(summary[key]) for key, field in fields.items()}
                    item["counts"] = counts
                    if counts["total"] == 0:
                        item.update(status="failed", error="未执行任何 Node 测试")
                    elif counts["failed"] or counts["cancelled"]:
                        item["status"] = "failed"
                    elif counts["passed"] == 0:
                        item.update(status="failed", error="Node 检查全部跳过或待实现")
                    elif code == 0 and (counts["skipped"] or counts["todo"]):
                        item["status"] = "passed_with_skips"
        except OSError as error:
            item.update(status="failed", error=str(error))
            print(str(error), flush=True)
        item["seconds"] = round(time.monotonic() - started, 3)
        failed = item["status"] not in ("passed", "passed_with_skips")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list", help="列出功能分组与副作用")
    for action in ("plan", "run"):
        sub = commands.add_parser(action, help="只显示命令" if action == "plan" else "执行所选检查")
        sub.add_argument("profiles", nargs="+", choices=[*PROFILES, "core", "ci", "transport", "live-ui", "task-flows", "map"])
        sub.add_argument("--ui", action="store_true", help="加跑所选功能的模拟页面检查")
        sub.add_argument("--output", help="保留日志/截图/结果至 .agent-tmp 下的新子目录；默认自动清理")
    args = parser.parse_args(argv)
    if args.action == "list":
        for name, (description, _python, _node, pages) in PROFILES.items():
            print(f"{name:10} {description}；模拟页面 {len(pages)} 项")
        print("core       合并以上各组，重复检查只跑一次；不含 transport、live-ui、task-flows、map 或图片预览")
        print("ci         core 的逻辑检查＋map；启动器只跑单元测试，不需要 Codex、浏览器、凭据或第三方包")
        print("transport  独立 CODEX_HOME + 本机模拟模型 + 临时 TCP 后台；不使用真实会话/额度")
        print("live-ui    真实浏览器 → MA4 后端 → 独立 Codex → 本机模拟模型；含历史重开与证据，不在 core 中")
        print("task-flows 中控确认、派工/报告、在途暂停、恢复、交接与重连；独立 Codex＋本机模拟模型，显式运行")
        print("map        只读核对已登记的地图输入/操作说明/证据；变化返回待复核，不自动宣称验证通过")
        print("--ui 加跑模拟页面；live-ui 显式运行真实页面。复用 Node/Chrome/Playwright 缓存，不安装依赖。")
        print("Python 跳过或 Node 跳过/待实现项标记 passed_with_skips；数量与原因见结果/日志。")
        print("零项测试判失败；Node 缺统计或全部跳过/待实现也判失败。")
        return 0
    if "ci" in args.profiles and args.ui:
        parser.error("ci 固定运行轻量检查，不接受 --ui；页面验证请单独选择相关功能分组")
    if args.action == "plan":
        output = Path(args.output) if args.output else Path("<临时输出>")
        for name, command in make_plan(args.profiles, args.ui, output):
            print(name + ": " + json.dumps(command, ensure_ascii=False))
        print("仅列出 argv；未创建目录、监听端口或执行检查。")
        return 0
    try:
        with output_directory(args.output) as output:
            plan = make_plan(args.profiles, args.ui, output)
            pages = selection(args.profiles, args.ui)[2]
            with static_site() if pages else nullcontext(None) as url:
                results = execute(plan, output, check_environment(output, url))
            passed = all(item["status"] in ("passed", "passed_with_skips") for item in results)
            outcome = "passed_with_skips" if any(item["status"] == "passed_with_skips" for item in results) else "passed"
            report = {"result": outcome if passed else "failed",
                      "at_utc": datetime.now(timezone.utc).isoformat(),
                      "platform": sys.platform, "python": sys.version.split()[0],
                      "profiles": args.profiles, "ui_requested": args.ui,
                      "checks": results,
                      "limits": "仅所列检查；系统/权限跳过见日志。不代表真实模型、线上任务或另一系统已验收。"}
            (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8", newline="\n")
            print(f"\n{report['result']}: " + ", ".join(f"{r['check']}={r['status']}" for r in results))
            print(report["limits"])
            print(f"保留本次输出：{output}" if args.output else "本次临时日志与截图自动清理；需保留时显式指定 --output。")
            return 0 if passed else 1
    except (ValueError, OSError) as error:
        print(f"验证入口失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
