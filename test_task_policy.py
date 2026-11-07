import copy
from dataclasses import FrozenInstanceError
from types import MappingProxyType
import unittest

import task_policy as policy


def task():
    return {"host": "host", "hostBusy": False, "status": "paused", "target": "已确认目标", "goalConfirmed": True,
            "budget": {"deadline": 2000}, "usage": {}, "workers": {}, "pending": []}


def frozen(value):
    if isinstance(value, dict):
        return MappingProxyType({key: frozen(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(frozen(item) for item in value)
    return value


class TaskPolicyTest(unittest.TestCase):
    def test_unknown_worker_precedes_idle_draft_and_failure_diagnoses(self):
        runtime = policy.RuntimeState(1000, True)
        cases = [{"status": state} for state in ("paused", "attention", "draft", "running", "waiting", "review")]
        cases += [{"draft": {"target": "新草案"}}, {"goalConfirmed": False},
                  {"handoffPending": "交接说明"},
                  {"metrics": {"host": {"turns": {"last": {"startedAt": 900, "status": "failed"}}}}}]
        for changes in cases:
            with self.subTest(changes=changes):
                t = task()
                t.update(changes, workers={"w": {"state": "future_state"}, "idle": {"state": "idle"}})
                before = copy.deepcopy(t)
                d = policy.diagnosis(frozen(t), runtime)
                self.assertEqual(d["code"], "unknown_work")
                self.assertEqual(d["work"]["unknown"], 1)
                self.assertEqual(d["work"]["idle"], 1)
                self.assertIsNotNone(d["confirmBlocker"])
                self.assertIn("核对", d["confirmBlocker"])
                self.assertNotIn("未记录在途", d["reason"])
                self.assertEqual(t, before)

    def test_unknown_worker_preserves_higher_priority_information(self):
        runtime = policy.RuntimeState(1000, True)
        cases = [
            ({}, policy.RuntimeState(1000, True, error="控制错误"), "error"),
            ({}, policy.RuntimeState(1000, False), "disconnected"),
            ({}, policy.RuntimeState(1000, True, recovering=True), "recovering"),
            ({"outbox": {"id": "uncertain"}}, runtime, "sending"),
            ({"host": None}, runtime, "missing_host"),
            ({"status": "closing"}, runtime, "closing"),
            ({"handoff": "等待交接"}, runtime, "handoff"),
            ({"hostBusy": True}, runtime, "pausing"),
            ({"budget": {"deadline": 999}}, runtime, "budget"),
            ({"budget": {"tokenLimit": 1}, "usage": {"host": {"totalTokens": 1}}}, runtime, "budget"),
            ({"budget": {"moneyLimit": 1, "rates": {"input": 1, "cached": 0, "output": 1}},
              "usage": {"host": {"inputTokens": 1000000}}}, runtime, "budget"),
            ({"costUncertain": True}, runtime, "cost_uncertain"),
        ]
        for changes, state, code in cases:
            with self.subTest(code=code, changes=changes):
                t = task()
                t.update(changes, workers={"w": {"state": "unknown"}})
                d = policy.diagnosis(frozen(t), state)
                self.assertEqual(d["code"], code)
                self.assertTrue(any("执行者" in fact and "待核对" in fact for fact in d["facts"]))
                self.assertIsNotNone(d["confirmBlocker"])
                # Unknown state is not a new handoff policy.
                self.assertEqual(d["handoffBlocker"], policy.handoff_blocker(dict(t, workers={}), state))

    def test_terminal_unknown_worker_never_claims_no_inflight_turns(self):
        for status in ("completed", "stopped"):
            for busy in (False, True):
                with self.subTest(status=status, busy=busy):
                    t = task()
                    t.update(status=status, hostBusy=busy, budget={"deadline": 999},
                             workers={"w": {"state": "unknown"}})
                    d = policy.diagnosis(frozen(t), policy.RuntimeState(1000, True))
                    self.assertEqual(d["code"], status)
                    self.assertNotIn("未记录在途", d["reason"])
                    self.assertTrue(any("待核对" in fact for fact in d["facts"]))
                    self.assertFalse(d["canPause"])
                    self.assertIsNotNone(d["confirmBlocker"])

    def test_unknown_worker_blocks_confirmation_without_guessing_state(self):
        for status in ("paused", "draft", "attention", "completed", "stopped", "waiting"):
            for worker_state in ("unknown", "future_state", "", None):
                with self.subTest(status=status, worker_state=worker_state):
                    t = task()
                    t.update(status=status, workers={"w": {"state": worker_state}})
                    before = copy.deepcopy(t)
                    blocker = policy.confirm_blocker(frozen(t), policy.RuntimeState(1000, True))
                    self.assertIsNotNone(blocker)
                    self.assertIn("核对", blocker)
                    self.assertEqual(t, before)

    def test_known_worker_states_keep_existing_diagnosis_and_confirmation(self):
        for worker_state, code, blocked in (("idle", "paused", False), ("queued", "paused", False),
                                            ("running", "pausing", True), ("sending", "pausing", True)):
            with self.subTest(worker_state=worker_state):
                t = task()
                t["workers"] = {"w": {"state": worker_state}}
                d = policy.diagnosis(frozen(t), policy.RuntimeState(1000, True))
                self.assertEqual(d["code"], code)
                self.assertEqual(d["work"]["unknown"], 0)
                self.assertEqual(bool(d["confirmBlocker"]), blocked)
                self.assertEqual(d["canPause"], blocked)
                self.assertEqual(d["facts"], [])
                if blocked:
                    t["workers"]["unknown"] = {"state": "unknown"}
                    mixed = policy.diagnosis(frozen(t), policy.RuntimeState(1000, True))
                    self.assertEqual(mixed["code"], "pausing")
                    self.assertEqual(mixed["confirmBlocker"], d["confirmBlocker"])
                    self.assertTrue(mixed["canPause"])

    def test_expiry_depends_on_supplied_time_without_modifying_budget(self):
        t = task()
        before = copy.deepcopy(t)
        self.assertEqual(policy.diagnosis(t, policy.RuntimeState(1999, True))["code"], "paused")
        self.assertEqual(policy.diagnosis(t, policy.RuntimeState(2000, True))["code"], "budget")
        self.assertEqual(t, before)
        self.assertIsNone(policy.confirm_blocker(t, policy.RuntimeState(2000, True)))

    def test_immutable_task_input_and_runtime_work_without_a_hub_or_filesystem(self):
        t = task()
        t.update(status="waiting", workers={"w": {"state": "running", "name": "制作"}},
                 pending=[{"id": "w:one", "threadId": "w", "turnId": "one"}])
        snapshot = frozen(t)
        runtime = policy.RuntimeState(1000, True)
        result = policy.diagnosis(snapshot, runtime)
        self.assertEqual(result["code"], "workers_busy")
        self.assertEqual(policy.report_delivery(snapshot, runtime)["state"], "ready")
        self.assertEqual(policy.usage(snapshot)["totalTokens"], 0)
        with self.assertRaises(FrozenInstanceError): runtime.now = 2000
        result["work"]["running"] = 0
        self.assertEqual(policy.diagnosis(snapshot, runtime)["work"]["running"], 1)

    def test_unconfirmed_send_and_recovery_keep_reports_and_disable_actions(self):
        t = task()
        t.update(status="waiting", pending=[{"id": "report"}], outbox={"id": "uncertain"})
        runtime = policy.RuntimeState(1000, True)
        self.assertEqual(policy.diagnosis(t, runtime)["code"], "sending")
        self.assertEqual(policy.report_delivery(t, runtime)["state"], "sending")
        self.assertIsNotNone(policy.confirm_blocker(t, runtime))
        self.assertIsNotNone(policy.handoff_blocker(t, runtime))
        self.assertEqual(policy.diagnosis(t, policy.RuntimeState(1000, True, recovering=True))["code"], "recovering")
        self.assertEqual(len(t["pending"]), 1)

    def test_hard_budget_precedes_expiry_and_cached_tokens_are_not_double_charged(self):
        t = task()
        t["usage"] = {"host": {"totalTokens": 1000, "inputTokens": 900, "cachedInputTokens": 600, "outputTokens": 100}}
        t["budget"] = {"deadline": 999, "moneyLimit": .001, "rates": {"input": 2, "cached": 1, "output": 4}}
        self.assertAlmostEqual(policy.cost(t), .0016)
        self.assertEqual(policy.exhausted(t, 1000), "已达到估算金额上限")
        t["budget"]["tokenLimit"] = 1000
        self.assertEqual(policy.exhausted(t, 1000), "已达到 token 上限")
