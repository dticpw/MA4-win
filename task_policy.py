"""Pure task decisions: input snapshots + explicit runtime -> values only.

No Hub, RPC, filesystem, clock reads or task mutations. Controllers owns effects.
See ARCHITECTURE.md before adding a dependency or changing the runtime boundary.
"""
from dataclasses import dataclass
import math

ACTIVE = frozenset({"running", "waiting", "review"})
RUNNING = ACTIVE | {"closing"}
BUSY = frozenset({"running", "sending"})
TERMINAL = frozenset({"completed", "stopped"})
TOKEN_KEYS = ("totalTokens", "inputTokens", "cachedInputTokens", "outputTokens")


@dataclass(frozen=True)
class RuntimeState:
    now: float
    connected: bool
    recovering: bool = False
    error: str | None = None


def activity_timestamp(value):
    """Unix seconds from explicit session/turn metadata, never task operation time."""
    return value if (type(value) in (int, float) and math.isfinite(value) and value > 0) else 0


def turn_activity_at(turns):
    # Legacy estimated timing can include recovery time, so is not activity evidence.
    return max((activity_timestamp(row.get(key)) for row in turns if not row.get("timeEstimated")
                for key in ("startedAt", "completedAt")), default=0)


def confirmed(t):
    # Existing tasks keep the goal the user had already supplied.
    return t.get("goalConfirmed", bool(t.get("target")))


def usage(t):
    return {k: sum(v.get(k, 0) for v in t["usage"].values()) for k in TOKEN_KEYS}


def cost(t):
    rates = t["budget"].get("rates")
    if not rates:
        return None
    u = usage(t)
    return (max(0, u["inputTokens"] - u["cachedInputTokens"]) * rates["input"]
            + u["cachedInputTokens"] * rates["cached"] + u["outputTokens"] * rates["output"]) / 1e6


def exhausted(t, now, include_deadline=True):
    b = t["budget"]
    if b.get("tokenLimit") and usage(t)["totalTokens"] >= b["tokenLimit"]:
        return "已达到 token 上限"
    if b.get("moneyLimit") and cost(t) >= b["moneyLimit"]:
        return "已达到估算金额上限"
    if include_deadline and b.get("deadline") and now >= b["deadline"]:
        return "已到截止时间"
    return None


def control_blocker(runtime):
    if runtime.error:
        return "中控运行控制异常，请先核对页面错误和服务日志"
    if not runtime.connected:
        return "后台连接已断开，请等待重连后核对状态"
    if runtime.recovering:
        return "正在核对会话和发送状态，请稍后再操作"
    return None


def confirm_blocker(t, runtime):
    # Shared by the read-only view and the mutation; budget/goal validation
    # still uses the actual submitted form, so an expired budget is editable.
    if control_blocker(runtime):
        return control_blocker(runtime)
    if t["hostBusy"] or any(w["state"] in BUSY for w in t["workers"].values()) or t.get("outbox") or t.get("handoff"):
        return "还有回合或发送操作未结束，请等它们返回后再确认目标"
    if t["status"] in RUNNING:
        return "请先暂停任务，再确认目标与预算"
    return None


def handoff_blocker(t, runtime):
    if control_blocker(runtime):
        return control_blocker(runtime)
    if t["status"] == "closing" or t["status"] in ACTIVE and exhausted(t, runtime.now) == "已到截止时间":
        return "到期收尾中，不再交接或启动新的中控"
    if t["status"] in TERMINAL or t.get("outbox"):
        return "任务已结束或有发送状态未确认"
    if not t.get("host"):
        return "中控会话尚未创建成功，请先检查创建失败原因"
    if t.get("handoff"):
        return "交接已安排，请等待当前回合结束，不要重复交接"
    return None


