"""Goal-oriented sessions. One actor owns mutations; Codex owns transcripts.

Only this module's managed threads are driven automatically. Persist before sending
so an uncertain RPC cannot silently duplicate work after a restart.
"""
import copy
import json
import math
import os
from pathlib import Path, PurePosixPath
import queue
import stat
from paths import overlaps, path_key, is_link, has_link
import subprocess
import threading
import time
import uuid

from appserver import Disconnected, RpcError
import task_policy
# Keep existing imports/API stable while task rules have one implementation.
from task_policy import ACTIVE, RUNNING, BUSY, TERMINAL, TOKEN_KEYS, activity_timestamp, turn_activity_at, confirmed


DEFAULT_DURATION_MINUTES = 120
REPORT_LIMIT = 3000
DRAFT_PREFIX = "[MA4 目标草案]\n"
WORKSPACES_MARKER = "\n[MA4 工作目录]\n"
DISPATCH_PREFIX = "[MA4 工作目录] "

# Capabilities are explicit; delegation and authorized scope remain task rules.
HOST_TOOL_SETTINGS = {"sandboxPolicy": {"type": "dangerFullAccess"}, "approvalPolicy": "never"}


def file_link_guidance(windows=None):
    windows = os.name == "nt" if windows is None else windows
    example = "E:/PG/项目/中文 报告.md" if windows else "/mnt/e/PG/项目/中文 报告.md"
    return ("本地文件 Markdown 链接使用当前系统真实路径；含空格用尖括号，如 "
            f"[报告](<{example}:12>)；相对路径按会话 cwd。"
            "盘符前不要加 /；行号可用 :12 或 #L12，点击只打开文件。")


def message_envelope(message, request_id, source="automatic", context=""):
    # Every managed turn, including reused/recovered hosts and workers.
    return f"[MA4 message:{request_id}]\n[MA4 source:{source}]\n{context}\n{file_link_guidance()}\n[MA4 content]\n{message}"


# Applied on every dispatch as well as new threads, so existing sessions benefit.
EVIDENCE_GUIDANCE = """交付先列成果路径、实际验证证据、失败/未完成项和临时材料去向；摘要前部区分本次新测、复用结果（证据位置及仍有效的依据）、未验证部分，解释按需读取。
高风险视觉任务先用代表素材与整体预览验证方向，再铺开；普通小任务不固定增加轮次或 Agent。
给模型看图先用整体预览（通常长边 1600 像素以内，以关键内容可辨为准），再看必要局部；未变化的图不重复输入。
原图留在项目，缩略图/裁切图放任务临时目录并按规则收尾；不删除或改写原生会话日志，不建立历史副本。
测试前用一两句说明变更/疑点、受影响行为、可复用证据和新增验证点，选择最小相关范围，无需逐次请求测试批准；遵守用户明确要求和项目必需检查。
复用结果须核对证据可读，相关代码、资源、依赖、测试方法与必要运行条件仍匹配；换会话、换审查者或无关文档变化不触发全量重跑。新失败、证据失效/不足、共享核心改动或整合风险出现时，按影响扩大检查。
独立审查是独立判断方法、证据和实际成果并抽查关键结论，不默认复制制作方全量自测；核对完整目标的覆盖情况，未覆盖部分明确标注。画面或命令相同不等于验证点相同。
优先复用项目已有且适用的测试入口及场景/阶段筛选；确有缺口才由获准执行者补最小入口。失败先最小复现，修复后只复测失败项及相关边界；相同失败无新信息时改变诊断方法，不重放无关全流程。
报错或缺少必要产物时，退出码0、流程结束标记均不能作为通过证据。当前验证状态沿用项目已有文档，简记覆盖、相关实现/方法/条件、结果与证据位置，不逐轮新建报告或复制历史。
实现、自测和本轮必要说明由同一执行者在获准范围内收尾；尚未稳定时记录简短现状，验证结束后集中更新。不要为补数字或小段说明固定另开会话。
"""

HOST_WORK_GUIDANCE = """同一问题返修优先复用原制作会话；任务阶段或所需上下文明显变化时再新建。遵守用户已要求的独立审查，其余按风险安排，不固定增加角色或轮次。
派工明确本轮实际读写路径及需要保护的共享文件；目录授权是最大允许范围，不表示每轮都需占用整个目录。
派工写清本轮变更、受影响检查与已有证据位置；制作方完成相关自测，审查方核对证据有效性并补测关键风险，不只写“独立验收”让其重跑全套。
中控具备完全访问能力，但主要制作、批量修改、反复调试和说明整理默认交给执行者；自己聚焦目标、必要查看和独立验收，避免把实现过程堆进中控上下文。
必要的检查脚本、缓存或少量辅助修改可自行完成，但必须在已确认任务与目录范围内，不能与在途执行者修改同一批文件；发现需要持续返工时交回执行者。
目标草案只写成果、范围、约束和验收；不要把“尚未确认/仍是旧修订”等临时状态或推算截止时间写入目标正文。预算和确认状态由页面及程序字段管理；具体目标变更仍需用户确认。
"""


def text(value, label, limit=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label}需为 1–{limit} 个字符")
    return value.strip()


def budget_value(value):
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError("预算需为对象")
    out = {}
    for key in ("tokenLimit", "deadline", "moneyLimit", "durationMinutes"):
        n = value.get(key)
        if n in (None, ""):
            continue
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0:
            raise ValueError("预算数值必须为有限正数")
        out[key] = int(n) if key == "tokenLimit" else n
    if "tokenLimit" in out and out["tokenLimit"] < 1:
        raise ValueError("token 上限至少为 1")
    if value.get("rates") is not None:
        rates = value["rates"]
        if not isinstance(rates, dict):
            raise ValueError("单价格式错误")
        out["rates"] = {}
        for key in ("input", "cached", "output"):
            n = rates.get(key)
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0:
                raise ValueError("需提供输入、缓存输入、输出的每百万 token 单价")
            out["rates"][key] = n
    if "moneyLimit" in out and "rates" not in out:
        raise ValueError("金额上限需配套单价；没有可靠单价时请用 token 或时限")
    if "deadline" in out:
        out.pop("durationMinutes", None)
    if not any(out.get(k) for k in ("tokenLimit", "deadline", "moneyLimit", "durationMinutes")):
        out["durationMinutes"] = DEFAULT_DURATION_MINUTES
    out["currency"] = str(value.get("currency") or "CNY")[:8]
    return out


def scopes(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("写入范围应为最多 20 个相对路径")
    result = []
    for raw in value:
        raw = text(raw, "相对路径", 500)
        p = PurePosixPath(raw)
        if p.is_absolute() or ".." in p.parts or "\\" in raw or (raw[:1].isalpha() and raw[1:2] == ":"):
            raise ValueError("写入范围必须是项目相对路径，如 src/ui；不能用绝对路径、盘符或 ..")
        result.append(str(p))
    return result


def overlap(a, b):
    if not a or not b:
        return True
    return any(x == "." or y == "." or overlaps(x, y)
               for x in a for y in b)


def task_workspaces(t):
    # Old state stays single-project; reading it never grants new directories.
    return t.get("workspaces", [{"cwd": t["cwd"], "write_scope": []}])


def checked_scope(cwd, scope):
    root = Path(cwd)
    if not root.is_dir() or has_link(root) or root.resolve() != root:
        raise ValueError("工作目录不存在或链接目标已改变，请重新核对授权")
    regions = []
    for rel in scope or ["."]:
        path = root / rel
        if has_link(path) or path.resolve() != path or not path.resolve().is_relative_to(root):
            raise ValueError("写入范围含符号链接或解析到项目之外，请使用实际路径")
        regions.append(str(path))
    return regions


def workspace_value(value, main):
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ValueError("工作目录需为 1–12 项，包含主项目")
    rows, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"cwd", "write_scope"}:
            raise ValueError("每个工作目录需明确填写 cwd 和 write_scope")
        p = Path(text(row["cwd"], "工作目录", 2000)).expanduser()
        if not p.is_absolute() or not p.is_dir():
            raise ValueError("工作目录需为已存在的绝对路径")
        if has_link(p) or p.resolve() != p:
            raise ValueError("工作目录含链接或 ..，请填写实际绝对路径后重新确认")
        cwd = str(p.resolve())
        if path_key(cwd) in seen:
            raise ValueError("工作目录重复")
        if not isinstance(row["write_scope"], list):
            raise ValueError("目录授权的 write_scope 必须是数组；[] 明确表示整个目录")
        scope = scopes(row["write_scope"])
        checked_scope(cwd, scope)
        rows.append({"cwd": cwd, "write_scope": scope})
        seen.add(path_key(cwd))
    if path_key(main) not in seen:
        raise ValueError("工作目录必须包含原主项目；不改变任务所属项目")
    return rows


def tool(name, description, properties, required=()):
    return {"type": "function", "name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": list(required), "additionalProperties": False}}


