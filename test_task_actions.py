"""Cheap client safety/judgment tests. No native backend, browser or model."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.task_actions import TaskActions, ROOT, validate_identity, validate_plan, timeout_value


def fake_fixture():
    root = (ROOT / ".agent-tmp" / "unit-task-actions").resolve()
    identity = {"instance": "a" * 32, "ownerPid": os.getpid(), "backendPid": 123,
                "endpoint": "ws://127.0.0.1:4322", "codexHome": str(root / "codex-home"),
                "dataDir": str(root / "state")}
    state = {"side": {"runtime": {"verification": copy.deepcopy(identity), "defaultCwd": str(root)}},
             "daemon": {"connected": True, "version": "test-1"}, "threads": [],
             "controllers": {"tasks": [], "error": None}}
    f = {"root": root, "home": root / "codex-home", "endpoint": identity["endpoint"],
         "url": "http://127.0.0.1:4321", "api": Mock(side_effect=lambda *args: copy.deepcopy(state)),
         "web": SimpleNamespace(server_port=4321, runtime={"verification": identity}),
         "hub": SimpleNamespace(data_dir=root / "state", daemon=state["daemon"],
                                socket_path=identity["endpoint"], codex_home=str(root / "codex-home")),
         "process": SimpleNamespace(pid=123, poll=lambda: None), "model": SimpleNamespace(script=Mock())}
    return f, state


def owned_task(a, state):
    task = {"id": "task", "cwd": a.identity["cwd"], "host": "host-id", "formerHosts": [],
            "workers": {}, "budget": {"deadline": 12345}, "target": "test goal", "revision": 1,
            "status": "draft", "goalConfirmed": False, "hostBusy": False, "pending": []}
    state["controllers"]["tasks"].append(task)
    a.owned["main"] = {"id": "task", "host": "host-id", "former": [], "workers": {}}
    return task


class TaskSafetyTests(unittest.TestCase):
    def setUp(self):
        self.f, self.state = fake_fixture()
        self.a = TaskActions(self.f)

    def test_complete_identity_accepted(self):
        self.assertEqual(validate_identity(self.a.identity), self.a.identity)

    def test_reject_live_external_url_before_http(self):
        for url in ["http://127.0.0.1:8764", "https://127.0.0.1:4321", "http://example.org:4321",
                    "http://localhost:4321", "http://user@127.0.0.1:4321", "http://127.0.0.1:4321/x",
                    "http://127.0.0.1:4321?x=1", "http://127.0.0.1:4321#fragment"]:
            with self.subTest(url=url):
                f, _ = fake_fixture()
                f["url"] = url
                with self.assertRaises(AssertionError):
                    TaskActions(f)
                f["api"].assert_not_called()

    def test_missing_and_foreign_identity_fields(self):
        for key in self.a.identity["verification"]:
            data = copy.deepcopy(self.a.identity)
            del data["verification"][key]
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_identity(data)
        for key, value in [("instance", "x"), ("ownerPid", os.getpid() + 1),
                           ("backendPid", True), ("endpoint", "ws://127.0.0.1:8764"),
                           ("codexHome", str(ROOT)), ("dataDir", str(ROOT))]:
            data = copy.deepcopy(self.a.identity)
            data["verification"][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_identity(data)

    def test_changed_descriptor_rejected_before_http(self):
        self.f["api"].reset_mock()
        self.f["url"] = "http://127.0.0.1:8764"
        with self.assertRaisesRegex(AssertionError, "descriptor"):
            self.a.guard()
        self.f["api"].assert_not_called()

    def test_http_identity_and_version_drift_rejected(self):
        for change in [lambda s: s["side"]["runtime"]["verification"].update(instance="b" * 32),
                       lambda s: s["daemon"].update(version="test-2"),
                       lambda s: s["daemon"].update(connected=False)]:
            f, state = fake_fixture()
            a = TaskActions(f)
            change(state)
            with self.assertRaises((AssertionError, RuntimeError)):
                a.guard()

    def test_dead_backend_rejected(self):
        self.f["process"].poll = lambda: 1
        with self.assertRaises(RuntimeError):
            self.a.guard()

    def test_foreign_task_rejected(self):
        self.state["controllers"]["tasks"].append({"id": "foreign"})
        with self.assertRaisesRegex(AssertionError, "foreign task"):
            self.a.guard()

    def test_foreign_session_and_external_workspace_rejected(self):
        owned_task(self.a, self.state)
        self.state["threads"] = [{"id": "someone-else", "cwd": self.a.identity["cwd"]}]
        with self.assertRaisesRegex(AssertionError, "foreign session"):
            self.a.guard()
        self.state["threads"] = [{"id": "host-id", "cwd": str(ROOT)}]
        with self.assertRaisesRegex(AssertionError, "foreign session"):
            self.a.guard()

    def test_role_swap_and_external_grant_rejected(self):
        task = owned_task(self.a, self.state)
        task["formerHosts"] = ["former-id"]
        self.a.owned["main"]["former"] = ["former-id"]
        task["host"], task["formerHosts"] = "former-id", ["host-id"]
        with self.assertRaisesRegex(AssertionError, "roles changed"):
            self.a.guard()
        task["host"], task["formerHosts"] = "host-id", ["former-id"]
        task["workspaces"] = [{"cwd": str(ROOT)}]
        with self.assertRaisesRegex(AssertionError, "external task grant"):
            self.a.guard()

    def test_changed_fixed_budget_and_target_rejected(self):
        task = owned_task(self.a, self.state)
        self.a.owned["main"].update(budget=copy.deepcopy(task["budget"]), target=task["target"], revision=1)
        task["budget"]["deadline"] += 60
        with self.assertRaisesRegex(AssertionError, "fixed budget"):
            self.a.guard()

    def test_unowned_alias_and_history_are_rejected(self):
        for value in ["foreign", "http://evil", "../other", "__import__('os')", "E:/test"]:
            with self.subTest(value=value), self.assertRaises(AssertionError):
                self.a.task(value)
        with self.assertRaisesRegex(AssertionError, "foreign history"):
            self.a._history("foreign-id")

    def test_confirm_requires_explicit_boolean_and_dispatch_requires_confirmation(self):
        owned_task(self.a, self.state)
        for value in [False, 1, "true", None]:
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, "explicit"):
                self.a.confirm(explicit=value)
        with self.assertRaisesRegex(AssertionError, "confirm/resume"):
            self.a.dispatch()
        self.f["model"].script.arm.assert_not_called()

    def test_wait_is_bounded_and_does_not_resend(self):
        task = owned_task(self.a, self.state)
        task["hostBusy"] = True
        self.a.timeout = .001
        with self.assertRaisesRegex(AssertionError, "no automatic resend"):
            self.a.wait(condition="host-idle")
        self.assertTrue(all(len(c.args) == 1 for c in self.f["api"].call_args_list))

    def test_wait_timeout_rejects_nan_infinite_bool_and_unbounded(self):
        for value in [float("nan"), float("inf"), -1, 0, 61, True, "30"]:
            with self.subTest(value=value), self.assertRaises(AssertionError):
                timeout_value(value)

    def test_failed_idle_host_is_not_a_success(self):
        owned_task(self.a, self.state)
        with patch.object(self.a, "_history", return_value=[{"id": "failed", "status": "failed"}]):
            with self.assertRaisesRegex(AssertionError, "not proof"):
                self.a.wait(condition="host-idle")

    def test_reports_missing_duplicate_and_wrong_count_fail(self):
        task = owned_task(self.a, self.state)
        self.a.owned["main"]["workers"] = {"worker": "worker-id"}
        task["workers"] = {"worker-id": {"cwd": self.a.identity["cwd"], "access": "read", "scope": []}}
        turn = {"id": "turn-id", "status": "completed", "items": []}
        report = {"id": "worker-id:turn-id", "threadId": "worker-id", "turnId": "turn-id",
                  "status": "completed", "cwd": self.a.identity["cwd"], "targetRevision": 1,
                  "access": "read", "write_scope": [], "report": "final"}
        message = {"id": "host-turn", "status": "completed", "items": [{"type": "userMessage",
                    "text": '[MA4 source:worker_report]\n[MA4 content]\n未验证报告\n' + json.dumps([report])}]}
        for count, passed in [(0, False), (1, True), (2, False)]:
            with self.subTest(count=count), patch.object(self.a, "_history", side_effect=
                    lambda tid: [turn] if tid == "worker-id" else [message] * count):
                if passed:
                    self.assertEqual(next(iter(self.a.reports().values()))["delivered"], 1)
                else:
                    with self.assertRaisesRegex(AssertionError, "missing/duplicated"):
                        self.a.reports()
        turn["items"] = [{"type": "agentMessage", "text": "different native final"}]
        with patch.object(self.a, "_history", side_effect=lambda tid: [turn] if tid == "worker-id" else [message]):
            with self.assertRaisesRegex(AssertionError, "differs from native"):
                self.a.reports()

    def test_report_content_must_match_actual_native_final(self):
        from tools.task_actions import delivered_reports
        report = {"id": "one"}
        history = [[{"items": [{"type": "userMessage", "text":
                    '[MA4 source:worker_report]\ncontext mentions one\n[MA4 content]\n报告\n' + json.dumps([report])}]}]]
        self.assertEqual(delivered_reports(history), [report])
        history[0][0]["items"][0]["text"] = '[MA4 source:worker_report]\ncontext mentions one'
        with self.assertRaisesRegex(AssertionError, "malformed"):
            delivered_reports(history)

    def test_reconnect_wait_tolerates_a_temporarily_missing_client(self):
        owned_task(self.a, self.state)
        old, new = SimpleNamespace(closed=False), SimpleNamespace(closed=False)
        self.f["hub"].client = old
        self.f["hub"].controllers = SimpleNamespace(snapshot=lambda: {"recovering": False})
        self.f["client"] = SimpleNamespace(closed=False)
        old.close = lambda: setattr(self.f["hub"], "client", None)
        def wait(predicate, label):
            self.assertFalse(predicate())
            self.f["hub"].client = new
            self.assertTrue(predicate())
        with patch.object(self.a, "_until", side_effect=wait):
            self.a.reconnect()


class PlanTests(unittest.TestCase):
    def test_history_plan_accepts_only_preceding_owned_aliases_and_roles(self):
        plan = ["create", {"op": "history", "session": "host"},
                {"op": "dispatch", "worker": "alpha"}, {"op": "history", "session": "alpha"},
                "handoff", {"op": "history", "session": "former"}]
        self.assertEqual(len(validate_plan(plan)), len(plan))
        for session in ["unknown-id", "worker", "former", "01a1b624-bb3b-7112-9a92-36acac28855c",
                        "E:/PG", "../worker", "http://127.0.0.1:8764", "__import__('os')", None]:
            with self.subTest(session=session), self.assertRaises(AssertionError):
                validate_plan(["create", {"op": "history", "session": session}])
        with self.assertRaisesRegex(AssertionError, "worker alias"):
            validate_plan(["create", {"op": "dispatch", "worker": "alpha"},
                           {"op": "create", "task": "second"},
                           {"op": "history", "task": "second", "session": "alpha"}])
        for key in ["threadId", "url", "path", "code"]:
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_plan(["create", {"op": "history", key: "arbitrary"}])

    def test_run_history_reads_actual_owned_session_and_records_no_transcript(self):
        f, state = fake_fixture()
        a = TaskActions(f)
        turns = [{"id": "turn-id", "status": "completed", "items": [
            {"id": "message-id", "type": "agentMessage", "text": "private test body"}]}]
        def create(name):
            owned_task(a, state)
            a.record("create", task=name)
        with patch.object(a, "create", side_effect=create), patch.object(a, "_history", return_value=turns) as read:
            steps = a.run(["create", {"op": "history", "session": "host"}])
            read.assert_called_once_with("host-id")
            self.assertEqual(steps[-1]["operation"], "history")
            self.assertEqual((steps[-1]["threadId"], steps[-1]["turnCount"], steps[-1]["itemCount"]),
                             ("host-id", 1, 1))
            self.assertEqual(steps[-1]["turns"][0]["id"], "turn-id")
            self.assertEqual(len(steps[-1]["turns"][0]["itemsSha256"]), 64)
            self.assertNotIn("private test body", json.dumps(steps))
            count = len(steps)
            self.assertIs(a.history(), turns)
            self.assertEqual(len(a.steps), count, "standalone history must not gain step side effects")

    def test_history_runtime_rejects_worker_not_created_even_if_plan_mentions_dispatch(self):
        f, state = fake_fixture()
        a = TaskActions(f)
        with patch.object(a, "create", side_effect=lambda name: owned_task(a, state)), \
                patch.object(a, "dispatch"), patch.object(a, "_history") as read:
            with self.assertRaisesRegex(AssertionError, "not created"):
                a.run(["create", {"op": "dispatch", "worker": "alpha"},
                       {"op": "history", "session": "alpha"}])
            read.assert_not_called()

    def test_finite_plan_is_copied_and_validated(self):
        plan = ["create", "draft", {"op": "confirm", "explicit": True}, "dispatch", "wait", "reports"]
        before = copy.deepcopy(plan)
        self.assertEqual(len(validate_plan(plan)), 6)
        self.assertEqual(plan, before)

    def test_arbitrary_code_ids_urls_and_paths_are_refused(self):
        plans = [[], ["eval"], ["create", {"op": "status", "task_id": "external"}],
                 ["create", {"op": "dispatch", "cwd": "E:/PG"}],
                 ["create", {"op": "status", "url": "http://127.0.0.1:8764"}],
                 ["create", {"op": "dispatch", "code": "__import__('os')"}],
                 ["create", "confirm"], ["reports"], ["create", "create"],
                 ["create", {"op": "wait", "condition": "eval(x)"}], ["create"] * 41]
        for plan in plans:
            with self.subTest(plan=plan), self.assertRaises(AssertionError):
                validate_plan(plan)


class RegistrationTimingTests(unittest.TestCase):
    """Deterministic snapshots at Hub registration / Controllers publication boundary."""
    def setUp(self):
        self.f, self.state = fake_fixture()
        self.a = TaskActions(self.f, timeout=.2)
        self.task = owned_task(self.a, self.state)
        self.task.update(status="running", goalConfirmed=True)

    def worker(self):
        return {"name": "验证执行者 worker", "state": "running", "cwd": self.a.identity["cwd"],
                "access": "read", "scope": []}

    def snapshots(self, first, complete):
        reads = []
        def api(path, *args):
            self.assertEqual(path, "/api/state")
            self.assertEqual(args, (), "registration polling must never write")
            reads.append(path)
            return copy.deepcopy(first if len(reads) <= 2 else complete)
        self.f["api"].side_effect = api
        return reads

    def begin(self, kind="dispatch", new=True):
        self.a._begin_transition("main", kind, new_worker=new)
        self.a._submit_transition(kind)
        self.f["api"].reset_mock()

    def test_native_return_id_confirms_temporary_gap_without_new_writes(self):
        gap = copy.deepcopy(self.state)
        gap["threads"] = [{"id": "new-worker", "cwd": self.a.identity["cwd"]}]
        complete = copy.deepcopy(gap)
        complete["controllers"]["tasks"][0]["workers"]["new-worker"] = self.worker()
        def tool(*args, **kwargs):
            self.a._submit_transition("dispatch")
            reads = self.snapshots(gap, complete)
            self.a.guard()
            self.assertGreater(len(reads), 2)
            self.assertEqual(self.a.owned["main"]["workers"], {}, "provisional ID must not be adopted")
            return {"success": True, "output": json.dumps({"session_id": "new-worker"})}
        with patch.object(self.a, "_tool", side_effect=tool):
            self.a.dispatch()
        self.assertEqual(self.a.owned["main"]["workers"], {"worker": "new-worker"})
        self.assertTrue(all(len(c.args) == 1 for c in self.f["api"].call_args_list))
        self.assertEqual(self.a.steps[-1]["result"], "confirmed")

    def test_different_native_return_id_never_adopts_provisional_worker(self):
        def tool(*args, **kwargs):
            self.a._submit_transition("dispatch")
            self.task["workers"]["unrelated-worker"] = self.worker()
            return {"success": True, "output": json.dumps({"session_id": "different-returned-id"})}
        with patch.object(self.a, "_tool", side_effect=tool), self.assertRaisesRegex(AssertionError, "native dispatch"):
            self.a.dispatch()
        self.assertEqual(self.a.owned["main"]["workers"], {})

    def test_without_submitted_transition_unknown_session_is_immediately_rejected(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                if pending:
                    self.state["threads"] = []
                    self.a._begin_transition("main", "dispatch", new_worker=True)
                self.state["threads"] = [{"id": "foreign", "cwd": self.a.identity["cwd"]}]
                with patch("tools.task_actions.time.sleep") as sleep, self.assertRaisesRegex(AssertionError, "foreign session"):
                    self.a.guard()
                sleep.assert_not_called()

    def test_stable_foreign_session_times_out_without_adoption_or_write(self):
        self.a.timeout = .001
        self.begin()
        self.state["threads"] = [{"id": "foreign", "cwd": self.a.identity["cwd"]}]
        with self.assertRaisesRegex(AssertionError, "no resend"):
            self.a.guard()
        self.assertEqual(self.a.owned["main"]["workers"], {})
        self.assertTrue(all(len(c.args) == 1 for c in self.f["api"].call_args_list))
        self.assertLessEqual(self.f["api"].call_count, 4)
        self.assertEqual(self.a.steps[-1]["result"], "timeout")

    def test_identity_directory_and_foreign_task_drift_fail_without_waiting(self):
        for change in (lambda s: s["side"]["runtime"]["verification"].update(instance="b"*32),
                       lambda s: s["threads"].append({"id":"foreign", "cwd":str(ROOT)}),
                       lambda s: s["controllers"]["tasks"].append({"id":"foreign-task"})):
            with self.subTest(change=change):
                self.setUp()
                self.begin()
                change(self.state)
                with patch("tools.task_actions.time.sleep") as sleep, self.assertRaises((AssertionError, RuntimeError)):
                    self.a.guard()
                sleep.assert_not_called()

    def test_external_url_during_transition_is_rejected_before_network(self):
        self.begin()
        self.f["url"] = "http://127.0.0.1:8764"
        with patch("tools.task_actions.time.sleep") as sleep, self.assertRaisesRegex(AssertionError, "descriptor"):
            self.a.guard()
        self.f["api"].assert_not_called()
        sleep.assert_not_called()

    def test_registration_cannot_hide_role_changes_or_multiple_foreign_workers(self):
        self.begin()
        self.task["host"] = "foreign-host"
        with self.assertRaisesRegex(AssertionError, "controller roles"):
            self.a.guard()
        self.task["host"] = "host-id"
        self.task["workers"] = {"one": self.worker(), "two": self.worker()}
        with self.assertRaisesRegex(AssertionError, "unrelated worker"):
            self.a.guard()
        with self.assertRaisesRegex(AssertionError, "no additional writes"):
            self.a._post("pause", "main")

    def test_handoff_gap_requires_retirement_and_preserves_original_workers(self):
        self.begin(kind="handoff", new=False)
        gap = copy.deepcopy(self.state)
        task = gap["controllers"]["tasks"][0]
        task.update(host=None, formerHosts=["host-id"])
        gap["threads"] = [{"id":"replacement", "cwd":self.a.identity["cwd"]}]
        complete = copy.deepcopy(gap)
        complete["controllers"]["tasks"][0]["host"] = "replacement"
        self.snapshots(gap, complete)
        tasks = self.a.guard()
        self.assertEqual(tasks["task"]["host"], "replacement")
        self.assertEqual(self.a.owned["main"]["host"], "host-id", "guard must not adopt a host")
        self.assertEqual(self.a._transition["candidate"], "replacement")
        bad = copy.deepcopy(complete)
        bad["controllers"]["tasks"][0]["workers"]["unexpected"] = self.worker()
        self.f["api"].side_effect = lambda *args: bad
        with self.assertRaisesRegex(AssertionError, "original workers"):
            self.a.guard()

    def test_candidate_cannot_disappear_or_switch_identity_to_become_accepted(self):
        self.begin()
        gap = copy.deepcopy(self.state)
        gap["threads"] = [{"id":"first", "cwd":self.a.identity["cwd"]}]
        complete = copy.deepcopy(self.state)
        complete["controllers"]["tasks"][0]["workers"]["second"] = self.worker()
        self.snapshots(gap, complete)
        with self.assertRaisesRegex(AssertionError, "candidate identity"):
            self.a.guard()


if __name__ == "__main__":
    unittest.main()
