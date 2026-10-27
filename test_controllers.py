import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from controllers import Controllers, overlap, budget_value, scopes, TOKEN_KEYS, DRAFT_PREFIX, WORKSPACES_MARKER, workspace_value, task_workspaces


class Hub:
    def __init__(self):
        self.daemon = {"connected": True}
        self.sent, self.events, self.interrupted = [], [], []
        self.steered = []
        self.histories, self.sessions = {}, {}

    def emit(self, kind, **data):
        self.events.append((kind, data))

    def new_thread(self, cwd, **options):
        tid = "thread-" + str(len(self.sessions) + 1)
        self.sessions[tid] = dict(options, cwd=cwd)
        return {"threadId": tid}

    def rename(self, tid, name):
        pass

    def send_raw(self, tid, text, request_id, *, skills=None):
        turn = "turn-" + str(len(self.sent) + 1)
        self.sent.append((tid, text, request_id, turn))
        self.histories.setdefault(tid, []).append({"id": turn, "status": "inProgress",
            "items": [{"type": "userMessage", "text": text}]})
        return {"turnId": turn, "mode": "start"}

    def history(self, tid, limit=8):
        return {"turns": copy.deepcopy(self.histories.get(tid, [])[-limit:])}

    def subscribe(self, tid):
        pass

    def interrupt(self, tid):
        self.interrupted.append(tid)

    def steer_only(self, tid, turn_id, message, request_id):
        self.steered.append((tid, turn_id, message, request_id))

    def archive_thread(self, tid):
        self.sessions.pop(tid, None)