TOOLS = [
    tool("ma4_dispatch", "派发或续接本任务的执行会话。返回排队状态后结束本轮，MA4 会自动回传结果；不要轮询。",
         {"instruction": {"type": "string"}, "name": {"type": "string"},
          "cwd": {"type": "string", "description": "已确认的工作目录绝对路径；省略用主项目，复用会话时用该会话的目录。"},
          "session_id": {"type": "string"}, "access": {"type": "string", "enum": ["read", "write"]},
          "write_scope": {"type": "array", "items": {"type": "string"},
                          "description": "相对所选 cwd 的路径，如 src/ui。省略继承该目录已授权范围；空数组表示整个目录，只有已授权整个目录时可用。禁止绝对路径、盘符和 ..。"}}, ["instruction"]),
    tool("ma4_control", "查看目标/预算；wait 交还运行控制；pause 请求用户处理，也可按上下文约定提交目标草案；finish 须独立验收并提供证据；handoff 交接干净中控。不能确认草案、自行提高预算或改正式目标。",
         {"action": {"type": "string", "enum": ["status", "wait", "pause", "finish", "handoff"]},
          "summary": {"type": "string"}, "evidence": {"type": "string"},
          "outcome": {"type": "string", "enum": ["met", "unmet"]}}, ["action"]),
    tool("ma4_artifacts", "检查本任务临时材料；clean 只删除精确列出的已无用途且无依赖文件；keep 记录保留理由。不能删除项目正式文件。",
         {"action": {"type": "string", "enum": ["list", "clean", "keep"]},
          "paths": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}, ["action"]),
]

HOST_INSTRUCTIONS = """你是 MA4 中控，首要职责是维护目标和独立验收。
创建后先与用户讨论，整理目标、范围和验收草案。只有用户在页面确认目标和预算并启动后，才可在正式目标内通过 ma4_dispatch 派工，无需逐次请求许可。
草案通过 ma4_control(action=pause, summary="[MA4 目标草案]\\n目标：…\\n范围：…\\n验收：…") 提交。只保存当前草案，等用户确认，不能把聊天中的“开始吧”视为程序已启动。
你具备完全访问、联网和工具调用能力；这不扩大用户已确认的目标、目录授权、预算或项目规则。
主要制作、批量修改、反复调试和说明整理默认交给执行者；你聚焦统筹、必要查看与独立验收，避免把实现细节堆满上下文。
必要的检查脚本、缓存或少量辅助修改可自行完成；先核对授权及在途写入范围，不与执行者并发修改同一批文件。需要持续返工时交回执行者。
先看目标、参考与实际成果，再读执行者解释。
用户没有指出的问题不等于认可。每轮核对完整目标与整体质量的证据覆盖情况，不把上轮修改清单当作全部要求；这不要求每轮重新执行全部测试。
执行者的报告未经独立验证，不能单凭它判定完成；独立核对方法、实际证据与关键风险，复用仍有效的结果，对变更和未覆盖部分补测。视觉任务必须实际查看图像/实机，不能只看代码或文件是否存在。
必要时推翻初稿、更换干净执行会话。证据不足明确说未验证。达到目标才 ma4_control finish(outcome=met, evidence=实际证据)。
成本包含你和全部执行者。不能自行增加预算、降标或超范围工作；确需改变时 pause 说明原因。
需要用户决定时用 pause 记录具体问题，并在回复中询问；不要调用只在终端提供交互的提问工具。
只使用 ma4_dispatch 派工，禁止另用原生子 Agent、exec codex、其他 API 绕过关联和预算。
派工后结束当前回合等待系统自动回传，不循环查询、不睡眠轮询、不把等待当作失败。
独立验收可派只读调查，但你仍负责最后判断。共享文件范围必须真实，不得申报只读却修改。
保持精简：任务是一条消息，结果是会话末尾摘要，不为流转建立领取/提交/签收文档。
试验、验收、任务结束时检查本任务临时目录。必要证据/素材先转正；明确无依赖的精确文件用 ma4_artifacts clean，未知用途用 keep 留理由。
系统已经提供的目标、预算、执行状态和空目录信息不必再调工具查询。连续尝试无进展时改变方法或暂停说明，不无限重复。
交接只传用户决定、产物位置、未解决问题和必要事实；旧判断不自动成为已认可目标。
finish 只提交结论和验收证据；最终用时与 token 由程序更新，不为补数字另派或续开一轮。
""" + file_link_guidance() + "\n"

WORKER_INSTRUCTIONS = """你是 MA4 执行会话，完成中控给你的具体工作。禁止自行派生子 Agent 或新 Codex 会话。
遵守本次任务的读写范围。正式源码/素材留在项目；临时材料使用消息指定的任务目录，不向项目外存放产物。
结束时用简短最终回答说明产物位置、实际验证结果、剩余问题及临时文件去向，不声称未做过的验证。
用户未批评的部分不等于认可；需要推翻原方案时直接说明。不要自动提交、推送或扩展部署范围。
""" + file_link_guidance() + "\n"