def report_delivery(t, runtime):
    """Derived view of the existing durable queue, not a second delivery log."""
    pending = t["pending"]
    state, reason = "none", ""
    if pending:
        if runtime.error:
            state, reason = "error", "运行控制异常，报告保留待核对"
        elif not runtime.connected:
            state, reason = "disconnected", "连接断开，报告已保存，等待重新连接"
        elif runtime.recovering:
            state, reason = "recovering", "正在恢复并核对发送状态，避免重复回传"
        elif t.get("outbox"):
            state, reason = "sending", "正在确认消息发送结果，确认前不会重复回传"
        elif t.get("handoff"):
            state, reason = "handoff", "等待中控交接完成"
        elif t["status"] not in RUNNING:
            state, reason = "retained", "任务未自动运行，报告保留；普通聊天不会恢复任务"
        elif exhausted(t, runtime.now, include_deadline=False):
            state, reason = "budget", "已到 token 或金额上限，报告保留待你处理"
        elif t["hostBusy"]:
            state, reason = "host_busy", "中控正在处理当前回合，结束后再回传"
        elif t["status"] == "closing" and (not t["closing"]["needsReview"] or t["closing"]["reviewStarted"]):
            state, reason = "retained", "到期自动汇总已安排或不再自动汇总，剩余报告保留待续接"
        elif t["status"] == "closing" and any(w["state"] in BUSY for w in t["workers"].values()):
            state, reason = "closing", "正在到期收尾，等本任务执行者返回后统一汇总"
        else:
            state, reason = "ready", "中控空闲，等待自动回传；其他执行者写入不会阻挡报告"
    return {"count": len(pending), "state": state, "reason": reason,
            "reports": [{"id": p["id"], "threadId": p.get("threadId"), "turnId": p.get("turnId"),
                         "name": t["workers"].get(p.get("threadId"), {}).get("name", "执行者报告")}
                        for p in pending]}