class ControllerTest(unittest.TestCase):
    def symlink(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows 尚未授予符号链接权限；Junction 另有实机检查")
            raise

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hub = Hub()
        self.now = [1000.0]
        self.c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, name="任务", start=False):
        r = self.c.do_create(str(self.root), name, "完成目标并独立验收", {"tokenLimit": 1000})
        t = self.c.tasks[r["taskId"]]
        self.confirm(t, start=start)
        return t

    def confirm(self, t, start=False):
        draft = t.get("draft") or {"target": t["target"], "budget": t["budget"]}
        return self.c.do_confirm(t["id"], t.get("draftRevision", 0), t["name"], draft["target"], draft["budget"], start)

    def active(self):
        t = self.task()
        t["status"] = "running"
        return t

    def worker(self, t, **kw):
        tid = self.c.dispatch(t, "做出实际成果", **kw)["session_id"]
        return tid, t["workers"][tid]

    def finish_worker(self, t, tid, w, report="已输出 result.txt；请验收"):
        turn = {"id": w["turnId"], "status": "completed", "items": [{"type": "agentMessage", "phase": "final_answer", "text": report}]}
        self.hub.histories[tid][-1].update(turn)
        self.c.event("turn/completed", {"threadId": tid, "turn": turn})
        return turn

    def test_project_can_have_two_independent_tasks(self):
        a, b = self.task("甲"), self.task("乙")
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(a["host"], b["host"])
        self.assertEqual(a["cwd"], b["cwd"])
        self.assertEqual(len(self.hub.sent), 0)  # create doesn't spend model tokens

    def test_host_has_full_capability_but_delegates_main_implementation(self):
        t = self.task()
        settings = self.hub.sessions[t["host"]]
        self.assertEqual(settings["sandbox"], "danger-full-access")
        self.assertEqual(settings["approval_policy"], "never")
        self.assertIn("主要制作、批量修改、反复调试和说明整理默认交给执行者", settings["developer_instructions"])
        self.assertIn("主要制作、批量修改、反复调试和说明整理默认交给执行者", self.c.context(t))
        t["status"] = "running"
        reader, _ = self.worker(t, access="read")
        self.assertEqual(self.hub.sessions[reader]["sandbox"], "read-only")
        self.assertNotIn("approval_policy", self.hub.sessions[reader])

    def test_prompt_omits_idle_history_but_status_and_ui_keep_all_workers(self):
        t = self.active()
        for i in range(20):
            _, w = self.worker(t, name=f"旧制作{i}", write_scope=[f"old/{i}/" + "long" * 50])
            w["state"] = "idle"
        before = copy.deepcopy(t)
        context = self.c.context(t)
        self.assertIn("省略 20 个", context)
        self.assertIn("空闲不等于已验收", context)
        self.assertNotIn("long" * 50, context)
        result = self.c.tool_call({"threadId": t["host"], "tool": "ma4_control",
                                   "arguments": {"action": "status"}})
        self.assertEqual(len(result["workers"]), 20)
        self.c.publish(save=False)
        self.assertEqual(len(self.c.snapshot()["tasks"][0]["workers"]), 20)
        self.assertEqual(t, before)
        self.assertFalse(self.hub.sent)

    def test_prompt_keeps_every_nonidle_worker_and_pending_failed_report(self):
        t = self.active()
        for state in ("running", "sending", "queued", "unknown", "idle"):
            tid, w = self.worker(t, name=state, write_scope=[state + "-scope"])
            w["state"] = state
        t["pending"] = [{"id": "report", "threadId": tid, "turnId": "failed-turn",
                         "status": "failed", "text": "失败：输出缺失"}]
        context = self.c.context(t)
        for state in ("running", "sending", "queued", "unknown", "idle"):
            self.assertIn(state + "-scope", context)
        self.assertIn("待回传报告 1 份", context)
        self.assertNotIn("省略", self.c.worker_context(t))
        before = copy.deepcopy(t["pending"])
        self.c.context(t)
        self.assertEqual(t["pending"], before)

    def test_named_idle_worker_in_user_message_is_included_on_start_and_steer(self):
        t = self.active()
        tid, w = self.worker(t, name="屋顶返修", write_scope=["art/roof"])
        w["state"] = "idle"
        _, old = self.worker(t, name="无关地板", write_scope=["art/unrelated-floor"])
        old["state"] = "idle"
        for message in ("请复用屋顶返修", f"看看 {tid} 的结果"):
            self.c.do_send(t["host"], message, message)
            payload = self.hub.sent[-1][1]
            self.assertIn("art/roof", payload)
            self.assertNotIn("art/unrelated-floor", payload)
        self.assertTrue(t["hostBusy"])

    def test_program_status_does_not_rewrite_confirmed_goal_or_draft(self):
        t = self.task()
        t.update(target="保留全部约束。正式目标仍为修订5，此草案仅供确认。", revision=6)
        self.c.stage_draft(t, "新目标：只改屋顶", "controller")
        before = copy.deepcopy(t)
        context = self.c.context(t)
        for value in (t["target"], t["draft"]["target"], "目标修订 6", "任务状态 paused",
                      "有待确认草案，禁止按新草案执行", "tokenLimit", t["cwd"],
                      "不自行删减或扩权", "目标草案只写成果、范围、约束和验收"):
            self.assertIn(value, context)
        self.assertEqual(t, before)

    def test_reused_worker_receives_current_test_and_closeout_guidance(self):
        t = self.active()
        tid, w = self.worker(t, write_scope=["art"])
        w["state"] = "idle"
        self.c.dispatch(t, "原作者修正", session_id=tid, write_scope=["art"])
        self.c.tick()
        payload = self.hub.sent[-1][1]
        self.assertIn("优先复用项目已有且适用的测试入口", payload)
        self.assertIn("实现、自测和本轮必要说明由同一执行者", payload)
        self.assertIn("原作者修正", payload)
        self.assertEqual(len(t["workers"]), 1)

    def test_creation_only_needs_project_and_name_and_cannot_start(self):
        result = self.c.do_create(str(self.root), "先商量")
        t = self.c.tasks[result["taskId"]]
        self.assertEqual(t["target"], "")
        self.assertFalse(t["goalConfirmed"])
        self.assertEqual(t["status"], "draft")
        self.assertFalse(self.hub.sent)
        with self.assertRaisesRegex(ValueError, "确认"):
            self.c.do_resume(t["id"])
        with self.assertRaises(ValueError):
            self.c.do_create(str(self.root), "不能一步启动", "目标", start=True)
        self.assertEqual(len(self.c.tasks), 1)

    def test_idea_discussion_proposal_and_explicit_confirmation(self):
        result = self.c.do_create(str(self.root), "美术讨论", idea="先看看人物比例")
        t = self.c.tasks[result["taskId"]]
        self.assertIn("[MA4 source:user]", self.hub.sent[-1][1])
        self.assertEqual(t["target"], "")
        with self.assertRaises(ValueError): self.worker(t)
        proposed = "目标：比例协调\n范围：代表角色\n验收：实机对照"
        self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
            "action": "pause", "summary": DRAFT_PREFIX + proposed}})
        self.assertEqual(t["draft"]["target"], proposed)
        self.assertEqual(t["draft"]["source"], "controller")
        self.assertEqual(t["target"], "")
        with self.assertRaisesRegex(ValueError, "回合"):
            self.confirm(t, start=True)
        self.finish_host(t)
        self.now[0] += 3000
        self.c.tick()
        self.assertEqual(t["status"], "draft")
        self.assertEqual(len(self.hub.sent), 1)
        self.confirm(t, start=True)
        self.assertEqual(t["target"], proposed)
        self.assertEqual(t["budget"]["deadline"], self.now[0] + 7200)
        self.assertEqual(t["firstStartedAt"], self.now[0])
        self.assertIn("[MA4 source:automatic]", self.hub.sent[-1][1])
        self.assertEqual(t["status"], "running")

    def test_stale_or_invalid_confirmation_cannot_apply_goal_or_budget(self):
        t = self.task()
        old = copy.deepcopy(t)
        old_revision = t["draftRevision"]
        self.c.stage_draft(t, "新草案", "controller")
        with self.assertRaisesRegex(ValueError, "已更新"):
            self.c.do_confirm(t["id"], old_revision, "新名", "过期草案", {"tokenLimit": 5000})
        self.assertEqual(t["target"], old["target"])
        self.assertEqual(t["budget"], old["budget"])
        with self.assertRaises(ValueError):
            self.c.do_confirm(t["id"], t["draftRevision"], t["name"], "", {})
        self.assertEqual(t["target"], old["target"])
        with self.assertRaisesRegex(ValueError, "截止时间"):
            self.c.do_confirm(t["id"], t["draftRevision"], t["name"], "新目标", {"deadline": 900})
        self.assertEqual(t["budget"], old["budget"])
        self.confirm(t)
        self.assertEqual(t["target"], "新草案")
        self.assertEqual(t["status"], "paused")
        self.assertFalse(self.hub.sent)

    def test_goal_proposal_stops_new_work_but_waits_for_old_worker(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick()
        self.assertEqual(w["state"], "running")
        original = t["target"]
        self.c.stage_draft(t, "新的范围与验收", "controller")
        self.assertEqual(t["target"], original)
        self.assertFalse(self.hub.interrupted)
        with self.assertRaises(ValueError): self.worker(t)
        with self.assertRaises(ValueError): self.confirm(t, start=True)
        self.finish_worker(t, tid, w)
        self.c.tick()
        self.assertEqual(len(self.hub.sent), 1)  # no automatic host reply while paused
        self.assertEqual(len(t["pending"]), 1)
        self.confirm(t)
        self.assertEqual(t["revision"], 2)
        self.assertEqual(t["status"], "paused")

    def test_after_deadline_discussion_does_not_restart_or_reset_budget(self):
        for status in ("paused", "budget", "completed"):
            t = self.task(name=status)
            t.update(status=status, budget={"deadline": 900, "currency": "CNY"})
            self.c.do_send(t["host"], "只是讨论，开始吧也不是按钮确认", status)
            self.assertEqual(t["status"], status)
            self.assertEqual(t["budget"]["deadline"], 900)
            with self.assertRaises(ValueError): self.worker(t)
            self.finish_host(t)
            self.c.tick()
            self.assertEqual(t["status"], status)
        self.assertEqual(len(self.hub.sent), 3)

    def test_discussion_still_obeys_token_and_money_limits(self):
        t = self.task()
        self.c.do_send(t["host"], "继续讨论", "discussion")
        self.c.event("thread/tokenUsage/updated", {"threadId": t["host"],
            "tokenUsage": {"total": {"totalTokens": 1000}}})
        self.c.tick()
        self.assertIn(t["host"], self.hub.interrupted)
        with self.assertRaisesRegex(ValueError, "token"):
            self.c.do_send(t["host"], "再讨论", "blocked")

    def test_pending_draft_survives_restart_and_legacy_goal_stays_confirmed(self):
        t = self.task()
        self.c.stage_draft(t, "待确认内容", "controller")
        restored = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        restored.tick()
        rt = restored.tasks[t["id"]]
        self.assertEqual(rt["draft"], t["draft"])
        self.assertEqual(rt["target"], t["target"])
        with self.assertRaises(ValueError): restored.do_resume(t["id"])
        legacy = self.task("旧任务")
        legacy.pop("goalConfirmed"); legacy.pop("draftRevision")
        self.c.publish()
        restored = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        restored.tick()
        self.assertEqual(restored.tasks[legacy["id"]]["target"], legacy["target"])
        self.assertFalse(self.hub.sent)
        restored.do_resume(legacy["id"])
        self.assertEqual(len(self.hub.sent), 1)

    def test_pending_draft_workers_keep_old_budget_without_automatic_review(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick()
        self.c.stage_draft(t, "新的待确认草案", "controller")
        t["budget"]["deadline"] = self.now[0]
        self.c.tick()
        self.assertEqual(t["status"], "closing")
        self.assertEqual(len(self.hub.steered), 1)
        self.assertFalse(self.hub.interrupted)
        self.finish_worker(t, tid, w)
        self.c.tick()
        self.assertEqual(t["status"], "budget")
        self.assertEqual(len(self.hub.sent), 1)
        self.assertEqual(len(t["pending"]), 1)
        self.assertEqual(t["draft"]["target"], "新的待确认草案")

    def test_pending_draft_worker_still_obeys_hard_limit_when_host_idle(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick()
        self.c.stage_draft(t, "待确认目标", "controller")
        self.c.event("thread/tokenUsage/updated", {"threadId": tid, "tokenUsage": {"total": {"totalTokens": 1000}}})
        self.c.tick()
        self.assertIn(tid, self.hub.interrupted)
        self.assertEqual(t["status"], "budget")

    def test_budget_required_before_autonomy_and_cannot_be_raised_by_tool(self):
        t = self.task()
        t["budget"] = {}
        with self.assertRaises(ValueError): self.c.do_resume(t["id"])
        with self.assertRaises(ValueError):
            self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {"action": "raise_budget"}})
        for bad in [{"tokenLimit": float("nan")}, {"moneyLimit": 10}, {"deadline": True},
                    {"durationMinutes": 0}, {"durationMinutes": True}, {"durationMinutes": float("inf")}]:
            with self.assertRaises(ValueError): budget_value(bad)

    def test_default_two_hours_begin_at_start_not_creation(self):
        result = self.c.do_create(str(self.root), "默认预算", "完成目标")
        t = self.c.tasks[result["taskId"]]
        self.assertEqual(t["budget"], {"durationMinutes": 120, "currency": "CNY"})
        self.now[0] += 10000  # discussion time does not use the two hours
        self.assertEqual(len(self.hub.sent), 0)
        self.confirm(t, start=True)
        self.assertEqual(t["budget"], {"deadline": self.now[0] + 7200, "currency": "CNY"})
        self.now[0] += 7200
        self.c.tick()
        self.assertEqual(t["status"], "closing")
        self.assertEqual(self.hub.interrupted, [])
        self.assertEqual(self.hub.steered[0][:2], (t["host"], t["hostTurn"]))
        self.finish_host(t)
        self.c.tick()
        self.assertEqual(t["status"], "budget")

    def finish_host(self, t):
        turn = {"id": t["hostTurn"], "status": "completed", "items": [{"type": "agentMessage", "text": "已保存进度"}]}
        self.hub.histories[t["host"]][-1].update(turn)
        self.c.event("turn/completed", {"threadId": t["host"], "turn": turn})

    def test_deadline_waits_for_worker_then_one_final_controller_turn(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick()
        t["budget"]["deadline"] = self.now[0]
        self.c.tick(); self.c.tick()
        self.assertEqual(t["status"], "closing")
        self.assertEqual(w["state"], "running")
        self.assertEqual(len(self.hub.steered), 1)
        self.assertEqual(self.hub.interrupted, [])
        with self.assertRaisesRegex(ValueError, "不再新增"):
            self.c.dispatch(t, "继续扩大")
        with self.assertRaises(ValueError): self.c.do_handoff(t["id"], "新中控")
        self.finish_worker(t, tid, w)
        self.c.tick()
        self.assertEqual(len(self.hub.sent), 2)
        self.assertIn("到期收尾汇总", self.hub.sent[-1][1])
        self.assertEqual(t["pending"], [])
        self.finish_host(t)
        for _ in range(3): self.c.tick()
        self.assertEqual(t["status"], "budget")
        self.assertEqual(len(self.hub.sent), 2)
        self.assertNotIn("completion", t)  # no fabricated acceptance

    def test_deadline_restart_preserves_notices_and_single_review(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick()
        t["budget"]["deadline"] = self.now[0]
        self.c.tick()
        self.c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.c.tick()
        t = self.c.tasks[t["id"]]; w = t["workers"][tid]
        self.assertEqual(len(self.hub.steered), 1)
        self.finish_worker(t, tid, w); self.c.tick()
        self.c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.c.tick()
        t = self.c.tasks[t["id"]]
        self.assertEqual(len(self.hub.sent), 2)
        self.finish_host(t); self.c.tick()
        self.assertEqual((t["status"], len(self.hub.sent)), ("budget", 2))

    def test_closing_can_record_an_honest_outcome_after_workers_return(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick(); t["budget"]["deadline"] = self.now[0]; self.c.tick()
        self.finish_worker(t, tid, w); self.c.tick()
        self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
            "action": "finish", "outcome": "unmet", "summary": "还没做好", "evidence": "已核对成果，主要目标尚未实现"}})
        self.finish_host(t); self.c.tick()
        self.assertEqual(t["status"], "stopped")
        self.assertEqual(t["completion"]["outcome"], "unmet")

    def test_hard_limits_and_manual_pause_still_interrupt_closing_turns(self):
        for hard in (True, False):
            with self.subTest(hard=hard):
                t = self.task(start=True)
                t["budget"]["deadline"] = self.now[0]
                self.c.tick()
                if hard:
                    t["usage"][t["host"]] = {"totalTokens": 1001}
                    self.c.tick()
                    self.assertEqual(t["status"], "budget")
                    self.assertIn("token", t["note"])
                else:
                    self.c.do_pause(t["id"])
                    self.assertEqual(t["status"], "paused")
                self.assertIn(t["host"], self.hub.interrupted)

    def test_expiry_during_a_tool_call_blocks_dispatch_without_tick(self):
        t = self.task(start=True)
        t["budget"]["deadline"] = self.now[0]
        with self.assertRaisesRegex(ValueError, "不再新增"):
            self.c.dispatch(t, "新工作")
        self.assertEqual(t["status"], "closing")
        self.assertEqual(t["workers"], {})

    def test_controller_pause_during_closing_does_not_interrupt_workers(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick(); t["budget"]["deadline"] = self.now[0]; self.c.tick()
        self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {"action": "pause", "summary": "保存进度"}})
        self.assertEqual(t["status"], "closing")
        self.assertEqual(self.hub.interrupted, [])

    def test_uncertain_closing_notice_is_not_retried_or_a_new_turn(self):
        t = self.task(start=True)
        t["budget"]["deadline"] = self.now[0]
        def fail(*args):
            self.hub.steered.append(args)
            raise TimeoutError("lost reply")
        self.hub.steer_only = fail
        self.c.tick(); self.c.tick()
        self.assertEqual(len(self.hub.steered), 1)
        self.assertEqual(len(self.hub.sent), 1)
        self.assertEqual(self.hub.interrupted, [])

    def test_money_limit_takes_precedence_over_simultaneous_deadline(self):
        t = self.task(start=True)
        t["budget"] = budget_value({"deadline": self.now[0], "moneyLimit": 1,
                                   "rates": {"input": 1, "cached": 1, "output": 1}})
        t["usage"][t["host"]] = {"inputTokens": 1000000}
        self.c.tick()
        self.assertEqual(t["status"], "budget")
        self.assertIn("金额", t["note"])
        self.assertIn(t["host"], self.hub.interrupted)

    def test_launch_rechecks_deadline_at_the_send_boundary(self):
        t = self.active(); tid, w = self.worker(t)
        t["budget"]["deadline"] = self.now[0]
        self.c.launch(t, tid, w)
        self.assertEqual(w["state"], "queued")
        self.assertEqual(self.hub.sent, [])

    def test_closing_waits_for_all_workers_and_preserves_queued_work(self):
        t = self.active()
        a, wa = self.worker(t, access="read"); b, wb = self.worker(t, access="read")
        c, wc = self.worker(t, access="read")
        self.c.tick(); self.c.tick()
        self.assertEqual((wa["state"], wb["state"], wc["state"]), ("running", "running", "queued"))
        t["budget"]["deadline"] = self.now[0]; self.c.tick()
        self.finish_worker(t, a, wa); self.c.tick()
        self.assertFalse(t["hostBusy"])
        self.assertEqual(wc["state"], "queued")
        self.finish_worker(t, b, wb); self.c.tick()
        self.assertTrue(t["hostBusy"])
        self.assertEqual(len(self.hub.sent), 3)
        self.finish_host(t); self.c.tick()
        self.assertEqual(t["status"], "budget")
        self.assertEqual(wc["state"], "queued")

    def test_default_deadline_survives_pause_restart_handoff_and_resume(self):
        result = self.c.do_create(str(self.root), "默认预算", "完成目标")
        t = self.c.tasks[result["taskId"]]
        self.confirm(t, start=True)
        deadline = t["budget"]["deadline"]
        self.c.do_pause(t["id"])
        t["hostBusy"] = False  # interruption has completed
        self.c.publish()
        self.now[0] += 300
        restored = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        restored.tick()
        restored.do_handoff(t["id"], "原时限继续有效")
        restored.do_resume(t["id"])
        self.assertEqual(restored.tasks[t["id"]]["budget"]["deadline"], deadline)

    def test_explicit_deadline_and_existing_budgets_are_preserved(self):
        result = self.c.do_create(str(self.root), "明确时限", "目标",
                                  {"deadline": 2000, "durationMinutes": 120})
        t = self.c.tasks[result["taskId"]]
        self.confirm(t, start=True)
        self.assertEqual(t["budget"], {"deadline": 2000, "currency": "CNY"})
        self.assertEqual(budget_value({"tokenLimit": 100}), {"tokenLimit": 100, "currency": "CNY"})
        restored = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.assertEqual(restored.tasks[t["id"]]["budget"], t["budget"])

    def test_failed_start_does_not_begin_duration(self):
        result = self.c.do_create(str(self.root), "讨论中", "目标")
        t = self.c.tasks[result["taskId"]]
        t["hostBusy"] = True
        with self.assertRaises(ValueError): self.c.do_resume(t["id"])
        self.assertEqual(t["budget"], {"durationMinutes": 120, "currency": "CNY"})

    def test_writers_coordinate_across_tasks_and_review(self):
        a, b = self.active(), self.active()
        ta, wa = self.worker(a)
        tb, wb = self.worker(b)
        self.c.tick()
        self.assertEqual(wa["state"], "running")
        self.assertEqual(wb["state"], "queued")
        self.finish_worker(a, ta, wa)
        self.c.tick()
        self.assertTrue(a["hostBusy"])
        self.assertEqual(wb["state"], "queued")  # a stable version is available during review

    def test_declared_disjoint_scopes_can_write_together(self):
        a, b = self.active(), self.active()
        _, wa = self.worker(a, write_scope=["src/ui"])
        _, wb = self.worker(b, write_scope=["src/backend"])
        self.c.tick()
        self.assertEqual((wa["state"], wb["state"]), ("running", "running"))
        self.assertTrue(overlap(["src"], ["src/ui"]))
        self.assertTrue(overlap([], ["src"]))
        self.assertFalse(overlap(["src/ui"], ["src/uikit"]))

    def test_worker_completion_delivered_once_without_claiming_goal_complete(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick()
        turn = self.finish_worker(t, tid, w)
        self.c.tick()
        sent = len(self.hub.sent)
        self.c.event("turn/completed", {"threadId": tid, "turn": turn})
        self.c.tick()
        self.assertEqual(len(self.hub.sent), sent)
        self.assertEqual(t["status"], "review")
        self.assertIn("未独立验证", self.hub.sent[-1][1])

    def test_explicit_acceptance_requires_evidence_and_no_outstanding_work(self):
        t = self.active(); tid, w = self.worker(t)
        def finish(**kw):
            return self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {"action": "finish", "outcome": "met", "summary": "已通过", **kw}})
        with self.assertRaises(ValueError): finish(evidence="报告说好了")
        w["state"] = "idle"
        with self.assertRaises(ValueError): finish()
        finish(evidence="亲自读取产物并运行检查，结果符合 target")
        self.assertEqual(t["status"], "completed")

    def test_token_updates_are_cumulative_not_added_twice(self):
        t = self.active()
        update = {"threadId": t["host"], "tokenUsage": {"total": {"totalTokens": 900}}}
        self.c.event("thread/tokenUsage/updated", update)
        self.c.event("thread/tokenUsage/updated", update)
        self.assertEqual(self.c.usage(t)["totalTokens"], 900)
        update["tokenUsage"]["total"]["totalTokens"] = 1001
        t["hostBusy"] = True
        self.c.event("thread/tokenUsage/updated", update)
        self.c.tick()
        self.assertEqual(t["status"], "budget")
        self.assertIn(t["host"], self.hub.interrupted)

    def test_deadline_stops_queued_work(self):
        t = self.active(); _, w = self.worker(t)
        t["budget"]["deadline"] = 999
        self.c.tick()
        self.assertEqual(t["status"], "budget")
        self.assertEqual(w["state"], "queued")
        self.assertEqual(self.hub.sent, [])

    def test_money_estimate_separates_cached_input(self):
        t = self.active()
        t["budget"] = budget_value({"moneyLimit": 10, "rates": {"input": 2, "cached": 0.2, "output": 8}})
        t["usage"][t["host"]] = {"inputTokens": 1000000, "cachedInputTokens": 500000, "outputTokens": 100000}
        self.assertAlmostEqual(self.c.cost(t), 1.9)

    def test_handoff_keeps_workers_budget_and_task_identity(self):
        t = self.active(); tid, w = self.worker(t)
        old, task_id = t["host"], t["id"]
        self.c.do_handoff(task_id, "已有成果见项目文件；灯光尚未验证")
        self.assertNotEqual(t["host"], old)
        self.assertEqual(t["formerHosts"], [old])
        self.assertIn(tid, t["workers"])
        self.assertEqual(t["budget"]["tokenLimit"], 1000)
        self.assertEqual(t["id"], task_id)
        self.assertEqual(self.hub.sessions[t["host"]]["sandbox"], "danger-full-access")
        self.assertEqual(self.hub.sessions[t["host"]]["approval_policy"], "never")
        with self.assertRaises(ValueError):
            self.c.tool_call({"threadId": old, "tool": "ma4_dispatch", "arguments": {"instruction": "过期派工"}})

    def test_handoff_waits_for_current_controller_turn(self):
        t = self.task(start=True)
        old = t["host"]
        self.c.do_handoff(t["id"], "接续说明")
        self.assertEqual(t["host"], old)
        self.c.event("turn/completed", {"threadId": old, "turn": {"id": t["hostTurn"], "status": "completed"}})
        self.assertNotEqual(t["host"], old)

    def test_recovery_matches_sent_marker_instead_of_resending(self):
        t = self.active()
        rid = "persisted-send"
        result = self.hub.send_raw(t["host"], "[MA4 message:" + rid + "]", rid)
        t["outbox"] = {"id": rid, "tid": t["host"], "kind": "host", "deliveries": []}
        self.c.publish()
        resumed = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        resumed.tick()
        rt = resumed.tasks[t["id"]]
        self.assertEqual(rt["outbox"], {})
        self.assertEqual(rt["hostTurn"], result["turnId"])
        self.assertEqual(len(self.hub.sent), 1)

    def test_uncertain_send_is_not_retried_after_restart(self):
        t = self.active()
        t["outbox"] = {"id": "unknown", "tid": t["host"], "kind": "host", "deliveries": []}
        self.c.publish()
        resumed = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        resumed.tick()
        self.assertEqual(resumed.tasks[t["id"]]["status"], "attention")
        self.assertEqual(self.hub.sent, [])

    def test_pause_stops_owned_threads_only(self):
        a, b = self.active(), self.active()
        tid, w = self.worker(a); w["state"] = "running"
        other, ow = self.worker(b); ow["state"] = "running"
        self.c.do_pause(a["id"])
        self.assertEqual(self.hub.interrupted, [tid])
        self.assertEqual(b["status"], "waiting")

    def test_artifact_cleanup_requires_exact_safe_owned_files(self):
        t = self.task(); root = self.c.ensure_scratch(t)
        (root / "scratch.txt").write_text("temporary")
        outside = self.root / "important.txt"; outside.write_text("keep")
        self.symlink((root / "link.txt"), outside)
        for paths in [["../important.txt"], ["link.txt"], [".ma4-owner.json"], ["."]]:
            with self.assertRaises(ValueError): self.c.do_artifacts(t["id"], "clean", paths, "无依赖")
        self.c.do_artifacts(t["id"], "keep", ["scratch.txt"], "尚未解决的问题证据")
        self.assertIn("scratch.txt", t["retained"])
        self.c.do_artifacts(t["id"], "clean", ["scratch.txt"], "问题已解决且证据已保全")
        self.assertFalse((root / "scratch.txt").exists())
        self.assertEqual(outside.read_text(), "keep")

    def test_host_review_scratch_registered_before_start_even_with_remote_workers(self):
        t = self.cross_task(); shared = self.root / "shared"; self.grant(t, shared)
        root = self.c.scratch(t)
        self.c.do_send(t["host"], "先讨论", "discussion")
        self.assertFalse(root.exists())
        self.finish_host(t)
        send = self.hub.send_raw
        def check_registration(*args, **kwargs):
            self.assertEqual(json.loads((root / ".ma4-owner.json").read_text()), {"task": t["id"]})
            return send(*args, **kwargs)
        with patch.object(self.hub, "send_raw", side_effect=check_registration):
            self.c.do_resume(t["id"])
        (root / "review.txt").write_text("host review")
        self.worker(t, cwd=str(shared))
        self.finish_host(t)
        inventory = self.c.do_artifacts(t["id"])
        self.assertEqual([f["path"] for f in inventory["files"]], ["review.txt"])
        self.assertEqual(len(inventory["roots"]), 2)

    def test_unregistered_scratch_not_adopted_and_does_not_block_explanation(self):
        t = self.active(); root = self.c.scratch(t); root.mkdir(parents=True)
        (root / "review.txt").write_text("keep")
        self.c.send_host(t, "继续核对")
        self.assertIn("主项目临时目录不可使用", self.hub.sent[-1][1])
        with self.assertRaisesRegex(ValueError, "不自动认领"):
            self.c.do_artifacts(t["id"])
        self.assertFalse((root / ".ma4-owner.json").exists())
        self.assertEqual((root / "review.txt").read_text(), "keep")

    def test_invalid_owner_markers_are_never_replaced(self):
        t = self.active(); root = self.c.ensure_scratch(t); marker = root / ".ma4-owner.json"
        for raw in ("broken json", "[]", '{"task":"another-task"}'):
            with self.subTest(raw=raw):
                marker.write_text(raw)
                with self.assertRaises(ValueError): self.c.ensure_scratch(t)
                self.assertEqual(marker.read_text(), raw)
        marker.unlink()
        outside = self.root / "owner.json"; outside.write_text(json.dumps({"task": t["id"]}))
        self.symlink(marker, outside)
        with self.assertRaisesRegex(ValueError, "符号链接"): self.c.ensure_scratch(t)
        self.assertTrue(marker.is_symlink())

    def test_finish_preserves_decision_when_scratch_registration_is_missing(self):
        for outcome, status in (("met", "completed"), ("unmet", "stopped")):
            with self.subTest(outcome=outcome):
                t = self.active(); root = self.c.scratch(t); root.mkdir(parents=True)
                (root / "evidence.txt").write_text("keep")
                result = self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
                    "action": "finish", "outcome": outcome, "summary": "实际判断", "evidence": "已检查正式成果"}})
                self.assertEqual(result["status"], status)
                self.assertIn("归属标记", result["cleanupWarning"])
                restored = Controllers(self.hub, self.root / "data").tasks[t["id"]]
                self.assertEqual(restored["status"], status)
                self.assertEqual(restored["completion"]["outcome"], outcome)
                self.assertIn(result["cleanupWarning"], restored["note"])
                self.assertFalse((root / ".ma4-owner.json").exists())
                self.assertEqual((root / "evidence.txt").read_text(), "keep")
        self.assertFalse(self.hub.sent)
        self.assertFalse(self.hub.interrupted)

    def test_finish_reports_cleanup_io_failure_without_returning_failed_acceptance(self):
        t = self.active()
        with patch.object(self.c, "remove_empty_scratch", side_effect=PermissionError("read-only directory")):
            result = self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
                "action": "finish", "outcome": "met", "summary": "达标", "evidence": "已检查正式成果"}})
        self.assertEqual(result["status"], "completed")
        self.assertIn("read-only directory", result["cleanupWarning"])

    def test_finish_reclaims_owned_empty_roots_and_preserves_review_files(self):
        t = self.cross_task(); shared = self.root / "shared"; self.grant(t, shared)
        t["status"] = "running"
        root = self.c.ensure_scratch(t); other = self.c.ensure_scratch(t, str(shared))
        (other / "review.txt").write_text("keep")
        result = self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
            "action": "finish", "outcome": "met", "summary": "达标", "evidence": "已检查正式成果"}})
        self.assertNotIn("cleanupWarning", result)
        self.assertFalse(root.exists())
        self.assertEqual((other / "review.txt").read_text(), "keep")
        self.assertEqual(json.loads((other / ".ma4-owner.json").read_text()), {"task": t["id"]})

    def test_malformed_state_never_silently_overwrites_original(self):
        self.c.path.parent.mkdir(exist_ok=True)
        self.c.path.write_text("broken state")
        c = Controllers(self.hub, self.root / "data")
        self.assertIsNotNone(c.error)
        c.tick()
        self.assertEqual(c.path.read_text(), "broken state")

    def test_goal_change_cancels_queued_old_instructions(self):
        t = self.active(); _, w = self.worker(t)
        self.c.do_update(t["id"], "改名", "用户修改了目标", t["budget"])
        self.assertEqual(w["state"], "queued")
        self.assertNotEqual(t["target"], "用户修改了目标")
        self.confirm(t)
        self.assertEqual(w["state"], "idle")
        self.assertNotIn("instruction", w)
        self.assertEqual(t["revision"], 2)

    def test_controller_pause_stops_workers_without_interrupting_own_tool(self):
        t = self.active(); tid, w = self.worker(t); w["state"] = "running"
        self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {"action": "pause", "summary": "需要用户决定"}})
        self.assertEqual(self.hub.interrupted, [tid])
        self.assertEqual(t["status"], "paused")

    def test_cleanup_preserves_other_task_and_refuses_hardlinks(self):
        a, b = self.task(), self.task()
        ar, br = self.c.ensure_scratch(a), self.c.ensure_scratch(b)
        (br / "evidence").write_text("keep")
        (ar / "hardlink").hardlink_to(br / "evidence")
        with self.assertRaises(ValueError): self.c.do_artifacts(a["id"], "clean", ["hardlink"], "无依赖")
        self.assertTrue((br / "evidence").exists())

    def test_removal_requires_inactive_task_and_clean_scratch(self):
        t = self.active()
        with self.assertRaises(ValueError): self.c.do_remove(t["id"])
        t["status"] = "paused"
        root = self.c.ensure_scratch(t); (root / "important").write_text("unknown")
        with self.assertRaises(ValueError): self.c.do_remove(t["id"])
        self.c.do_artifacts(t["id"], "clean", ["important"], "测试生成文件，已无依赖")
        self.c.do_remove(t["id"])
        self.assertNotIn(t["id"], self.c.tasks)
        self.assertFalse(root.exists())

    def test_runtime_actor_executes_commands_without_blocking_rpc_reader(self):
        self.c.start()
        try:
            result = self.c.invoke("create", cwd=str(self.root), name="线程测试", target="目标", budget={})
            self.assertIn(result["taskId"], self.c.tasks)
            inventory = self.c.invoke("artifacts", task_id=result["taskId"], action="list")
            self.assertEqual(inventory["files"], [])
            self.c.invoke("handoff", task_id=result["taskId"], summary="接任说明")
            t = self.c.tasks[result["taskId"]]
            self.assertEqual(len(t["formerHosts"]), 1)
        finally:
            self.c.close()

    def test_paused_handoff_delivers_summary_when_resumed(self):
        t = self.task()
        self.c.do_handoff(t["id"], "用户已决定保留池塘；灯光需重做")
        self.assertEqual(self.hub.sent, [])
        self.c.do_resume(t["id"])
        self.assertIn("用户已决定保留池塘", self.hub.sent[-1][1])
        self.assertIn("须核实", self.hub.sent[-1][1])
        self.assertNotIn("handoffPending", t)

    def test_nested_project_writes_also_coordinate(self):
        a, b = self.active(), self.active()
        sub = self.root / "nested"; sub.mkdir()
        b["cwd"] = str(sub)
        b["workspaces"] = [{"cwd": str(sub), "write_scope": []}]
        _, wa = self.worker(a)
        _, wb = self.worker(b)
        self.c.tick()
        self.assertEqual((wa["state"], wb["state"]), ("running", "queued"))

    def cross_task(self, name="main"):
        root = self.root / name
        root.mkdir()
        result = self.c.do_create(str(root), name, target="实现并验收", budget={"durationMinutes": 480})
        t = self.c.tasks[result["taskId"]]
        self.confirm(t)
        return t

    def grant(self, t, root, scope=None):
        root.mkdir(exist_ok=True)
        grants = [*task_workspaces(t), {"cwd": str(root), "write_scope": scope or []}]
        self.c.do_confirm(t["id"], t["draftRevision"], t["name"], t["target"], t["budget"], False, grants)
        return grants

    def test_workspace_proposal_old_tool_is_not_authorization(self):
        t = self.cross_task(); extra = self.root / "shared"; extra.mkdir()
        grants = [*task_workspaces(t), {"cwd": str(extra), "write_scope": ["skills/godot-tech"]}]
        self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
            "action": "pause", "summary": DRAFT_PREFIX + "新目标" + WORKSPACES_MARKER + json.dumps(grants)}})
        self.assertEqual(t["draft"]["workspaces"], grants)
        self.assertEqual(t["target"], "实现并验收")
        self.assertEqual(len(task_workspaces(t)), 1)
        revision = t["draftRevision"]
        with self.assertRaisesRegex(ValueError, "明确确认"):
            self.confirm(t)  # Old clients cannot approve undisplayed grants.
        self.c.do_confirm(t["id"], revision, t["name"], "新目标", t["budget"], False, grants)
        self.assertEqual(task_workspaces(t), grants)
        with self.assertRaisesRegex(ValueError, "已更新"):
            self.c.do_confirm(t["id"], revision, t["name"], "新目标", t["budget"], False, grants)

    def test_invalid_workspace_grants_do_not_change_draft_or_formal_state(self):
        t = self.cross_task(); before = copy.deepcopy(t)
        extra = self.root / "shared"; extra.mkdir()
        main = {"cwd": t["cwd"], "write_scope": []}
        for grants in [[], [main, main], [{"cwd": str(extra), "write_scope": []}],
                       [dict(main, write_scope=None)], [dict(main, write_scope=["/absolute"])],
                       [dict(main, cwd="relative")], [dict(main, cwd=str(extra / "missing"))]]:
            with self.assertRaises(ValueError):
                self.c.stage_draft(t, "新草案", "user", workspaces=grants)
            self.assertEqual(t, before)
        self.assertTrue(overlap(["/"], [str(extra)]))

    def test_cross_project_worker_real_cwd_scope_budget_and_old_schema(self):
        t = self.cross_task(); extra = self.root / "shared"
        self.grant(t, extra, ["skills/godot-tech"])
        self.c.do_resume(t["id"]); self.finish_host(t); t["status"] = "running"
        deadline = t["budget"]["deadline"]
        result = self.c.tool_call({"threadId": t["host"], "tool": "ma4_dispatch", "arguments": {
            "instruction": f"[MA4 工作目录] {extra}\n更新 Skill"}})
        tid = result["session_id"]; w = t["workers"][tid]
        self.assertEqual(self.hub.sessions[tid]["cwd"], str(extra))
        self.assertEqual(w["scope"], ["skills/godot-tech"])
        self.assertEqual(w["instruction"], "更新 Skill")
        self.assertEqual(Path(result["scratch"]), extra / ".agent-tmp" / ("ma4-" + t["id"]))
        self.c.tick()
        self.assertIn(f"实际工作目录：{extra}", self.hub.sent[-1][1])
        self.token_event(t, w["turnId"], 100, tid=tid)
        self.assertEqual(self.c.usage(t)["totalTokens"], 100)
        self.finish_worker(t, tid, w)
        self.assertEqual(t["pending"][0]["cwd"], str(extra))
        self.assertEqual(t["budget"]["deadline"], deadline)
        self.c.dispatch(t, "继续核对", session_id=tid)
        self.assertEqual(w["cwd"], str(extra))
        w["state"] = "idle"
        with self.assertRaisesRegex(ValueError, "不能更换"):
            self.c.dispatch(t, "换项目", session_id=tid, cwd=t["cwd"])

    def test_dispatch_rejects_ungranted_root_and_scope_widening_without_creating_threads(self):
        t = self.cross_task(); extra = self.root / "shared"
        self.grant(t, extra, ["skills/godot-tech"]); t["status"] = "running"
        n = len(self.hub.sessions)
        for kwargs in [dict(cwd=str(self.root)), dict(cwd=str(extra), write_scope=[]),
                       dict(cwd=str(extra), write_scope=["skills/godot-tech2"]),
                       dict(cwd=str(extra), write_scope=["../secret"])]:
            with self.assertRaises(ValueError): self.worker(t, **kwargs)
        self.assertEqual(len(self.hub.sessions), n)
        self.assertFalse((extra / ".agent-tmp").exists())
        tid, w = self.worker(t, cwd=str(extra), write_scope=["skills/godot-tech/SKILL.md"])
        self.assertEqual(w["scope"], ["skills/godot-tech/SKILL.md"])

    def test_cross_task_actual_paths_serialize_and_disjoint_scopes_run(self):
        a, b = self.cross_task("project-a"), self.cross_task("project-b")
        shared = self.root / "shared"
        for t in [a, b]: self.grant(t, shared); t["status"] = "running"
        _, wa = self.worker(a, cwd=str(shared), write_scope=["skills/one"])
        _, wb = self.worker(b, cwd=str(shared), write_scope=["skills/one/SKILL.md"])
        self.c.tick()
        self.assertEqual((wa["state"], wb["state"]), ("running", "queued"))
        wb["scope"] = ["skills/two"]
        self.c.tick()
        self.assertEqual(wb["state"], "running")

    def test_shared_writes_warn_receiving_host_without_blocking_reports(self):
        a, b = self.cross_task("project-a"), self.cross_task("project-b")
        shared = self.root / "shared"
        for t in [a, b]: self.grant(t, shared); t["status"] = "running"
        tid, w = self.worker(a, cwd=str(shared)); b["hostBusy"] = True
        self.assertFalse(self.c.can_launch(a, w))
        b["hostBusy"] = False; self.c.tick()
        b["pending"] = [{"id": "pending", "report": "检查共享素材"}]
        before = len(self.hub.sent)
        self.c.tick()
        self.assertEqual(len(self.hub.sent), before + 1)
        self.assertEqual(self.hub.sent[-1][0], b["host"])
        self.assertEqual(w["state"], "running")
        self.assertIn(str(shared), self.hub.sent[-1][1])
        self.assertIn("暂缓验收", self.hub.sent[-1][1])
        self.assertFalse(self.hub.interrupted)

    def test_assessment_arrives_during_archive_and_later_report_waits_for_busy_host(self):
        t = self.cross_task(); archive = self.root / "archive"
        self.grant(t, archive); t["status"] = "running"
        assessment_id, assessment = self.worker(t, name="制作经验评估")
        archive_id, writer = self.worker(t, name="归档制作", cwd=str(archive))
        self.c.tick(); self.c.tick()
        self.assertEqual((assessment["state"], writer["state"]), ("running", "running"))
        turn = self.finish_worker(t, assessment_id, assessment, "评估已完成，建议增补 Skill")
        self.assertEqual(self.c.report_delivery(t)["state"], "ready")
        self.c.tick()
        self.assertEqual(writer["state"], "running")
        self.assertEqual(self.hub.sent[-1][0], t["host"])
        self.assertIn("评估已完成", self.hub.sent[-1][1])
        self.assertIn(str(archive), self.hub.sent[-1][1])
        self.assertEqual(t["pending"], [])
        # Completion notifications may be duplicated; they must not redeliver.
        self.c.complete_worker(t, assessment_id, turn)
        self.assertEqual(t["pending"], [])
        with self.assertRaisesRegex(ValueError, "还有执行工作"):
            self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
                "action": "finish", "outcome": "met", "summary": "不能提前结束", "evidence": "评估报告"}})
        self.finish_host(t)
        self.assertEqual(t["status"], "waiting")
        self.c.do_send(t["host"], "继续讨论评估建议", "followup-discussion")
        self.finish_worker(t, archive_id, writer, "归档制作完成")
        delivery = self.c.report_delivery(t)
        self.assertEqual((delivery["count"], delivery["state"]), (1, "host_busy"))
        self.assertEqual(delivery["reports"][0]["name"], "归档制作")
        saved = json.loads(self.c.path.read_text())["tasks"][t["id"]]["pending"]
        self.assertEqual(saved[0]["threadId"], archive_id)
        before = len(self.hub.sent)
        self.c.tick(); self.c.tick()
        self.assertEqual(len(self.hub.sent), before)
        self.assertFalse(self.hub.steered)  # A report never steers a busy host.
        self.finish_host(t); self.c.tick()
        self.assertEqual(len(self.hub.sent), before + 1)
        body = self.hub.sent[-1][1].split("[MA4 content]\n", 1)[1]
        self.assertIn("归档制作完成", body)
        self.assertNotIn("评估已完成", body)
        self.assertEqual(self.c.report_delivery(t)["count"], 0)

    def test_busy_host_reports_merge_after_restart_without_automatic_resume(self):
        t = self.active()
        one, w1 = self.worker(t, name="评估", write_scope=["art"])
        two, w2 = self.worker(t, name="归档", write_scope=["docs"])
        self.c.tick(); self.c.tick()
        self.c.do_send(t["host"], "补充讨论", "user-discussion")
        self.finish_worker(t, one, w1, "评估回复")
        self.finish_worker(t, two, w2, "归档回复")
        before = len(self.hub.sent)
        self.c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.c.tick(); t = self.c.tasks[t["id"]]
        self.assertEqual(len(self.hub.sent), before)
        self.assertEqual(self.c.report_delivery(t)["count"], 2)
        self.finish_host(t); self.c.tick()
        self.assertEqual(len(self.hub.sent), before + 1)
        self.assertIn("评估回复", self.hub.sent[-1][1])
        self.assertIn("归档回复", self.hub.sent[-1][1])
        self.assertEqual(t["pending"], [])

    def test_paused_and_hard_budget_reports_are_retained(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick(); self.c.do_pause(t["id"])
        self.finish_worker(t, tid, w)
        before = len(self.hub.sent)
        self.c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.c.tick(); t = self.c.tasks[t["id"]]
        self.assertEqual(len(self.hub.sent), before)
        self.assertEqual(self.c.report_delivery(t)["state"], "retained")
        t["status"] = "running"
        t["usage"][t["host"]] = {"totalTokens": 1000}
        self.assertEqual(self.c.report_delivery(t)["state"], "budget")
        self.c.tick()
        self.assertEqual(t["status"], "budget")
        self.assertEqual(len(t["pending"]), 1)
        self.assertEqual(len(self.hub.sent), before)

    def test_report_send_lost_reply_is_reconciled_without_resending(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick(); self.finish_worker(t, tid, w)
        original = self.hub.send_raw
        def lost_reply(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError("accepted but response lost")
        self.hub.send_raw = lost_reply
        with self.assertRaises(TimeoutError): self.c.tick()
        self.assertEqual(len(t["pending"]), 1)
        self.assertEqual(self.c.report_delivery(t)["state"], "sending")
        sent = len(self.hub.sent)
        self.hub.send_raw = original
        self.c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.c.tick(); t = self.c.tasks[t["id"]]
        self.assertEqual(len(self.hub.sent), sent)
        self.assertEqual(t["pending"], [])
        self.assertTrue(t["hostBusy"])

    def test_closing_waits_own_workers_but_not_other_task_writer(self):
        a, b = self.cross_task("a"), self.cross_task("b")
        shared = self.root / "shared"
        for t in [a, b]: self.grant(t, shared); t["status"] = "running"
        own, wa = self.worker(a)
        other, wb = self.worker(b, cwd=str(shared))
        self.c.tick()
        a["budget"]["deadline"] = self.now[0]
        self.c.tick()
        self.assertEqual(a["status"], "closing")
        self.finish_worker(a, own, wa)
        self.c.tick()
        self.assertEqual(wb["state"], "running")
        self.assertTrue(a["closing"]["reviewStarted"])
        self.assertIn("到期收尾汇总", self.hub.sent[-1][1])
        self.assertIn(str(shared), self.hub.sent[-1][1])
        self.assertIn("暂缓验收", self.hub.sent[-1][1])
        self.finish_host(a); self.c.tick()
        self.assertEqual(a["status"], "budget")
        self.assertEqual(wb["state"], "running")

    def test_report_delivery_state_explains_connection_and_handoff_waits(self):
        t = self.active()
        t["pending"] = [{"id": "report", "threadId": "old", "turnId": "turn"}]
        self.hub.daemon["connected"] = False
        self.c.publish()
        self.assertEqual(self.c.snapshot()["tasks"][0]["reportDelivery"]["state"], "disconnected")
        self.hub.daemon["connected"] = True; self.c.recovering = True
        self.assertEqual(self.c.report_delivery(t)["state"], "recovering")
        self.c.recovering = False; t["handoff"] = "交接中"
        self.assertEqual(self.c.report_delivery(t)["state"], "handoff")
        self.assertNotIn("reportDelivery", json.loads(self.c.path.read_text())["tasks"][t["id"]])

    def test_grant_change_cancels_queued_work_and_does_not_restart_budget(self):
        t = self.cross_task(); extra = self.root / "shared"
        self.grant(t, extra); self.c.do_resume(t["id"]); self.finish_host(t); t["status"] = "running"
        _, w = self.worker(t, cwd=str(extra))
        deadline = t["budget"]["deadline"]
        self.c.stage_draft(t, t["target"], "user", workspaces=[task_workspaces(t)[0]])
        self.c.do_confirm(t["id"], t["draftRevision"], t["name"], t["target"], t["budget"], False, t["draft"]["workspaces"])
        self.assertEqual(w["state"], "idle")
        self.assertNotIn("instruction", w)
        self.assertEqual(t["budget"]["deadline"], deadline)
        self.c.do_resume(t["id"])
        self.assertEqual(t["budget"]["deadline"], deadline)

    def test_symlinks_checked_again_at_launch_and_grant_confirmation(self):
        t = self.cross_task(); shared = self.root / "shared"
        self.grant(t, shared, ["skills"]); t["status"] = "running"
        _, w = self.worker(t, cwd=str(shared))
        self.symlink((shared / "skills"), self.root)
        self.c.tick()
        self.assertEqual(w["state"], "queued")
        self.assertEqual(t["status"], "attention")
        self.assertFalse(self.hub.sent)
        with self.assertRaises(ValueError): workspace_value(task_workspaces(t), t["cwd"])
        alias = self.root / "alias"; self.symlink(alias, shared)
        with self.assertRaises(ValueError): workspace_value([{"cwd": str(alias), "write_scope": []}], t["cwd"])

    def test_legacy_single_project_and_multiroot_state_survive_restart_handoff(self):
        t = self.cross_task(); t.pop("workspaces")
        t["status"] = "running"
        tid, w = self.worker(t); w.pop("cwd"); w["state"] = "idle"; t["status"] = "paused"
        self.c.publish()
        c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.assertEqual(task_workspaces(c.tasks[t["id"]]), [{"cwd": t["cwd"], "write_scope": []}])
        shared = self.root / "shared"; grants = self.grant(t, shared, ["skills"])
        self.c.do_handoff(t["id"], "跨项目维护，沿用预算")
        c = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        self.assertEqual(task_workspaces(c.tasks[t["id"]]), grants)
        self.assertEqual(c.tasks[t["id"]]["budget"], t["budget"])
        self.assertEqual(c.worker_cwd(c.tasks[t["id"]], w), t["cwd"])
        self.assertFalse(self.hub.sent)

    def test_multiroot_artifacts_remain_manageable_after_revocation(self):
        t = self.cross_task(); shared = self.root / "shared"; self.grant(t, shared)
        t["status"] = "running"; _, w = self.worker(t, cwd=str(shared)); w["state"] = "idle"; t["status"] = "paused"
        ar = self.c.ensure_scratch(t); br = self.c.scratch(t, str(shared))
        (ar / "one").write_text("one"); (br / "two").write_text("two")
        t["workspaces"] = [task_workspaces(t)[0]]
        inventory = self.c.do_artifacts(t["id"])
        self.assertEqual({f["path"] for f in inventory["files"]}, {"one", str(br / "two")})
        self.c.do_artifacts(t["id"], "keep", [str(br / "two")], "待复查")
        self.assertIn(str(br / "two"), t["retained"])
        with self.assertRaises(ValueError): self.c.do_remove(t["id"])
        for path in [str(shared / "formal"), str(br / ".ma4-owner.json"), str(br), "../one"]:
            with self.assertRaises(ValueError): self.c.do_artifacts(t["id"], "clean", [path], "不能删")
        self.c.do_artifacts(t["id"], "clean", ["one", str(br / "two")], "无依赖")
        self.c.do_remove(t["id"])
        self.assertFalse(ar.exists()); self.assertFalse(br.exists())

    def test_shared_artifact_links_and_busy_workers_are_not_cleaned(self):
        t = self.cross_task(); shared = self.root / "shared"; self.grant(t, shared)
        t["status"] = "running"; _, w = self.worker(t, cwd=str(shared))
        root = self.c.scratch(t, str(shared)); original = shared / "formal"; original.write_text("keep")
        (root / "hard").hardlink_to(original); self.symlink((root / "link"), original)
        for path in [str(root / "hard"), str(root / "link")]:
            with self.assertRaises(ValueError): self.c.do_artifacts(t["id"], "clean", [path], "不能删")
        (root / "temp").write_text("temp"); w["state"] = "running"
        with self.assertRaisesRegex(ValueError, "仍在运行"):
            self.c.do_artifacts(t["id"], "clean", [str(root / "temp")], "等返回")
        self.assertEqual(original.read_text(), "keep")

    def test_external_model_change_invalidates_money_budget(self):
        t = self.active()
        t["model"] = "model-a"
        t["budget"] = budget_value({"moneyLimit": 10, "rates": {"input": 1, "cached": 0.1, "output": 2}})
        self.c.event("thread/settings/updated", {"threadId": t["host"], "threadSettings": {"model": "model-b"}})
        self.assertTrue(t["costUncertain"])
        self.assertEqual(t["status"], "paused")
        with self.assertRaises(ValueError): self.c.do_resume(t["id"])

    def test_duplicate_create_request_does_not_create_extra_controller(self):
        kwargs = dict(cwd=str(self.root), name="幂等创建", target="目标", request_id="same-user-click")
        first = self.c.do_create(**kwargs)
        second = self.c.do_create(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(len(self.hub.sessions), 1)

    def token_event(self, t, turn, total, cached=0, tid=None):
        self.c.event("thread/tokenUsage/updated", {"threadId": tid or t["host"], "turnId": turn,
                    "tokenUsage": {"total": dict(zip(TOKEN_KEYS, (total, total - 10, cached, 10)))}})

    def test_turn_usage_late_duplicate_notifications_and_restart(self):
        t = self.task(start=True); tid = t["host"]; first = t["hostTurn"]
        self.token_event(t, first, 100, 40)
        self.c.event("turn/completed", {"threadId": tid, "turn": {"id": first, "status": "completed", "durationMs": 1000}})
        self.c.do_resume(t["id"]); second = t["hostTurn"]
        self.token_event(t, second, 240, 100)
        # A delayed previous-turn notification corrects both splits, not the total.
        self.token_event(t, first, 120, 50)
        self.token_event(t, first, 120, 50)
        restored = Controllers(self.hub, self.root / "data", clock=lambda: self.now[0])
        stats = restored.snapshot()["tasks"][0]["statistics"]
        self.assertEqual([r["usage"]["totalTokens"] for r in stats["sessions"][0]["turns"]], [120, 120])
        self.assertEqual([r["usage"]["cachedInputTokens"] for r in stats["sessions"][0]["turns"]], [50, 50])
        self.assertEqual(stats["roles"][0]["usage"]["totalTokens"], 240)
        self.assertEqual(len(self.hub.sent), 2)

    def test_finish_records_settling_tokens_and_time_without_another_turn(self):
        t = self.task(start=True); turn = t["hostTurn"]
        self.token_event(t, turn, 100, 40)
        self.c.tool_call({"threadId": t["host"], "tool": "ma4_control", "arguments": {
            "action": "finish", "outcome": "unmet", "summary": "视觉目标未达标", "evidence": "亲自检查整体预览，比例不符"}})
        self.assertTrue(t["completion"]["settling"])
        self.c.event("turn/completed", {"threadId": t["host"], "turn": {"id": turn, "status": "completed",
            "startedAt": 1000, "completedAt": 1005, "durationMs": 5000}})
        self.token_event(t, turn, 200, 80)
        self.c.tick()
        restored = json.loads(self.c.path.read_text())["tasks"][t["id"]]["completion"]
        self.assertEqual(restored["usageTotal"]["totalTokens"], 200)
        self.assertEqual(restored["turnDurationMs"], 5000)
        self.assertEqual(restored["elapsedMs"], 5000)
        self.assertEqual(restored["outcome"], "unmet")
        self.assertFalse(restored["settling"])
        self.assertEqual(len(self.hub.sent), 1)

    def test_legacy_usage_and_recovery_gaps_are_not_invented_turn_counts(self):
        t = self.task(start=True); tid = t["host"]; turn = t["hostTurn"]
        self.token_event(t, turn, 100)
        self.hub.usage_snapshot = lambda _: {"totalTokens": 250}
        self.c.recovering = True
        self.c.reconcile()
        stats = self.c.statistics(t)["sessions"][0]
        self.assertEqual(stats["usage"]["totalTokens"], 250)
        self.assertEqual(stats["unattributedTokens"], 150)
        t.pop("metrics")
        self.c.recovering = True
        self.c.reconcile()
        self.token_event(t, turn, 300)
        stats = self.c.statistics(t)["sessions"][0]
        self.assertIsNone(stats["turns"][0]["usage"])
        self.assertEqual(stats["unattributedTokens"], 300)

    def test_legacy_timing_is_unknown_and_resume_is_not_the_original_start(self):
        t = self.task()
        del t["firstStartedAt"]
        self.assertIsNone(self.c.statistics(t)["sessions"][0]["durationMs"])
        self.c.do_resume(t["id"])
        self.assertNotIn("firstStartedAt", t)

    def test_roles_keep_former_hosts_and_worker_usage_separate(self):
        t = self.task(start=True); old = t["host"]; turn = t["hostTurn"]
        self.token_event(t, turn, 100, 30)
        self.c.event("turn/completed", {"threadId": old, "turn": {"id": turn, "status": "completed"}})
        t["status"] = "paused"
        self.c.do_handoff(t["id"], "成果路径已核实，继续原目标")
        self.c.do_resume(t["id"])
        self.token_event(t, t["hostTurn"], 50, 20)
        tid, w = self.worker(t)
        self.c.launch(t, tid, w)
        self.token_event(t, w["turnId"], 70, 10, tid)
        stats = self.c.statistics(t)
        self.assertEqual([r["usage"]["totalTokens"] for r in stats["roles"]], [150, 70])
        self.assertEqual(len(stats["sessions"]), 3)

    def test_recovered_usage_gap_is_not_charged_to_the_next_turn(self):
        t = self.task(start=True); tid = t["host"]; first = t["hostTurn"]
        self.token_event(t, first, 100)
        self.c.event("turn/completed", {"threadId": tid, "turn": {"id": first, "status": "completed"}})
        self.c.event("thread/tokenUsage/updated", {"threadId": tid, "tokenUsage": {"total": {"totalTokens": 250}}})
        self.c.do_resume(t["id"])
        self.token_event(t, t["hostTurn"], 400)
        session = self.c.statistics(t)["sessions"][0]
        self.assertEqual([r["usage"]["totalTokens"] for r in session["turns"]], [100, 150])
        self.assertEqual(session["unattributedTokens"], 150)

    def test_long_report_keeps_artifact_failure_and_source_without_full_context(self):
        t = self.active(); tid, w = self.worker(t)
        self.c.tick()
        turn = {"id": w["turnId"], "status": "failed", "error": {"message": "上游 503"}, "items": [
            {"type": "agentMessage", "text": "成果：result.png\n" + "解释" * 10000 + "\n未完成：整体比例不符"}]}
        self.c.event("turn/completed", {"threadId": tid, "turn": turn})
        result = t["pending"][0]
        self.assertTrue(result["reportTruncated"])
        self.assertLess(len(result["report"]), 3100)
        self.assertIn("result.png", result["report"])
        self.assertIn("整体比例不符", result["report"])
        self.assertEqual(result["error"], "上游 503")
        self.assertEqual(result["threadId"], tid)

    def test_write_scope_is_always_project_relative(self):
        for value in ["/tmp/x", "E:/PG/x", "C:\\x", "../x", "src/../x"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                scopes([value])
        self.assertEqual(scopes(["src/ui", "README.md"]), ["src/ui", "README.md"])
        self.assertEqual(scopes(["src/file:name"]), ["src/file:name"])


if __name__ == "__main__":
    unittest.main()