class Controllers:
    def __init__(self, hub, directory, clock=time.time):
        self.hub, self.clock = hub, clock
        self.path = Path(directory) / "controllers.json"
        self.tasks = {}
        self.error = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if saved.get("version") != 1 or not isinstance(saved.get("tasks"), dict):
                raise ValueError("不支持的数据格式")
            self.tasks = saved["tasks"]
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.error = "中控状态无法读取，已停止自动运行：" + str(exc)
        self.inbox = queue.Queue(maxsize=2048)
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self.run, name="ma4-controllers", daemon=True)
        self.view = {}
        self.recovering = bool(self.tasks)
        self.next_reconcile = 0
        self.overflow = False
        self.connection_note = None
        self.publish(save=False)

    def start(self):
        self.worker.start()

    def close(self):
        self.stop.set()
        if self.worker.is_alive():
            self.worker.join(timeout=3)

    def snapshot(self):
        return copy.deepcopy(self.view)

    def member_ids(self):
        return {tid for t in self.view.get("tasks", []) for tid in
                [t.get("host"), *t.get("formerHosts", []), *t.get("workers", {})] if tid}

    def watched_ids(self):
        ids = set()
        for t in self.view.get("tasks", []):
            if t.get("host") and (t["status"] in RUNNING or t["hostBusy"]):
                ids.add(t["host"])
            ids.update(tid for tid, w in t["workers"].items() if w["state"] in BUSY or w["state"] == "queued")
        return ids

    def activity_times(self):
        return {s["threadId"]: s.get("updatedAt") for t in self.view.get("tasks", [])
                for s in t.get("statistics", {}).get("sessions", [])}

    def owner(self, tid):
        for t in self.tasks.values():
            if tid == t.get("host") or tid in t.get("formerHosts", []) or tid in t["workers"]:
                return t
        return None

    def publish(self, save=True):
        for t in self.tasks.values():
            if t.get("completion"):
                t["completion"].update(usageTotal=self.usage(t), estimatedCost=self.cost(t),
                                       settling=t["hostBusy"],
                                       turnDurationMs=sum(r.get("durationMs", 0) for s in t.get("metrics", {}).values()
                                                          for r in s["turns"].values()))
                if t.get("firstStartedAt") is not None:
                    end = t["completion"].get("completedAt", t["completion"]["decidedAt"])
                    t["completion"]["elapsedMs"] = max(0, (end - t["firstStartedAt"]) * 1000)
        if save:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump({"version": 1, "tasks": self.tasks}, f, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        values = []
        for t in self.tasks.values():
            row = copy.deepcopy(t)
            row["usageTotal"] = self.usage(t)
            row["estimatedCost"] = self.cost(t)
            row["statistics"] = self.statistics(t)
            row["reportDelivery"] = self.report_delivery(t)
            row["diagnosis"] = self.diagnosis(t)
            row.pop("metrics", None)
            # Queued instructions / internal delivery markers are not another transcript UI.
            for w in row["workers"].values():
                w.pop("instruction", None)
            row.pop("outbox", None)
            values.append(row)
        self.view = {"tasks": values, "error": self.error, "warning": self.connection_note, "recovering": self.recovering}
        self.hub.emit("controllers", controllers=self.snapshot())

    def invoke(self, operation, **args):
        if not self.worker.is_alive():
            raise RuntimeError("中控运行模块未启动")
        done = threading.Event()
        slot = {"action": operation, "args": args, "done": done}
        self.inbox.put_nowait(("command", slot))
        if not done.wait(70):
            raise TimeoutError("操作仍在处理中，请刷新查看状态，不要重复创建")
        if "error" in slot:
            raise slot["error"]
        return slot.get("result")

    def post(self, method, params):
        if method not in ("turn/started", "turn/completed", "thread/tokenUsage/updated", "thread/name/updated", "thread/settings/updated"):
            return
        if params.get("threadId") not in self.member_ids():
            return
        try:
            self.inbox.put_nowait(("event", (method, params)))
        except queue.Full:
            self.overflow = True

    def request(self, client, rid, params):
        try:
            self.inbox.put_nowait(("tool", (client, rid, params)))
        except queue.Full:
            client.respond(rid, self.tool_result({"error": "事件过多，自动运行将暂停"}, False))
            self.overflow = True

    def disconnected(self):
        try:
            self.inbox.put_nowait(("recover", None))
        except queue.Full:
            self.overflow = True

    @staticmethod
    def tool_result(result, success=True):
        return {"success": success, "contentItems": [{"type": "inputText", "text": json.dumps(result, ensure_ascii=False)}]}

    def run(self):
        while not self.stop.is_set():
            try:
                try:
                    kind, payload = self.inbox.get(timeout=0.5)
                except queue.Empty:
                    kind = None
                if kind == "command":
                    try:
                        if self.error:
                            raise ValueError(self.error)
                        payload["result"] = getattr(self, "do_" + payload["action"])(**payload["args"])
                    except Exception as exc:
                        payload["error"] = exc
                    finally:
                        payload["done"].set()
                elif kind == "tool":
                    client, rid, params = payload
                    try:
                        result = self.tool_call(params)
                        reply = self.tool_result(result)
                    except Exception as exc:
                        reply = self.tool_result({"error": str(exc)}, False)
                    if not client.closed:
                        client.respond(rid, reply)
                elif kind == "event":
                    self.event(*payload)
                elif kind == "recover":
                    self.recovering, self.next_reconcile = True, 0
                    self.publish(save=False)
                self.tick()
            except (Disconnected, TimeoutError, RpcError) as exc:
                self.connection_note = "正在重新核对会话连接：" + str(exc)[:180]
                self.next_reconcile = self.clock() + 5
                self.recovering = True
                self.publish(save=False)
            except Exception as exc:
                # Keep the existing service alive, but never continue uncertain work.
                self.error = "中控自动运行暂停：" + str(exc)[:300]
                for t in self.tasks.values():
                    if t["status"] in ACTIVE:
                        t.update(status="attention", note=self.error)
                    busy = ([t["host"]] if t["hostBusy"] else []) + [tid for tid, w in t["workers"].items() if w["state"] in BUSY]
                    for tid in busy:
                        try:
                            self.hub.interrupt(tid)
                        except Exception:
                            pass
                self.publish(save=False)

    def policy_runtime(self):
        return task_policy.RuntimeState(now=self.clock(), connected=bool(self.hub.daemon.get("connected")),
                                        recovering=self.recovering, error=self.error)

    def usage(self, t):
        return task_policy.usage(t)

    def record_turn(self, t, tid, turn, live_start=False):
        """Keep counters/timing only, never another copy of conversation items."""
        turn_id = turn.get("id")
        if not turn_id:
            return
        session = t.setdefault("metrics", {}).setdefault(tid, {
            "baseline": dict(t["usage"].get(tid, {})) if live_start else None, "turns": {}})
        row = session["turns"].setdefault(turn_id, {"id": turn_id})
        if live_start:
            row["usageKnown"] = True
            row.setdefault("startUsage", dict(t["usage"].get(tid, {})))
        for key in ("startedAt", "completedAt", "durationMs"):
            if turn.get(key) is not None:
                row[key] = turn[key]
        if live_start and "startedAt" not in row:
            row["startedAt"] = self.clock()
            row["timeEstimated"] = True
        # A delayed real start cannot make an estimated completion trustworthy.
        # Keep the existing conservative marker until all stored bounds are known.
        if turn.get("startedAt") is not None and ("completedAt" not in row or turn.get("completedAt") is not None):
            row.pop("timeEstimated", None)
        status = turn.get("status")
        if status and (status != "inProgress" or row.get("status") in (None, "inProgress")):
            row["status"] = status
        if status and status != "inProgress" and "completedAt" not in row:
            row["completedAt"] = self.clock()
            row["timeEstimated"] = True
        if row.get("durationMs") is None and row.get("completedAt") is not None and row.get("startedAt") is not None:
            row["durationMs"] = max(0, (row["completedAt"] - row["startedAt"]) * 1000)
        return row

    def statistics(self, t):
        sessions = []
        for tid in dict.fromkeys([t.get("host"), *t.get("formerHosts", []), *t["workers"]]):
            if not tid:
                continue
            metric = t.get("metrics", {}).get(tid, {})
            previous = metric.get("baseline")
            rows = []
            for raw in metric.get("turns", {}).values():
                row = {k: v for k, v in raw.items() if k not in ("cumulative", "usageKnown", "startUsage")}
                cumulative = raw.get("cumulative")
                row["usage"] = ({k: max(0, cumulative.get(k, 0) - max(previous.get(k, 0), raw.get("startUsage", {}).get(k, 0))) for k in TOKEN_KEYS}
                                if raw.get("usageKnown") and cumulative is not None and previous is not None else None)
                previous = cumulative
                rows.append(row)
            total = {k: t["usage"].get(tid, {}).get(k, 0) for k in TOKEN_KEYS}
            attributed = {k: sum((r["usage"] or {}).get(k, 0) for r in rows) for k in TOKEN_KEYS}
            sessions.append({"threadId": tid, "role": "worker" if tid in t["workers"] else "host",
                             "name": t["workers"][tid]["name"] if tid in t["workers"] else "当前中控" if tid == t["host"] else "前任中控",
                             "usage": total, "turns": rows, "updatedAt": turn_activity_at(rows) or None,
                             "durationMs": sum(r.get("durationMs", 0) for r in rows) if any("durationMs" in r for r in rows) else None,
                             "unattributedTokens": max(0, total["totalTokens"] - attributed["totalTokens"])})
        roles = []
        for role in ("host", "worker"):
            group = [s for s in sessions if s["role"] == role]
            roles.append({"role": role, "usage": {k: sum(s["usage"][k] for s in group) for k in TOKEN_KEYS},
                          "durationMs": sum(s["durationMs"] or 0 for s in group) if not group or any(s["durationMs"] is not None for s in group) else None,
                          "turnCount": sum(len(s["turns"]) for s in group)})
        return {"roles": roles, "sessions": sessions}

    def cost(self, t):
        return task_policy.cost(t)

    def exhausted(self, t, include_deadline=True):
        return task_policy.exhausted(t, self.clock(), include_deadline=include_deadline)

    def control_blocker(self):
        return task_policy.control_blocker(self.policy_runtime())

    def confirm_blocker(self, t):
        return task_policy.confirm_blocker(t, self.policy_runtime())

    def handoff_blocker(self, t):
        return task_policy.handoff_blocker(t, self.policy_runtime())

    def diagnosis(self, t):
        return task_policy.diagnosis(t, self.policy_runtime())

    def begin_closing(self, t):
        """A deadline drains existing turns; token/money limits remain hard stops."""
        active = t["status"] in ACTIVE
        # A proposed change pauses new work, but already running workers still
        # have to obey the old confirmed budget. Do not auto-review a paused draft.
        draft_workers = t.get("draft") and t["status"] == "paused" and any(w["state"] in BUSY for w in t["workers"].values())
        if not (active or draft_workers) or self.exhausted(t) != "已到截止时间":
            return
        t["closing"] = {"startedAt": self.clock(), "notified": {}, "reviewStarted": False,
                        "needsReview": active and bool(t["pending"] or any(w["state"] in BUSY for w in t["workers"].values()))}
        t.update(status="closing", note="时限已到，停止新增派工，等待当前工作安全收尾；实际结束可能晚于时限。")
        self.publish()

    def close_at_boundary(self, t):
        closing = t["closing"]
        active = [(tid, w.get("turnId")) for tid, w in t["workers"].items() if w["state"] in BUSY]
        if t["hostBusy"] and not closing["reviewStarted"]:
            active.append((t["host"], t.get("hostTurn")))
        for tid, turn in active:
            if not turn or closing["notified"].get(tid) == turn:
                continue
            # Persist before steering; a lost response must not repeatedly interrupt concentration.
            closing["notified"][tid] = turn
            self.publish()
            message = ("[MA4 到期收尾提醒]\n任务时限已到。不要开始新一批工作、派工或继续扩大范围。"
                       "请让正在进行的操作到达安全停止点，保存已有成果和必要接续信息，"
                       "简短报告成果路径、已验证/未验证内容及未完成项，然后结束本轮。"
                       "这不是立即中断命令，也不代表目标已完成。中控需等已有执行者返回后汇总。")
            try:
                # No fallback to turn/start if the addressed turn has just finished.
                rid = uuid.uuid4().hex
                self.hub.steer_only(tid, turn, message_envelope(message, rid), rid)
            except (ValueError, Disconnected, RpcError, TimeoutError):
                t["note"] = "时限已到；收尾提醒未确认，继续等待已有回合自然结束，不重发或强制中断。"
                self.publish()
        if t["hostBusy"] or any(w["state"] in BUSY for w in t["workers"].values()) or t.get("outbox"):
            return
        if closing["needsReview"] and not closing["reviewStarted"]:
            closing["reviewStarted"] = True
            t["note"] = "执行者已返回，中控正在做最后一次收尾汇总，不再派工。"
            self.publish()
            pending = t["pending"][:8]
            message = ("[MA4 到期收尾汇总]\n这是到期后的最后一次自动汇总。先核对以下执行者报告和现有成果，"
                       "交付已完成项、未完成/未验证项、成果位置与接续信息。只做有限的只读核对，"
                       "不再派工、返工或交接新的中控。没有充分证据不得宣称目标完成；"
                       "可调用 finish 提交真实结论，也可直接汇报后结束本轮，程序将停止自动推进。\n"
                       f"尚待核对的报告共 {len(t['pending'])} 份，本次提供前 {len(pending)} 份；其余保留待续接。\n"
                       + json.dumps(pending, ensure_ascii=False))
            self.send_host(t, message, deliveries=[p["id"] for p in pending], source="worker_report" if pending else "automatic")
            return
        t.update(status="budget", note="已到时限，现有回合已结束，自动推进已停止；未完成目标需调整预算后继续。")
        closing["completedAt"] = self.clock()
        self.publish()

    def get(self, task_id):
        if task_id not in self.tasks:
            raise ValueError("未知任务")
        return self.tasks[task_id]

    def context(self, t, related_workers=()):
        try:
            empty = all(not root.exists() or not any(p.name != ".ma4-owner.json" for p in root.iterdir())
                        for root in (self.scratch(t, cwd) for cwd in self.scratch_cwds(t)))
        except OSError:
            empty = False
        return (f"MA4 任务：{t['name']}\n项目：{t['cwd']}\n"
                f"程序运行状态：正式目标{'已确认' if confirmed(t) else '未确认'}；目标修订 {t.get('revision', 1)}；"
                f"任务状态 {t['status']}；{'有待确认草案，禁止按新草案执行' if t.get('draft') else '无待确认草案'}。\n"
                "确认、暂停、预算和目录授权以本条程序字段为准；目标正文中的旧草案时态不改变程序状态。"
                "正文中的成果范围和操作限制仍须遵守；若矛盾影响具体目标或权限，先提出澄清草案，不自行删减或扩权。\n"
                f"完整正式目标（保留用户确认原文）：\n{t['target'] or '尚未确认；现在只讨论，不执行。'}\n"
                f"初步想法：{t.get('idea') or '未填写'}\n"
                f"当前草案（未确认，不可执行）：{(t.get('draft') or {}).get('target') or '尚无草案'}\n"
                "需要整理或变更目标时，调用 ma4_control(action=pause, summary=\"[MA4 目标草案]\\n目标：…\\n范围：…\\n验收：…\")。"
                "请包含完整草案而非只写差异。工具只保存草案，用户在页面确认目标与预算后才能启动。\n"
                f"已授权工作目录及写入范围：{json.dumps(task_workspaces(t), ensure_ascii=False)}\n"
                f"待确认工作目录：{json.dumps((t.get('draft') or {}).get('workspaces'), ensure_ascii=False)}\n"
                "跨项目仍使用本任务、同一预算。派工可传 cwd；旧工具没有 cwd 参数时，在 instruction 第一行写"
                " [MA4 工作目录] /实际绝对路径，下一行起写任务正文。复用执行会话不能更换目录。\n"
                "需要新增或变更目录授权时，将完整目录数组追加在目标草案末尾：\\n[MA4 工作目录]\\n"
                '[{"cwd":"/实际目录","write_scope":["相对路径"]}]。包含主项目；[] 表示整个目录。'
                "这只提出草案，不授予权限；已确认目录后续直接复用，不重复确认。旧目标中的分工限制仍须遵守，不能自行忽略。\n"
                + ("当前仅讨论：可以只读了解项目、回应用户并整理草案；不能派工、执行或宣告目标达标。普通消息不恢复任务。\n" if t["status"] not in RUNNING else "") +
                f"预算：{json.dumps(t['budget'], ensure_ascii=False)}\n"
                f"累计用量：{json.dumps(self.usage(t), ensure_ascii=False)}；估算金额：{self.cost(t)}\n"
                f"临时目录：{self.scratch(t)}\n"
                f"临时材料：{'任务临时目录为空，无需再调用工具检查。' if empty else '有待核对材料，结束时按需检查；clean/keep 使用 list 返回的精确 path，包含各项目材料。'}\n"
                + self.worker_context(t, related_workers)
                + self.write_context(t) +
                "交付先看成果路径、验证证据和失败项；说明按需读。finish 的最终数字由程序记录，无需另开回合。\n"
                "write_scope 相对所选工作目录，省略继承其已授权范围；显式 [] 表示整个目录，需已有对应授权。"
                "目录授权只管理派工范围，不扩大目标或部署/全局修改权限，也不是系统沙箱。\n"
                + EVIDENCE_GUIDANCE +
                HOST_WORK_GUIDANCE +
                ("时限已到：仅收尾，不再派工；等已有执行者返回后汇总，未验证部分明确保留。\n" if t["status"] == "closing" else "") +
                "目标、预算和相关执行状态已列出；只有需要未列出的历史执行者时才调用 ma4_control(action=status)，不要轮询。\n")

    def scratch_cwds(self, t):
        roots = {}
        for cwd in [t["cwd"], *t.get("scratchCwds", []),
                    *(w.get("cwd", t["cwd"]) for w in t["workers"].values())]:
            roots.setdefault(path_key(cwd), cwd)
        return list(roots.values())

    def scratch(self, t, cwd=None):
        return Path(cwd or t["cwd"]) / ".agent-tmp" / ("ma4-" + t["id"])

    def ensure_scratch(self, t, cwd=None):
        cwd = cwd or t["cwd"]
        if has_link(cwd) or Path(cwd).resolve() != Path(cwd):
            raise ValueError("项目路径的链接目标已改变，需重新核对归属")
        base = Path(cwd) / ".agent-tmp"
        if is_link(base):
            raise ValueError("项目临时区是符号链接，无法安全管理")
        root = self.scratch(t, cwd)
        if is_link(root):
            raise ValueError("任务临时区是符号链接")
        if root.exists():
            marker = root / ".ma4-owner.json"
            if is_link(marker):
                raise ValueError("临时目录归属标记是符号链接：" + str(marker))
            try:
                owner = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("临时目录归属标记缺失或无法读取，需维护核实后恢复；不自动认领：" + str(marker)) from exc
            if not isinstance(owner, dict) or owner.get("task") != t["id"]:
                raise ValueError("临时目录归属不匹配，不能使用：" + str(marker))
        else:
            repo = subprocess.run(["git", "-C", cwd, "rev-parse", "--is-inside-work-tree"], capture_output=True, timeout=5)
            if repo.returncode == 0:
                ignored = subprocess.run(["git", "-C", cwd, "check-ignore", "--quiet", str(root / ".ma4-owner.json")], capture_output=True, timeout=5)
                if ignored.returncode:
                    raise ValueError("项目尚未忽略 .agent-tmp/；请先将该目录加入项目 Git 忽略规则")
            root.mkdir(parents=True)
            (root / ".ma4-owner.json").write_text(json.dumps({"task": t["id"]}) + "\n", encoding="utf-8", newline="\n")
        if path_key(cwd) not in {path_key(p) for p in t.get("scratchCwds", [])}:
            t.setdefault("scratchCwds", []).append(cwd)
            self.publish()
        return root

    def new_host(self, t):
        tid = self.hub.new_thread(t["cwd"], developer_instructions=HOST_INSTRUCTIONS,
                                  dynamic_tools=TOOLS, sandbox="danger-full-access",
                                  approval_policy="never", model=t.get("model"))["threadId"]
        t["model"] = t.get("model") or getattr(self.hub, "live", {}).get(tid, {}).get("settings", {}).get("model")
        t["host"] = tid
        t.setdefault("metrics", {})[tid] = {"baseline": {}, "turns": {}}
        self.publish()
        self.hub.rename(tid, t["name"])
        return tid

    def do_create(self, cwd, name, target="", budget=None, start=False, request_id=None, idea=""):
        if start:
            raise ValueError("请先创建并讨论，再确认草案与预算后启动")
        if request_id:
            request_id = text(request_id, "请求标识", 100)
            existing = next((t for t in self.tasks.values() if t.get("createRequest") == request_id), None)
            if existing:
                return {"taskId": existing["id"], "threadId": existing["host"]}
        p = Path(text(cwd, "项目目录", 2000)).expanduser().resolve()
        if not p.is_dir():
            raise ValueError("项目目录不存在")
        initial = text(idea, "初步想法", 40000) if idea else ""
        draft_target = text(target, "草案") if target else ""
        t = {"id": uuid.uuid4().hex[:16], "cwd": str(p), "name": text(name, "任务名称", 100),
             "target": "", "goalConfirmed": False, "idea": initial, "draftRevision": 1,
             "draft": {"target": draft_target, "source": "user", "updatedAt": self.clock(), "budget": budget_value(budget)},
             "budget": budget_value(budget), "status": "draft",
             "host": None, "hostBusy": False, "hostTurn": None, "formerHosts": [], "workers": {},
             "pending": [], "usage": {}, "outbox": {}, "retained": {}, "summary": "", "note": "",
             "firstStartedAt": None,
             "createRequest": request_id,
             "createdAt": self.clock(), "updatedAt": self.clock()}
        self.tasks[t["id"]] = t
        self.publish()
        try:
            self.new_host(t)
            if initial:
                self.do_send(t["host"], initial, uuid.uuid4().hex)
        except Exception as exc:
            t.update(status="attention", note="创建未完成：" + str(exc))
            self.publish()
            raise
        return {"taskId": t["id"], "threadId": t["host"]}

    def require_budget(self, t):
        if not any(t["budget"].get(k) for k in ("deadline", "durationMinutes", "tokenLimit", "moneyLimit")):
            raise ValueError("自动运行至少设置一个预算上限（时限、token 或配套单价的金额）")
        if self.exhausted(t):
            raise ValueError(self.exhausted(t) + "，请先调整预算")

    def check_draft_revision(self, t, revision):
        if isinstance(revision, bool) or revision != t.get("draftRevision", 0):
            raise ValueError("草案已更新，请重新打开确认窗口查看最新内容")

    def stage_draft(self, t, target, source, budget=None, workspaces=None):
        if t["status"] == "closing":
            raise ValueError("正在到期收尾，请结束后再修改目标草案")
        grants = workspace_value(workspaces, t["cwd"]) if workspaces is not None else copy.deepcopy(
            (t.get("draft") or {}).get("workspaces", task_workspaces(t)))
        t["draftRevision"] = t.get("draftRevision", 0) + 1
        t["draft"] = {"target": target, "source": source, "updatedAt": self.clock(),
                      "budget": copy.deepcopy(budget if budget is not None else (t.get("draft") or {}).get("budget", t["budget"])),
                      "workspaces": grants}
        t.update(status="paused" if confirmed(t) else "draft",
                 note="草案待你确认；停止新增派工，已有执行回合仍按原目标收尾。", updatedAt=self.clock())
        self.publish()
        return {"draftSaved": True, "draftRevision": t["draftRevision"], "message": "草案已保存，请用户在页面查看并确认目标与预算；现在结束本轮，不执行草案。"}

    def do_update(self, task_id, name, target, budget, draft_revision=None, workspaces=None):
        t = self.get(task_id)
        if draft_revision is not None:
            self.check_draft_revision(t, draft_revision)
        new_name, new_target, new_budget = text(name, "名称", 100), text(target, "目标"), budget_value(budget)
        result = self.stage_draft(t, new_target, "user", new_budget, workspaces)
        # A display name is not an execution goal.
        t["name"] = new_name
        self.publish()
        if t["host"]:
            self.hub.rename(t["host"], new_name)
        return result

    def do_confirm(self, task_id, draft_revision, name, target, budget, start=True, workspaces=None):
        t = self.get(task_id)
        self.check_draft_revision(t, draft_revision)
        new_name, new_target, new_budget = text(name, "名称", 100), text(target, "目标"), budget_value(budget)
        # An old client must never confirm grants that it did not display.
        proposed = (t.get("draft") or {}).get("workspaces", task_workspaces(t))
        if workspaces is None and proposed != task_workspaces(t):
            raise ValueError("工作目录授权已变更，请刷新页面并明确确认目录与写入范围")
        grants = workspace_value(workspaces if workspaces is not None else task_workspaces(t), t["cwd"])
        if not isinstance(start, bool):
            raise ValueError("启动选项需为布尔值")
        blocker = self.confirm_blocker(t)
        if blocker:
            raise ValueError(blocker)
        if start:
            self.require_budget(dict(t, budget=new_budget))
            if not t.get("host"):
                raise ValueError("中控会话尚未创建成功")
            if new_budget.get("moneyLimit") and t.get("costUncertain"):
                raise ValueError("模型已改变，请改用 token/时限后继续")
        if new_target != t["target"] or grants != task_workspaces(t):
            t["revision"] = t.get("revision", 1) + 1 if confirmed(t) else 1
            t.update(summary="", evidence="")
            t.pop("completion", None)
            for w in t["workers"].values():
                if w["state"] == "queued":
                    w["state"] = "idle"
                    w.pop("instruction", None)
        t.update(name=new_name, target=new_target, budget=new_budget, goalConfirmed=True,
                 workspaces=grants,
                 status="paused", note="目标与预算已确认，尚未启动", updatedAt=self.clock(),
                 draftRevision=t.get("draftRevision", 0) + 1)
        t.pop("draft", None)
        if not new_budget.get("moneyLimit"):
            t.pop("costUncertain", None)
        self.publish()
        if t["host"]:
            self.hub.rename(t["host"], new_name)
        if start:
            return self.do_resume(task_id)
        return {"confirmed": True}

    def do_resume(self, task_id):
        t = self.get(task_id)
        blocker = self.confirm_blocker(t)
        if blocker:
            raise ValueError(blocker)
        if not confirmed(t) or t.get("draft"):
            raise ValueError("请先查看并确认目标草案与预算，再启动")
        self.require_budget(t)
        if t.get("costUncertain"):
            raise ValueError("有会话从外部切换了模型，金额估算不再可靠；请改用 token/时限后继续")
        if not t["host"]:
            raise ValueError("中控会话尚未创建成功")
        # Resolve the duration only on start; persist the fixed deadline so that
        # pauses, handoffs and process restarts cannot silently extend the budget.
        if t["budget"].get("durationMinutes"):
            t["budget"]["deadline"] = self.clock() + t["budget"].pop("durationMinutes") * 60
        t.update(status="running", note="", updatedAt=self.clock())
        # Legacy tasks did not record their original start. Do not turn a later
        # resume into a fabricated first-start timestamp.
        if "firstStartedAt" in t and t["firstStartedAt"] is None:
            t["firstStartedAt"] = self.clock()
        t.pop("completion", None)
        t.pop("closing", None)
        self.publish()
        self.send_host(t, "用户启动/恢复本任务。先核对当前成果和在途情况，再决定行动。")
        return {"resumed": True}

    def do_pause(self, task_id, reason="用户暂停"):
        t = self.get(task_id)
        t.update(status="paused", note=reason, updatedAt=self.clock())
        self.publish()
        tids = [t["host"]] if t["hostBusy"] else []
        tids += [tid for tid, w in t["workers"].items() if w["state"] in BUSY]
        errors = []
        for tid in tids:
            try:
                self.hub.interrupt(tid)
            except Exception as exc:
                errors.append(str(exc)[:150])
        if errors:
            t["note"] += "；中断尚未确认：" + "；".join(errors)
            self.publish()
        return {"paused": True, "interruptErrors": errors}

    def do_send(self, tid, message, request_id, skills=None):
        t = self.owner(tid)
        if not t:
            return self.hub.send_raw(tid, message, request_id, skills=skills)
        if tid != t["host"]:
            raise ValueError("请向当前中控发送要求，由它协调执行或交接；前任中控和执行会话可查看")
        self.begin_closing(t)
        if t["status"] == "closing" and not t["hostBusy"]:
            raise ValueError("正在到期收尾，请结束后再讨论")
        reason = self.exhausted(t, include_deadline=t["status"] in ACTIVE)
        if reason:
            raise ValueError(reason + "，请先确认调整预算")
        if t.get("outbox"):
            raise ValueError("有发送状态待核对，请稍后重试")
        return self.send_host(t, text(message, "消息", 40000), request_id, source="user", skills=skills)

    def send_host(self, t, message, request_id=None, deliveries=(), source="automatic", skills=None):
        rid = request_id or uuid.uuid4().hex
        selections = skills if source == "user" else None
        if selections is not None:
            self.hub.skill_inputs(t["host"], selections)  # reject stale selections before recording a send
        scratch_notice = "讨论阶段不创建临时目录，不自行创建任务根目录或归属标记。"
        if confirmed(t) and t["status"] in RUNNING:
            # The host can create review images even when all workers use another cwd.
            # Register its root before advertising it, including on resumed old tasks.
            try:
                self.ensure_scratch(t)
                scratch_notice = "主项目临时目录归属已核对，可使用现有目录；不要删除或改写归属标记。"
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                scratch_notice = ("主项目临时目录不可使用：" + str(exc) +
                                  "。不要自行创建任务根目录或补造标记；可继续讨论和只读检查，说明受阻部分。")
        related = [tid for tid, w in t['workers'].items()
                   if tid in message or (w.get('name') and w['name'] in message)]
        context = self.context(t, related) + "\n临时目录当前状态：" + scratch_notice + "\n"
        if t.get("handoffPending"):
            context += "\n前任中控交接说明（须核实，不替代用户目标）：\n" + t["handoffPending"]
        payload = message_envelope(message, rid, source, context)
        if len(payload) > 50000:
            raise ValueError("消息加任务信息超过 50000 字，请缩短本次消息或目标草案")
        if t["hostBusy"]:
            return self.hub.send_raw(t["host"], payload, rid, skills=selections)
        t["outbox"] = {"id": rid, "tid": t["host"], "kind": "host", "deliveries": list(deliveries)}
        self.publish()
        try:
            result = self.hub.send_raw(t["host"], payload, rid, skills=selections)
        except Exception:
            t.update(status="attention", note="中控消息发送结果不明，正在核对，未自动重发")
            self.publish()
            raise
        t.update(hostBusy=True, hostTurn=result.get("turnId"))
        self.record_turn(t, t["host"], {"id": result.get("turnId"), "status": "inProgress"}, live_start=True)
        t["pending"] = [p for p in t["pending"] if p["id"] not in deliveries]
        t["outbox"] = {}
        t.pop("handoffPending", None)
        self.publish()
        return result

    def tool_call(self, params):
        if self.error or self.recovering:
            raise ValueError(self.error or "正在恢复运行状态，请稍后")
        t = self.owner(params.get("threadId"))
        if not t or t["host"] != params.get("threadId"):
            raise ValueError("仅当前中控可调用本任务工具")
        self.begin_closing(t)
        name = params.get("tool")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise ValueError("工具参数需为对象")
        if name == "ma4_dispatch":
            return self.dispatch(t, **args)
        if name == "ma4_artifacts":
            return self.do_artifacts(t["id"], **args)
        if name != "ma4_control":
            raise ValueError("未知中控工具")
        action = args.get("action")
        if action == "status":
            return {"context": self.context(t), "workers": self.snapshot_task(t), "note": t["note"],
                    "diagnosis": self.diagnosis(t)}
        if action == "wait":
            return {"message": "请结束本轮，执行结果将自动回传；不要轮询。"}
        if action == "pause":
            summary = text(args.get("summary"), "暂停原因或草案")
            if summary.startswith(DRAFT_PREFIX):
                target, grants = summary[len(DRAFT_PREFIX):], None
                if WORKSPACES_MARKER in target:
                    target, raw = target.rsplit(WORKSPACES_MARKER, 1)
                    try:
                        grants = json.loads(raw)
                    except ValueError:
                        raise ValueError("[MA4 工作目录] 后需为完整 JSON 数组，不加代码围栏")
                    if not isinstance(grants, list):
                        raise ValueError("工作目录需为数组")
                return self.stage_draft(t, text(target, "目标、范围与验收草案"), "controller", workspaces=grants)
            if t["status"] == "closing":
                t["note"] = "到期收尾：" + text(args.get("summary"), "暂停原因")
                self.publish()
                return {"closing": True, "message": "请结束当前回合；程序会等待执行者自然返回并收尾，不中断它们。"}
            # Do not interrupt the tool call currently awaiting our response.
            t.update(status="paused", note=text(args.get("summary"), "暂停原因"))
            self.publish()
            for tid, w in t["workers"].items():
                if w["state"] in BUSY:
                    try:
                        self.hub.interrupt(tid)
                    except (ValueError, Disconnected, RpcError, TimeoutError):
                        t["note"] += "；执行者中断尚待确认"
            self.publish()
            return {"paused": True}
        if action == "finish":
            closing = t["status"] == "closing"
            if t["status"] not in RUNNING or self.exhausted(t, include_deadline=not closing):
                raise ValueError("当前任务不可完成，请向用户说明状态")
            if any(w["state"] in BUSY if closing else w["state"] != "idle" for w in t["workers"].values()) or t["pending"]:
                raise ValueError("还有执行工作或未回传结果，不能结束目标")
            outcome = args.get("outcome")
            if outcome not in ("met", "unmet"):
                raise ValueError("明确 outcome 为 met 或 unmet")
            evidence = text(args.get("evidence"), "实际验收证据")
            summary = text(args.get("summary"), "结论")
            t.update(status="completed" if outcome == "met" else "stopped", summary=summary,
                     evidence=evidence, note="请核对临时材料去向", updatedAt=self.clock())
            t["completion"] = {"outcome": outcome, "summary": summary, "evidence": evidence,
                               "decidedAt": self.clock(), "threadId": t["host"], "turnId": t["hostTurn"]}
            self.publish()
            result = {"status": t["status"], "message": "验收结论已保存，请向用户交付；最终用量由程序自动更新，无需为数字另开一轮。临时材料未确认无依赖前继续保留。"}
            try:
                self.remove_empty_scratch(t)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                # Cleanup cannot turn a persisted acceptance into a failed tool call.
                warning = "临时材料收尾未完成：" + str(exc)
                t["note"] = "验收结论已保存；" + warning
                self.publish()
                result.update(cleanupWarning=warning,
                              message="验收结论已保存；请单独报告临时材料收尾异常，不要因此再次暂停、重复 finish 或宣称材料已清理。")
            return result
        if action == "handoff":
            return self.do_handoff(t["id"], args.get("summary"))
        raise ValueError("未知任务动作")

    def snapshot_task(self, t):
        return {tid: dict({k: w[k] for k in ("name", "state", "access", "scope")}, cwd=w.get("cwd", t["cwd"]))
                for tid, w in t["workers"].items()}

    def worker_context(self, t, related_workers=()):
        """Keep actionable workers in every prompt; history stays available via status/UI."""
        related = set(related_workers) | {p.get("threadId") for p in t["pending"]}
        rows = self.snapshot_task(t)
        selected = {tid: w for tid, w in rows.items() if w["state"] != "idle" or tid in related}
        counts = {}
        for w in rows.values():
            counts[w["state"]] = counts.get(w["state"], 0) + 1
        omitted = len(rows) - len(selected)
        return (f"执行者总览：共 {len(rows)} 个；按状态计数 {json.dumps(counts, ensure_ascii=False)}；"
                f"待回传报告 {len(t['pending'])} 份。\n"
                f"本次相关执行状态：{json.dumps(selected, ensure_ascii=False)}\n"
                + (f"省略 {omitted} 个无关空闲执行者详情，空闲不等于已验收。完整列表仍在任务页面及 ma4_control(action=status) 的 workers 中；需要复用或追查时按需读取。\n" if omitted else ""))

    def worker_cwd(self, t, w):
        return w.get("cwd", t["cwd"])

    def worker_regions(self, t, w):
        return [str((Path(self.worker_cwd(t, w)) / p).resolve()) for p in w["scope"] or ["."]]

    def authorized_scope(self, t, cwd, access, scope):
        grant = next((g for g in task_workspaces(t) if path_key(g["cwd"]) == path_key(cwd)), None)
        if grant is None:
            raise ValueError("工作目录尚未授权，请提交包含目录与写入范围的草案，等用户确认")
        allowed = checked_scope(cwd, grant["write_scope"])
        regions = checked_scope(cwd, scope)
        if access == "write" and any(not any(Path(p).is_relative_to(a) for a in allowed) for p in regions):
            raise ValueError("写入范围超出该工作目录已确认的授权")

    def dispatch(self, t, instruction, name="执行", session_id=None, access="write", write_scope=None, cwd=None):
        self.begin_closing(t)
        if t["status"] == "closing":
            raise ValueError("时限已到，仅等待现有执行者收尾并汇总，不再新增或续派执行回合")
        if t["status"] not in ACTIVE or t.get("handoff") or not confirmed(t) or t.get("draft"):
            raise ValueError("任务未启动、已暂停或正在交接")
        if self.exhausted(t):
            raise ValueError(self.exhausted(t))
        instruction = text(instruction, "任务指令")
        if instruction.startswith(DISPATCH_PREFIX):
            first, separator, instruction = instruction.partition("\n")
            selected = first[len(DISPATCH_PREFIX):].strip()
            if not separator or (cwd is not None and cwd != selected):
                raise ValueError("工作目录指令格式错误或与 cwd 参数不一致")
            cwd = selected
            instruction = text(instruction, "任务指令")
        if access not in ("read", "write"):
            raise ValueError("access 需为 read 或 write")
        w = t["workers"].get(session_id) if session_id else None
        cwd = text(cwd, "工作目录", 2000) if cwd is not None else self.worker_cwd(t, w or {})
        grant = next((g for g in task_workspaces(t) if path_key(g["cwd"]) == path_key(cwd)), {})
        scope = scopes(grant.get("write_scope") if write_scope is None and access == "write" else write_scope)
        self.authorized_scope(t, cwd, access, scope)
        if session_id:
            if session_id not in t["workers"]:
                raise ValueError("执行会话不属于本任务")
            w = t["workers"][session_id]
            if w["state"] != "idle":
                raise ValueError("执行会话仍在工作或排队，请等结果")
            if access != w["access"]:
                raise ValueError("复用会话不能变更读写权限，请新建会话")
            if path_key(cwd) != path_key(self.worker_cwd(t, w)):
                raise ValueError("复用会话不能更换工作目录，请新建执行会话")
        self.ensure_scratch(t, cwd)
        if not session_id:
            session_id = self.hub.new_thread(cwd, developer_instructions=WORKER_INSTRUCTIONS,
                                             sandbox="read-only" if access == "read" else None, model=t.get("model"))["threadId"]
            w = {"name": text(name, "执行名称", 100), "access": access, "lastCompleted": None}
            t["workers"][session_id] = w
            t.setdefault("metrics", {})[session_id] = {"baseline": {}, "turns": {}}
        w.update(state="queued", cwd=cwd, scope=scope, instruction=instruction, turnId=None, requestId=uuid.uuid4().hex,
                 revision=t.get("revision", 1))
        t["status"] = "waiting"
        self.publish()
        self.hub.rename(session_id, t["name"] + " · " + w["name"])
        return {"session_id": session_id, "state": "queued", "cwd": cwd, "write_scope": scope, "scratch": str(self.scratch(t, cwd)),
                "message": "已排队；请结束本轮，结果会自动回传，无需等待或轮询。"}

    def can_launch(self, t, w):
        active = []
        for other in self.tasks.values():
            if w["access"] == "write" and other["hostBusy"] and overlap(
                    self.worker_regions(t, w), [g["cwd"] for g in task_workspaces(other)]):
                return False
            active.extend((other, x) for x in other["workers"].values() if x["state"] in BUSY)
        if sum(overlap([self.worker_cwd(other, x)], [self.worker_cwd(t, w)]) for other, x in active) >= 4:
            return False
        return w["access"] == "read" or not any(x["access"] == "write" and overlap(
            self.worker_regions(t, w), self.worker_regions(other, x)) for other, x in active)

    def active_writes(self, t):
        return [{"taskId": o["id"], "task": o["name"], "threadId": tid, "name": w["name"],
                 "cwd": self.worker_cwd(o, w), "paths": self.worker_regions(o, w)}
                for o in self.tasks.values() for tid, w in o["workers"].items()
                if w["access"] == "write" and w["state"] in BUSY and overlap(
                    self.worker_regions(o, w), [g["cwd"] for g in task_workspaces(t)])]

    def write_context(self, t):
        writers = self.active_writes(t)
        if not writers:
            return ""
        return ("报告可以先接收，文件验收按实际范围分别进行。以下是仍在写入的范围（发送时快照）：\n"
                + json.dumps(writers, ensure_ascii=False) + "\n"
                "只检查已稳定且不受这些写入影响的产物；相关文件仍在变化时暂缓验收，明确标为待验收，不能据此宣称目标完成。"
                "不要为等待文件稳定而轮询或睡眠；可处理其他报告，结束本轮等待后续结果。\n")

    def report_delivery(self, t):
        return task_policy.report_delivery(t, self.policy_runtime())

    def launch(self, t, tid, w):
        self.begin_closing(t)
        if t["status"] not in ACTIVE or self.exhausted(t):
            return
        cwd = self.worker_cwd(t, w)
        try:
            self.authorized_scope(t, cwd, w["access"], w["scope"])
            self.ensure_scratch(t, cwd)
        except (ValueError, OSError) as exc:
            t.update(status="attention", note="排队工作未启动：" + str(exc))
            self.publish()
            return
        rid = w["requestId"]
        w["state"] = "sending"
        t["outbox"] = {"id": rid, "tid": tid, "kind": "worker", "deliveries": []}
        self.publish()
        message = (f"本次执行任务：\n{w['instruction']}\n"
                   f"实际工作目录：{cwd}；先读取此项目的 AGENTS.md 和 README 等适用约定。\n"
                   f"读写权限：{w['access']}；写入范围（相对上述目录）：{w['scope'] or ['整个项目（独占写入）']}\n"
                   f"临时目录：{self.scratch(t, cwd)}\n预算剩余受中控统一控制，不自行派生其他会话。\n" + EVIDENCE_GUIDANCE)
        try:
            result = self.hub.send_raw(tid, message_envelope(message, rid), rid)
        except Exception as exc:
            t.update(status="attention", note="执行消息发送未确认：" + str(exc)[:150])
            self.publish()
            return
        w.update(state="running", turnId=result.get("turnId"))
        self.record_turn(t, tid, {"id": result.get("turnId"), "status": "inProgress"}, live_start=True)
        w.pop("instruction", None)
        t["outbox"] = {}
        self.publish()

    def event(self, method, p):
        tid = p.get("threadId")
        t = self.owner(tid)
        if not t:
            return
        if method == "thread/tokenUsage/updated":
            total = (p.get("tokenUsage") or {}).get("total") or {}
            old = t["usage"].get(tid, {})
            t["usage"][tid] = {k: max(old.get(k, 0), max(0, int(total.get(k, 0)))) for k in TOKEN_KEYS}
            if p.get("turnId"):
                row = self.record_turn(t, tid, {"id": p["turnId"]})
                before = row.get("cumulative", {})
                row["cumulative"] = {k: max(before.get(k, 0), max(0, int(total.get(k, 0)))) for k in TOKEN_KEYS}
            if t["status"] in TERMINAL and self.exhausted(t):
                t["note"] = "验收后的收尾用量已达到预算；不会再自动发起回合。在途请求的消耗无法撤回。"
            self.publish()
        elif method == "thread/name/updated" and tid == t["host"]:
            name = p.get("threadName") or p.get("name")
            if name:
                t["name"] = str(name)[:100]
                self.publish()
        elif method == "thread/settings/updated":
            model = (p.get("threadSettings") or {}).get("model")
            if model and t.get("model") and model != t["model"] and t["budget"].get("moneyLimit"):
                t["costUncertain"] = True
                self.do_pause(t["id"], "会话模型从外部改变，金额估算失去依据，请改用 token/时限")
        elif method == "turn/started":
            turn = p.get("turn") or {}
            self.record_turn(t, tid, turn, live_start=not p.get("recovered"))
            if tid == t["host"]:
                t.update(hostBusy=True, hostTurn=turn.get("id"))
            elif tid in t["workers"]:
                t["workers"][tid].update(state="running", turnId=turn.get("id"))
            self.publish()
        elif method == "turn/completed":
            turn = p.get("turn") or {}
            self.begin_closing(t)
            self.record_turn(t, tid, turn)
            if tid == t["host"]:
                if t.get("hostTurn") and turn.get("id") != t["hostTurn"]:
                    return
                t.update(hostBusy=False, hostTurn=None)
                if t.get("completion") and t["completion"].get("turnId") == turn.get("id"):
                    t["completion"].setdefault("completedAt", turn.get("completedAt") or self.clock())
                if t.get("handoff") and t["status"] != "closing":
                    self.perform_handoff(t)
                elif t["status"] in ACTIVE and not t["pending"] and not any(w["state"] != "idle" for w in t["workers"].values()):
                    t.update(status="attention", note="中控本轮已结束，尚未明确判定目标完成")
                elif t["status"] == "review" and not t["pending"]:
                    t["status"] = "waiting"  # Reports handled; other workers continue.
                self.publish()
            elif tid in t["workers"]:
                self.complete_worker(t, tid, turn)

    def complete_worker(self, t, tid, turn):
        w = t["workers"][tid]
        turn_id = turn.get("id")
        if not turn_id or turn_id == w.get("lastCompleted"):
            return
        if w.get("turnId") and turn_id != w["turnId"]:
            return
        items = turn.get("items") or []
        if not items:
            turns = self.hub.history(tid, limit=8)["turns"]
            turn = next((x for x in turns if x["id"] == turn_id), turn)
            items = turn.get("items") or []
        replies = [i.get("text", "") for i in items if i.get("type") == "agentMessage" and i.get("phase") != "commentary"]
        result = "\n".join(replies) or "未取得最终摘要，请查看执行会话和实际产物。"
        truncated = len(result) > REPORT_LIMIT
        if truncated:
            result = result[:2000] + "\n…（中间省略；完整回答见执行会话）…\n" + result[-1000:]
        error = turn.get("error")
        if isinstance(error, dict):
            error = error.get("message")
        w.update(state="idle", turnId=None, lastCompleted=turn_id)
        w.pop("instruction", None)
        t["pending"].append({"id": tid + ":" + turn_id, "threadId": tid, "turnId": turn_id,
                             "cwd": self.worker_cwd(t, w), "write_scope": w["scope"], "access": w["access"],
                             "status": turn.get("status"), "targetRevision": w.get("revision", 1),
                             "error": str(error)[:2000] if error else None, "reportTruncated": truncated, "report": result})
        self.publish()

    def do_handoff(self, task_id, summary):
        t = self.get(task_id)
        self.begin_closing(t)
        blocker = self.handoff_blocker(t)
        if blocker:
            raise ValueError(blocker)
        t["handoff"] = text(summary, "交接摘要")
        t["note"] = "等待当前中控结束本轮后交接"
        self.publish()
        if not t["hostBusy"]:
            self.perform_handoff(t)
        return {"handoff": "scheduled"}

    def perform_handoff(self, t):
        summary = t["handoff"]
        old = t["host"]
        # Retire old host before creating the replacement; any failure remains visible.
        t["formerHosts"].append(old)
        t.update(host=None, hostBusy=False, hostTurn=None, note="创建接任中控")
        self.publish()
        try:
            self.new_host(t)
        except Exception:
            t.update(status="attention", note="交接创建未完成，请检查，未自动重建")
            self.publish()
            raise
        t.pop("handoff", None)
        t["handoffPending"] = summary
        t["note"] = "中控已交接"
        self.publish()
        if t["status"] in ACTIVE and not self.exhausted(t):
            self.send_host(t, "你是接任中控，请核对交接说明、实际产物和在途工作后继续。")
        else:
            self.publish()

    def reconcile(self):
        for t in self.tasks.values():
            if not t.get("host"):
                continue
            check = {t["host"]} if t["hostBusy"] or t.get("outbox") or self.recovering and (t["status"] in RUNNING or t.get("completion")) else set()
            check.update(tid for tid, w in t["workers"].items() if w["state"] in BUSY)
            for tid in check:
                self.hub.subscribe(tid)
                turns = self.hub.history(tid, limit=8)["turns"]
                if self.recovering and hasattr(self.hub, "usage_snapshot"):
                    usage = self.hub.usage_snapshot(tid)
                    if usage is not None:
                        self.event("thread/tokenUsage/updated", {"threadId": tid, "tokenUsage": {"total": usage}})
                    elif turns and turns[-1]["status"] != "inProgress" and t["status"] in RUNNING:
                        t.update(status="attention", note="恢复后无法核对累计用量，请核对后继续")
                out = t.get("outbox") or {}
                if out.get("tid") == tid:
                    marker = "[MA4 message:" + out["id"] + "]"
                    sent = next((turn for turn in turns if any(marker in i.get("text", "") for i in turn["items"] if i["type"] == "userMessage")), None)
                    if not sent:
                        t.update(status="attention", note="未找到发送确认，保留待核对操作；不会自动重发")
                        continue
                    t["pending"] = [p for p in t["pending"] if p["id"] not in out["deliveries"]]
                    if out["kind"] == "worker":
                        t["workers"][tid].update(state="running", turnId=sent["id"])
                    else:
                        t.update(hostBusy=True, hostTurn=sent["id"])
                    t["outbox"] = {}
                if not turns:
                    continue
                latest = turns[-1]
                # Timing is safe to recover from the bounded history page. A cumulative
                # snapshot has no turn ID: never invent a per-turn token split from it.
                self.record_turn(t, tid, latest)
                if latest["status"] == "inProgress":
                    self.event("turn/started", {"threadId": tid, "turn": latest, "recovered": True})
                else:
                    self.event("turn/completed", {"threadId": tid, "turn": latest})
        self.recovering = False
        self.connection_note = None
        self.publish()

    def tick(self):
        if self.error or not self.hub.daemon.get("connected"):
            return
        if self.overflow:
            for t in self.tasks.values():
                if t["status"] in RUNNING:
                    self.do_pause(t["id"], "事件队列超限，暂停后核对状态")
            self.overflow = False
        for t in self.tasks.values():
            self.begin_closing(t)
        if self.clock() >= self.next_reconcile:
            self.next_reconcile = self.clock() + 15
            self.reconcile()
        if self.recovering:
            return
        for t in self.tasks.values():
            self.begin_closing(t)
            reason = self.exhausted(t, include_deadline=False)
            if reason and (t["status"] in RUNNING or t["hostBusy"] or any(w["state"] in BUSY for w in t["workers"].values())):
                self.do_pause(t["id"], reason)
                t["status"] = "budget"
                self.publish()
                continue
            if t["status"] not in RUNNING:
                continue
            if t["status"] == "closing":
                self.close_at_boundary(t)
                continue
            if t.get("outbox") or t.get("handoff"):
                continue
            if t["pending"] and not t["hostBusy"]:
                pending = t["pending"][:8]
                message = "以下是执行者的未独立验证报告。先对照完整 target 检查实际产物，不把报告当作事实或验收结论。\n" + json.dumps(pending, ensure_ascii=False)
                t["status"] = "review"
                self.send_host(t, message, deliveries=[p["id"] for p in pending], source="worker_report")
                continue
            for tid, w in t["workers"].items():
                if w["state"] == "queued" and self.can_launch(t, w):
                    self.launch(t, tid, w)
                    break

    def do_artifacts(self, task_id, action="list", paths=None, reason=""):
        t = self.get(task_id)
        roots = {cwd: self.scratch(t, cwd) for cwd in self.scratch_cwds(t)}
        retained = {}
        for key in t["retained"]:
            p = Path(key)
            identity = path_key(p if p.is_absolute() else self.scratch(t) / p)
            retained.setdefault(identity, []).append(key)
        files, total = [], 0
        for cwd, root in roots.items():
            if not root.exists() and not is_link(root):
                continue
            self.ensure_scratch(t, cwd)
            for base, dirs, names in os.walk(root, followlinks=False):
                links = [d for d in dirs if is_link(Path(base) / d)]
                dirs[:] = [d for d in dirs if d not in links]
                for name in names + links:
                    p = Path(base) / name
                    rel = p.relative_to(root).as_posix()
                    if rel == ".ma4-owner.json":
                        continue
                    key = rel if cwd == t["cwd"] else str(p)
                    s = p.lstat()
                    total += s.st_size
                    files.append({"path": key, "cwd": cwd, "bytes": s.st_size, "symlink": is_link(p),
                                  "retained": "; ".join(dict.fromkeys(t["retained"][k]
                                      for k in retained.get(path_key(p), []))) or None})
        if action == "list":
            return {"root": str(self.scratch(t)), "roots": [str(p) for p in roots.values()],
                    "files": files[:200], "count": len(files), "bytes": total,
                    "truncated": len(files) > 200, "retained": t["retained"]}
        reason = text(reason, "清理或保留理由", 2000)
        if not isinstance(paths, list) or not paths or len(paths) > 200:
            raise ValueError("需明确列出 1–200 个文件")
        if action == "clean" and any(w["state"] in BUSY for w in t["workers"].values()):
            raise ValueError("任务执行者仍在运行，暂不清理")
        selected = []
        available = {f["path"]: f for f in files}
        for key in paths:
            if not isinstance(key, str) or key not in available:
                raise ValueError("请使用材料列表中的精确路径；不能清理归属标记、整个目录或任务外文件")
            root = roots[available[key]["cwd"]]
            p = Path(key) if Path(key).is_absolute() else root / key
            rel = p.relative_to(root).as_posix()
            if rel in (".", ".ma4-owner.json"):
                raise ValueError("不能清理归属标记或整个目录")
            if any(is_link(q) for q in [p, *p.parents] if q == root or root in q.parents):
                raise ValueError("不跟随或删除符号链接：" + rel)
            s = p.lstat()
            if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
                raise ValueError("只清理本任务的普通独立文件：" + rel)
            selected.append((key, p, s, root))
        if action == "keep":
            for rel, p, _, _ in selected:
                for old in retained.get(path_key(p), []):
                    t["retained"].pop(old, None)
                t["retained"][rel] = reason
        elif action == "clean":
            for rel, p, before, root in selected:
                now = p.lstat()
                if (now.st_ino, now.st_mtime_ns, now.st_size) != (before.st_ino, before.st_mtime_ns, before.st_size):
                    raise ValueError("文件发生变化，停止清理：" + rel)
                p.unlink()
                for old in retained.get(path_key(p), []):
                    t["retained"].pop(old, None)
                parent = p.parent
                while parent != root:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        else:
            raise ValueError("未知材料动作")
        t["note"] = ("已清理" if action == "clean" else "保留") + f" {len(selected)} 个临时文件：{reason}"
        self.publish()
        return {"action": action, "count": len(selected), "reason": reason}

    def remove_empty_scratch(self, t):
        for cwd in self.scratch_cwds(t):
            root = self.scratch(t, cwd)
            if not root.exists() and not is_link(root):
                continue
            self.ensure_scratch(t, cwd)
            marker = root / ".ma4-owner.json"
            if set(root.iterdir()) == {marker}:
                marker.unlink()
                root.rmdir()

    def do_remove(self, task_id):
        """Explicit user action; archive Codex threads, never delete transcripts/files."""
        t = self.get(task_id)
        if t["status"] in RUNNING or t["hostBusy"] or t.get("outbox") or any(w["state"] in BUSY for w in t["workers"].values()):
            raise ValueError("任务还有运行、排队或未确认的工作，不能移除")
        inventory = self.do_artifacts(task_id)
        if inventory.get("files"):
            raise ValueError("临时材料尚未收尾，请先转正或清理，再移除任务")
        ids = [tid for tid in [t["host"], *t["formerHosts"], *t["workers"]] if tid]
        for tid in ids:
            self.hub.archive_thread(tid)
        self.remove_empty_scratch(t)
        del self.tasks[task_id]
        self.publish()
        return {"removed": True, "archivedThreads": len(ids), "message": "任务关联已移除，会话已归档；对话和项目正式文件仍保留。"}
