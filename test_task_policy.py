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