def diagnosis(t, runtime):
    """Explain existing state, without RPCs, writes, retries or semantic guesses."""
    states = [w["state"] for w in t["workers"].values()]
    work = {state: states.count(state) for state in ("running", "sending", "queued", "idle")}
    work["unknown"] = len(states) - sum(work.values())
    work.update(host=bool(t["hostBusy"]), reports=len(t["pending"]))
    busy = work["host"] or work["running"] or work["sending"]
    budget = exhausted(t, runtime.now)
    facts = []
    if t.get("handoffPending"):
        facts.append("接任中控已创建，交接说明尚未发送；下一次消息会附带说明。")
    if budget and t["status"] not in TERMINAL:
        facts.append(budget + "；暂停、交接或重连不会延长预算。")
    # Old hosts and uncertain timing cannot establish the latest host failure.
    turns = list(t.get("metrics", {}).get(t.get("host"), {}).get("turns", {}).values())
    ordered = turns and all(activity_timestamp(r.get("startedAt")) and not r.get("timeEstimated") for r in turns)
    latest = max(turns, key=lambda r: r["startedAt"]) if ordered else None
    latest = latest if latest and sum(r["startedAt"] == latest["startedAt"] for r in turns) == 1 else None

    if runtime.error:
        code, title, reason, step = "error", "运行控制异常", "自动运行已停止，当前工作状态需要核对。", "你或维护 Agent：查看页面错误和服务日志，处理后再核对会话；不要直接重复启动。"
    elif not runtime.connected:
        code, title, reason, step = "disconnected", "后台连接已断开", "下方是最后记录的工作数量，不能据此判断实际回合已经停止。", "MA4：重连后核对会话与发送记录；你可先查看已有记录，暂不确认启动或交接。"
    elif runtime.recovering:
        code, title, reason, step = "recovering", "正在核对运行状态", "正在核对会话及发送结果，工作数量可能尚未更新。", "MA4：核对完成后更新；若持续停留，你或维护 Agent 再检查连接错误和服务日志。"
    elif t.get("outbox"):
        code, title, reason, step = "sending", "消息发送结果待确认", "已记录发送操作，但尚未取得确认；不能判断它未送达。", "MA4：按消息标记核对；若持续未确认，你或维护 Agent 检查对应会话，避免重复发送或交接。"
    elif not t.get("host"):
        code, title, reason, step = "missing_host", "中控创建未完成", "当前没有可接续的中控会话。", "你或维护 Agent：查看任务记录和创建错误，核实是否已创建会话，再决定修复方式。"
    elif t["status"] == "closing":
        code, title, reason, step = "closing", "时限已到，正在收尾", "不再启动新工作，已有回合可能仍在运行，结束时间可晚于时限。", "执行者：结束当前工作并报告；MA4 按既有规则安排收尾汇总。你需要立刻中断时可点“立即停止”。"
    elif t.get("handoff"):
        code, title, reason, step = "handoff", "交接已安排", "等待当前中控回合结束，再创建接任中控。", "MA4：完成交接并保留目标、预算和执行者；请勿重复交接。"
    elif t["status"] in TERMINAL:
        code = t["status"]
        title = "目标已记录为达标" if code == "completed" else "任务已记录为未达标结束"
        reason = "结束记录已保存。" + ("仍有回合在收尾，结束记录不代表所有回合已停止。" if busy else "未记录在途回合。")
        step = "你：查看验收结论及实际成果；需要继续时重新核对目标与预算并确认。"
    elif t["status"] not in RUNNING and busy:
        code, title, reason, step = "pausing", "自动推进已停，仍有回合未结束", "暂停或保存草案不等于中断已经完成，也可能有讨论回合在运行。", "你：等回合返回后再确认；需要中断现有回合时可点“停止在途回合”。"
    elif budget:
        code, title, reason, step = "budget", "预算已到，需确认后继续", budget + "，不能按当前预算启动新工作。", "你：打开“查看并确认后继续”，核对目标与目录，明确调整预算后再启动；仅聊天不会恢复自动推进。"
        if busy or t["status"] in RUNNING:
            step = "MA4：按预算规则停止新增工作并处理在途回合。你：等回合结束、任务停止推进后，再核对并调整预算。"
    elif t.get("costUncertain"):
        code, title, reason, step = "cost_uncertain", "金额估算需要处理", "会话模型发生变化，现有金额估算不再可靠。", "你：在目标与预算表单中改用 token 或时限，核对后确认。"
    elif t.get("draft") or not confirmed(t):
        code, title, reason, step = "draft", "目标尚待确认", "讨论或新草案不等于已授权自主推进。", "你：查看草案中的目标、验收要求、目录和预算，再决定保存或启动。"
    elif t.get("handoffPending"):
        code, title, reason, step = "handoff_ready", "已交接，等待继续", "接任中控尚未收到交接说明。", "你：核对目标与预算后确认继续；接任中控先核对已有成果和在途工作。"
    elif t["status"] == "paused":
        code, title, reason, step = "paused", "任务已暂停", "未记录在途回合，排队工作和待回传报告保留。", "你：需要继续时查看并确认目标与预算；普通聊天只作讨论。"
    elif t["hostBusy"]:
        code, title, reason, step = "host_busy", "中控回合仍在进行", "当前记录显示中控忙碌；仅凭长时间无输出不能判定卡死。", "中控：处理当前回合。你可查看最近消息和工具状态，再决定等待、暂停或交接。"
    elif work["running"] or work["sending"]:
        code, title, reason, step = "workers_busy", "执行者仍在工作", "中控当前空闲，不代表整个任务已经停住。", "执行者：完成工作并报告；MA4 在中控空闲且条件允许时自动回传。"
    elif work["unknown"]:
        code, title, reason, step = "unknown_work", "有执行者状态待核对", "已有执行者状态无法归类，不能把它们算作空闲。", "你或维护 Agent：检查对应执行会话与任务记录，再决定接续方式。"
    elif t["status"] in RUNNING and work["reports"]:
        code, title, reason, step = "reports", "报告等待中控处理", report_delivery(t, runtime)["reason"], "MA4：按现有回传条件处理；中控仍须独立检查成果。"
    elif t["status"] in RUNNING and work["queued"]:
        code, title, reason, step = "queued", "有工作等待启动", "排队工作尚未开始；调度会核对并发、写入范围及预算。", "MA4：条件满足后启动。若持续等待，你或维护 Agent 检查其他任务的在途写入和任务记录。"
    elif latest and latest.get("status") == "failed":
        code, title, reason, step = "failed", "当前中控最近一轮失败", "已有可排序的回合记录显示失败，但未据此确定根因。", "你或维护 Agent：查看当前中控该轮错误及工具结果，处理后决定恢复或交接。"
    else:
        code, title, reason, step = "idle", "未记录在途工作，需核对下一步", "回合空闲不等于目标达标；现有状态不足以判定具体停滞原因。", "你或维护 Agent：查看中控最近回复、任务记录和成果，再决定继续讨论、确认恢复或交接。"
    return {"code": code, "title": title, "reason": reason, "nextStep": step, "facts": facts, "work": work,
            "confirmBlocker": confirm_blocker(t, runtime), "handoffBlocker": handoff_blocker(t, runtime),
            "canPause": t["status"] not in TERMINAL and bool(busy or t["status"] in RUNNING)}
