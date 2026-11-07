"""Maintenance event checks; fake API faults never contact port 8764 or a model."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import maintenance as m


FAIL_REPORT = {"result": "failed", "profiles": ["tasks"], "ui_requested": False, "checks": [
    {"check": "python", "status": "failed", "exit_code": 1, "counts": {"total": 3, "skipped": 0}}]}
PASS_REPORT = {"result": "passed", "profiles": ["tasks"], "ui_requested": False, "checks": [
    {"check": "python", "status": "passed", "exit_code": 0, "counts": {"total": 3, "skipped": 0}}]}
FAIL = (1, "FAIL: test_example\nAssertionError: expected 2, got 1\nfailed: python=failed\n", FAIL_REPORT)
PASS = (0, "Ran 3 tests in 0.1s\nOK\npassed: python=passed\n", PASS_REPORT)


class FakeAPI:
    """Faithful relevant fields of Controllers snapshot, with injected uncertainty."""
    def __init__(self):
        self.tasks = []
        self.posts = []
        self.reads = 0
        self.create_fault = None
        self.confirm_fault = None
        self.before_state = None

    def state(self):
        self.reads += 1
        if self.before_state:
            self.before_state(self)
        tasks = copy.deepcopy(self.tasks)
        threads = []
        for task in tasks:
            for tid in [task.get("host"), *task["workers"]]:
                if tid:
                    threads.append({"id": tid, "status": "running" if task["hostBusy"] else "idle"})
            task.setdefault("diagnosis", {"code": "sending" if task.get("outbox") else task["status"],
                                          "confirmBlocker": "pending send" if task.get("outbox") else None})
            task.pop("outbox", None)  # Production snapshot intentionally omits this.
        return {"daemon": {"connected": True}, "threads": threads, "controllers": {
            "tasks": tasks, "recovering": False, "error": None}}

    def post(self, path, body):
        self.posts.append((path, copy.deepcopy(body)))
        budget = {**body["budget"], "currency": "CNY"}
        if path.endswith("create"):
            if self.create_fault == "before":
                raise TimeoutError("injected create timeout before acceptance")
            self.tasks.append({"id": "test-task", "cwd": body["cwd"], "name": body["name"],
                               "createRequest": body["request_id"], "target": "", "goalConfirmed": False,
                               "draftRevision": 1, "draft": {"target": body["target"], "budget": budget},
                               "budget": budget, "status": "draft", "host": "test-host", "hostBusy": False,
                               "workers": {}, "pending": [], "firstStartedAt": None})
            if self.create_fault == "after":
                raise TimeoutError("injected create timeout after acceptance")
            return {"taskId": "test-task", "threadId": "test-host"}
        if path.endswith("confirm"):
            if self.confirm_fault == "before":
                raise TimeoutError("injected confirm timeout before acceptance")
            task = self.tasks[0]
            task.update(target=body["target"], budget=budget, goalConfirmed=True,
                        draftRevision=2, revision=1, workspaces=body["workspaces"],
                        firstStartedAt=1000, status="running")
            task.pop("draft")
            if self.confirm_fault == "after":
                raise TimeoutError("injected confirm timeout after acceptance")
            return {"resumed": True}
        raise AssertionError("unexpected mutation " + path)


class MaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.base = m.ROOT / ".agent-tmp" / "maintenance-worker-20261107"
        self.base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="unit-", dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for directory in ("tools", "web"):
            (self.repo / directory).mkdir()
        files = {"AGENTS.md": "fixture rules\n", "tools/verify.py": "# verifier fixture\n",
                 "app.py": "value = 1\n", "web/app.js": "let value = 1;\n",
                 "test_app.py": "# protected tests\n", "config.py": "# protected config\n",
                 ".gitignore": ".ma4/\n.agent-tmp/\n__pycache__/\nignored.py\n"}
        for name, value in files.items():
            (self.repo / name).write_text(value, encoding="utf-8", newline="\n")
        self.git("init", "-q")
        self.git("config", "core.fileMode", "false")
        self.git("config", "core.autocrlf", "false")
        self.git("add", ".")
        self.git("-c", "user.name=Maintenance test", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.api = FakeAPI()

    def git(self, *args):
        return m.git(self.repo, *args)

    def capture(self, result=FAIL):
        if len(result) == 2:
            result += (FAIL_REPORT,)
        return m.capture(self.repo, ["tasks"], lambda *_: result)

    def start(self, scope=None, duration=5):
        return m.start(self.repo, scope or ["app.py"], duration, self.api, now=lambda: 1000)

    def test_repository_requires_exact_absolute_git_root_and_verifier(self):
        self.assertEqual(m.repository(str(self.repo)), self.repo)
        for value in (".", str(self.repo / "web"), str(self.repo / "missing")):
            with self.subTest(value=value), self.assertRaises(m.Stop):
                m.repository(value)
        (self.repo / "tools/verify.py").unlink()
        with self.assertRaises(m.Stop):
            m.repository(str(self.repo))

    def test_worktree_regular_git_file_supported(self):
        other = self.repo / ".agent-tmp" / "isolated"
        self.git("worktree", "add", "--detach", str(other), "HEAD")
        self.assertTrue((other / ".git").is_file())
        self.assertEqual(m.repository(str(other)), other)
        self.assertEqual(m.fingerprint(other)["head"], m.fingerprint(self.repo)["head"])

    def test_git_environment_cannot_redirect_repository(self):
        with patch.dict(os.environ, {"GIT_DIR": str(self.repo / "wrong"), "GIT_WORK_TREE": "wrong"}):
            self.assertEqual(m.repository(str(self.repo)), self.repo)

    def test_only_finite_lightweight_profiles(self):
        self.assertEqual(m.groups(["tasks", "tasks", "map"]), ["map", "tasks"])
        for value in ([], ["transport"], ["platform"], ["live-ui"], ["--ui"], ["cmd"]):
            with self.subTest(value=value), self.assertRaises(m.Stop):
                m.groups(value)

    def test_success_skips_or_no_failure_do_not_dispatch(self):
        cases = [PASS, (0, "passed_with_skips: python=passed_with_skips\n"),
                 (1, "tool unavailable\n"), (0, "failed: python=failed\n"),
                 (1, "failed: node=not_run\n"), (1, "failed: unknown=failed\n")]
        for result in cases:
            with self.subTest(result=result):
                self.capture(result)
                with self.assertRaises(m.Stop):
                    self.start()
        self.assertEqual(self.api.posts, [])
        self.assertEqual(self.api.reads, 0)

    def test_failed_event_keeps_evidence_bounded_and_no_history(self):
        event = self.capture((1, "x" * 100000 + "\nfailed: python=failed\n"))
        self.assertLessEqual(len(event["evidence"]["summary"]), m.MAX_OUTPUT)
        files = list((self.repo / ".ma4/maintenance").iterdir())
        self.assertEqual([p.name for p in files], ["current.json"])
        self.assertLess(files[0].stat().st_size, m.MAX_STATE)

    def test_duplicate_capture_preserves_request_and_first_evidence(self):
        first = self.capture()
        second = self.capture((1, "different elapsed time\nfailed: python=failed\n"))
        self.assertEqual(first, second)

    def test_pass_recapture_invalidates_unstarted_failure(self):
        self.capture()
        self.capture(PASS)
        with self.assertRaises(m.Stop):
            self.start()

    def test_source_change_during_check_marks_invalid(self):
        def runner(*_args):
            (self.repo / "app.py").write_text("value = 2\n", encoding="utf-8")
            return FAIL
        event = m.capture(self.repo, ["tasks"], runner)
        self.assertEqual(event["evidence"]["result"], "invalid")
        with self.assertRaises(m.Stop):
            self.start()

    def test_dirty_same_size_content_rejects_stale_start(self):
        self.capture()
        path = self.repo / "app.py"
        old = path.stat()
        path.write_text("value = 9\n", encoding="utf-8", newline="\n")
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        with self.assertRaisesRegex(m.Stop, "过期"):
            self.start()
        self.assertEqual(self.api.posts, [])

    def test_untracked_ignored_source_changes_invalidate_evidence(self):
        for name in ("untracked.py", "ignored.py"):
            with self.subTest(name=name):
                self.capture()
                (self.repo / name).write_text("value = 3\n", encoding="utf-8")
                with self.assertRaises(m.Stop):
                    self.start()

    def test_tracked_deletion_and_index_and_head_are_fingerprinted(self):
        original = m.fingerprint(self.repo)
        (self.repo / "app.py").unlink()
        deleted = m.fingerprint(self.repo)
        self.assertNotEqual(original, deleted)
        self.git("add", "-u")
        self.assertNotEqual(deleted, m.fingerprint(self.repo))
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "delete fixture")
        self.assertNotEqual(original["head"], m.fingerprint(self.repo)["head"])

    def test_runtime_files_do_not_stale_evidence(self):
        self.capture()
        for folder in (".ma4", ".agent-tmp", "__pycache__"):
            root = self.repo / folder
            root.mkdir(exist_ok=True)
            (root / "noise.py").write_text("runtime", encoding="utf-8")
        self.assertEqual(self.start()["result"], "started")

    def test_plan_is_read_only_and_never_uses_api(self):
        self.capture()
        path = m.Store(self.repo).path
        before = path.read_bytes()
        with patch.object(m.API, "state", side_effect=AssertionError("network")):
            self.assertIn("task", m.plan(self.repo, ["app.py"], 5))
            self.assertEqual(m.reconcile(self.repo)["result"], "not_started")
        self.assertEqual(before, path.read_bytes())

    def test_scope_refuses_roots_escape_protected_paths_and_directories(self):
        for scope in ([], ["."], ["web"], ["../outside.py"], ["app.py/../web/app.js"],
                      [str(self.repo / "app.py")], ["E:/outside.py"], ["web\\app.js"],
                      ["*.py"], [".git/config"], [".ma4/state.py"], ["test_app.py"],
                      ["tools/verify.py"], ["tools/check_architecture.py"], ["tools/feature_map.py"],
                      ["tools/maintenance.py"], ["config.py"], ["AGENTS.md"], ["missing.py"],
                      ["web/../app.py"], ["web/app.js:secret"], ["app.py."], ["web//app.js"]):
            with self.subTest(scope=scope), self.assertRaises(m.Stop):
                m.scopes(self.repo, scope)
        self.assertEqual(m.scopes(self.repo, ["web/app.js", "app.py"]), ["app.py", "web/app.js"])

    def test_scope_rejects_hardlink(self):
        os.link(self.repo / "app.py", self.repo / "linked.py")
        with self.assertRaises(m.Stop):
            m.scopes(self.repo, ["linked.py"])

    def test_real_junction_or_symlink_is_not_followed(self):
        target = self.repo / "web"
        link = self.repo / "linked"
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                  capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr.decode(errors="replace"))
            self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        else:
            link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(m.Stop):
            m.scopes(self.repo, ["linked/app.js"])
        with self.assertRaises(m.Stop):
            m.fingerprint(self.repo)

    def test_reparse_flag_on_root_and_state_is_rejected(self):
        original = Path.lstat
        def flagged(path):
            result = original(path)
            if path == self.repo:
                class Info:
                    st_mode = result.st_mode
                    st_file_attributes = 0x400
                return Info()
            return result
        with patch.object(Path, "lstat", flagged), self.assertRaises(m.Stop):
            m.repository(str(self.repo))

    def test_budget_requires_finite_positive_up_to_60(self):
        self.capture()
        for value in (0, -1, 61, float("nan"), float("inf"), True, None):
            with self.subTest(value=value), self.assertRaises(m.Stop):
                self.start(duration=value)
        self.assertEqual(m.minutes(60), 60)
        self.assertEqual(self.api.posts, [])

    def test_explicit_start_posts_once_and_fixes_budget_and_scope(self):
        event = self.capture()
        result = self.start()
        self.assertEqual(result["result"], "started")
        self.assertEqual([p.rsplit("/", 1)[1] for p, _ in self.api.posts], ["create", "confirm"])
        for _path, body in self.api.posts:
            self.assertEqual(body["budget"], {"deadline": 1300})
        create, confirm = [body for _, body in self.api.posts]
        self.assertEqual(create["request_id"], event["request_id"])
        self.assertNotIn("idea", create)
        self.assertEqual(confirm["workspaces"], [{"cwd": str(self.repo), "write_scope": ["app.py"]}])
        for fragment in ("停止条件", "一个修复回合", "独立审查", "不得提交", "不是操作系统沙箱", "无 token 限制"):
            self.assertIn(fragment, confirm["target"])

    def test_repeated_start_never_posts_again_even_after_repair(self):
        self.capture()
        self.start()
        (self.repo / "app.py").write_text("value = 2\n", encoding="utf-8")
        for _ in range(3):
            self.assertEqual(self.start()["result"], "started")
        self.assertEqual(len(self.api.posts), 2)
        with self.assertRaises(m.Stop):
            self.start(duration=10)

    def test_started_evidence_never_overwritten_even_terminal(self):
        event = self.capture()
        self.start()
        self.api.tasks[0]["status"] = "completed"
        with self.assertRaises(m.Stop):
            self.capture(PASS)
        self.assertEqual(m.current_event(self.repo)["evidence"], event["evidence"])

    def test_create_timeout_after_acceptance_only_reads_then_later_start_confirms(self):
        self.capture()
        self.api.create_fault = "after"
        self.assertEqual(self.start()["result"], "draft")
        self.assertEqual(len(self.api.posts), 1)
        self.assertEqual(self.start()["result"], "started")
        self.assertEqual(len(self.api.posts), 2)

    def test_create_timeout_before_acceptance_never_replays_even_after_restart(self):
        self.capture()
        self.api.create_fault = "before"
        self.assertEqual(self.start()["result"], "unresolved")
        self.assertEqual(self.start()["result"], "unresolved")
        self.assertEqual(len(self.api.posts), 1)

    def test_confirm_timeout_after_acceptance_proves_started_without_retry(self):
        self.capture()
        self.api.confirm_fault = "after"
        self.assertEqual(self.start()["result"], "started")
        self.assertEqual(self.start()["result"], "started")
        self.assertEqual(len(self.api.posts), 2)

    def test_confirm_timeout_before_acceptance_never_blindly_resends(self):
        self.capture()
        self.api.confirm_fault = "before"
        self.assertEqual(self.start()["result"], "unresolved")
        self.assertEqual(self.start()["result"], "unresolved")
        self.assertEqual(len(self.api.posts), 2)

    def test_intents_persist_before_remote_mutation(self):
        self.capture()
        original = self.api.post
        def verify(path, body):
            event = m.current_event(self.repo)
            self.assertEqual(event["intent"]["phase"],
                             "create_intent" if path.endswith("create") else "confirm_intent")
            return original(path, body)
        self.api.post = verify
        self.start()

    def test_confirm_timeout_and_read_failure_remains_sealed(self):
        self.capture()
        self.api.confirm_fault = "after"
        def fail_read(api):
            if len(api.posts) == 2:
                raise TimeoutError("injected GET outage")
        self.api.before_state = fail_read
        with self.assertRaises(TimeoutError):
            self.start()
        self.api.before_state = None
        self.assertEqual(self.start()["result"], "started")
        self.assertEqual(len(self.api.posts), 2)

    def test_mismatched_task_goal_revision_budget_scope_identity_stops(self):
        self.capture()
        self.start()
        good = copy.deepcopy(self.api.tasks[0])
        for field, value in (("target", "changed"), ("revision", 2), ("draftRevision", 3),
                             ("budget", {"deadline": 2000, "currency": "CNY"}),
                             ("workspaces", [{"cwd": str(self.repo), "write_scope": []}]),
                             ("name", "foreign"), ("cwd", str(self.repo.parent)),
                             ("id", "foreign"), ("status", "alien")):
            self.api.tasks[0] = {**good, field: value}
            with self.subTest(field=field), self.assertRaises(m.Stop):
                self.start()
        self.assertEqual(len(self.api.posts), 2)

    def test_unknown_or_disconnected_state_never_creates(self):
        self.capture()
        for state in ({}, {"daemon": {"connected": False}, "controllers": {"tasks": []}},
                      {"daemon": {"connected": True}, "controllers": {"recovering": True, "tasks": []}}):
            with patch.object(self.api, "state", return_value=state), self.assertRaises(m.Stop):
                self.start()
        self.assertEqual(self.api.posts, [])

    def foreign_task(self, status="running", scope=None):
        return {"id": "old-task", "status": status, "cwd": str(self.repo), "hostBusy": False,
                "workers": {}, "workspaces": [{"cwd": str(self.repo), "write_scope": scope or ["app.py"]}]}

    def test_overlapping_active_grant_refused_but_disjoint_allowed(self):
        self.capture()
        old = self.foreign_task()
        self.api.tasks.append(old)
        before = copy.deepcopy(old)
        with self.assertRaisesRegex(m.Stop, "重叠"):
            self.start()
        self.assertEqual(old, before)
        self.assertEqual(self.api.posts, [])
        m.no_overlap(self.repo, ["web/app.js"], self.api.tasks)

    def test_paused_or_terminal_unfinished_worker_still_blocks(self):
        for status in ("paused", "completed", "stopped", "attention"):
            old = self.foreign_task(status)
            old["workers"] = {"w": {"state": "sending", "access": "write", "scope": ["app.py"]}}
            with self.subTest(status=status), self.assertRaises(m.Stop):
                m.no_overlap(self.repo, ["app.py"], [old])
            old["workers"]["w"]["access"] = "read"
            m.no_overlap(self.repo, ["app.py"], [old])

    def test_unknown_worker_stops_even_when_other_task_is_terminal(self):
        old = self.foreign_task("completed")
        old["workers"] = {"w": {"state": "unknown", "access": "write", "scope": ["app.py"]}}
        self.api.tasks = [old]
        with self.assertRaises(m.Stop):
            m.state_tasks(self.api.state())

    def test_overlap_appearing_after_create_prevents_confirm(self):
        self.capture()
        def appear(api):
            if len(api.posts) == 1 and len(api.tasks) == 1:
                api.tasks.append(self.foreign_task())
        self.api.before_state = appear
        with self.assertRaises(m.Stop):
            self.start()
        self.assertEqual(len(self.api.posts), 1)

    def test_source_change_after_create_prevents_confirm(self):
        self.capture()
        def change(api):
            if api.posts:
                (self.repo / "app.py").write_text("value = 8\n", encoding="utf-8")
        self.api.before_state = change
        with self.assertRaises(m.Stop):
            self.start()
        self.assertEqual(len(self.api.posts), 1)

    def test_budget_does_not_extend_on_create_recovery(self):
        self.capture()
        self.api.create_fault = "after"
        self.start()
        with self.assertRaises(m.Stop):
            m.start(self.repo, ["app.py"], 5, self.api, now=lambda: 1301)
        self.assertEqual(len(self.api.posts), 1)
        self.assertEqual(m.current_event(self.repo)["intent"]["deadline"], 1300)

    def test_duplicate_remote_request_id_stops(self):
        self.capture()
        self.api.create_fault = "after"
        self.start()
        self.api.tasks.append({**self.api.tasks[0], "id": "second"})
        with self.assertRaises(m.Stop):
            self.start()
        self.assertEqual(len(self.api.posts), 1)

    def test_missing_first_start_is_uncertain_not_retried(self):
        self.capture()
        self.start()
        self.api.tasks[0]["firstStartedAt"] = None
        self.assertEqual(self.start()["result"], "unresolved")
        self.assertEqual(len(self.api.posts), 2)

    def test_read_only_reconcile_does_not_update_current_record(self):
        self.capture()
        self.start()
        before = m.Store(self.repo).path.read_bytes()
        self.assertEqual(m.reconcile(self.repo, self.api)["result"], "started")
        self.assertEqual(before, m.Store(self.repo).path.read_bytes())
        self.assertEqual(len(self.api.posts), 2)

    def test_lock_blocks_other_process_and_never_kills_or_steals(self):
        store = m.Store(self.repo)
        with store.lock():
            data = store.lock_path.read_bytes()
            script = ("from pathlib import Path; from tools.maintenance import Store, Stop; "
                      "s=Store(Path(__import__('sys').argv[1])); "
                      "\ntry:\n with s.lock(): pass\nexcept Stop: raise SystemExit(7)\n")
            result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script, str(self.repo)],
                                    cwd=m.ROOT, capture_output=True)
            self.assertEqual(result.returncode, 7, result.stderr.decode(errors="replace"))
            self.assertEqual(data, store.lock_path.read_bytes())
        self.assertFalse(store.lock_path.exists())
        store.lock_path.write_text('{"pid": -1}', encoding="utf-8")
        with self.assertRaises(m.Stop):
            with store.lock():
                pass
        self.assertTrue(store.lock_path.exists())

    def test_corrupt_unknown_or_tampered_evidence_is_rejected(self):
        self.capture()
        path = m.Store(self.repo).path
        good = path.read_bytes()
        for content in (b"bad", b"[]", b"{}", b"x" * (m.MAX_STATE + 1)):
            path.write_bytes(content)
            with self.assertRaises(m.Stop):
                m.Store(self.repo).read()
        path.write_bytes(good)
        data = json.loads(good)
        data["evidence"]["summary"] = "changed"
        path.write_bytes(m.encoded(data))
        with self.assertRaises(m.Stop):
            m.Store(self.repo).read()

    def test_cli_requires_scope_and_budget_for_start(self):
        for arguments in (["start"], ["start", "--scope", "app.py"], ["capture", "transport"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                m.main(arguments)

    def test_real_capture_runner_uses_empty_codex_home_and_bounded_output(self):
        # Controlled verifier fixture, not production failures and not a model.
        script = ("import os, sys, json\nfrom pathlib import Path\n"
                  "p=Path(os.environ['CODEX_HOME'])\nassert p.is_dir() and not list(p.iterdir())\n"
                  "assert 'MA4_URL' not in os.environ\n"
                  "o=Path(sys.argv[sys.argv.index('--output')+1]); o.mkdir()\n"
                  f"(o/'result.json').write_text(json.dumps({FAIL_REPORT!r}), encoding='utf-8')\n"
                  "print('x' * 20000)\nprint('failed: python=failed')\nraise SystemExit(1)\n")
        (self.repo / "tools/verify.py").write_text(script, encoding="utf-8", newline="\n")
        with patch.dict(os.environ, {"CODEX_HOME": "must-not-read", "MA4_URL": "must-not-contact"}):
            event = m.capture(self.repo, ["tasks"])
        self.assertEqual(event["evidence"]["result"], "failed")
        self.assertLessEqual(len(event["evidence"]["summary"]), m.MAX_OUTPUT)
        self.assertFalse(list((self.repo / ".agent-tmp").iterdir()))

    def complete(self):
        self.capture()
        self.start()
        self.api.tasks[0]["status"] = "completed"

    def ack(self):
        return m.acknowledge(self.repo, "派发者独立审查：已核对文件差异与相关验证；测试夹具，不代表真实修复。", self.api)

    def test_ack_requires_explicit_independent_review_and_same_idle_terminal_task(self):
        self.complete()
        with self.assertRaises(m.Stop):
            m.acknowledge(self.repo, "", self.api)
        result = self.ack()
        self.assertEqual(result["result"], "acknowledged")
        self.assertEqual(len(self.api.posts), 2)
        before = m.Store(self.repo).path.read_bytes()
        self.assertEqual(self.ack()["result"], "acknowledged")
        self.assertEqual(before, m.Store(self.repo).path.read_bytes())

    def test_ack_allows_new_changed_source_failure_after_review(self):
        self.complete()
        old = m.current_event(self.repo)
        self.ack()
        (self.repo / "app.py").write_text("value = 2\n", encoding="utf-8")
        new = self.capture()
        self.assertNotEqual(new["request_id"], old["request_id"])
        self.assertIsNone(new["intent"])
        self.assertEqual(new["last_acknowledged_request_id"], old["request_id"])
        self.api.tasks = []
        self.assertEqual(self.start()["result"], "started")

    def test_ack_cannot_relaunch_unchanged_failure_even_after_success_capture(self):
        self.complete()
        self.ack()
        before = m.current_event(self.repo)
        self.assertEqual(self.capture(), before)
        with self.assertRaises(m.Stop):
            self.start()
        self.capture(PASS)
        self.capture()
        with self.assertRaises(m.Stop):
            self.start()
        self.assertEqual(len(self.api.posts), 2)

    def test_ack_refuses_nonterminal_busy_pending_outbox_handoff_unknown(self):
        self.complete()
        good = copy.deepcopy(self.api.tasks[0])
        cases = [("status", "running"), ("status", "paused"), ("status", "attention"),
                 ("status", "budget"), ("hostBusy", True), ("hostTurn", "active"),
                 ("pending", [{"id": "pending"}]), ("outbox", {"id": "uncertain"}),
                 ("handoff", "pending"), ("handoffPending", "unsent"),
                 ("workers", {"w": {"state": "queued"}}),
                 ("workers", {"w": {"state": "running"}}),
                 ("workers", {"w": {"state": "unknown"}}),
                 ("diagnosis", {}), ("diagnosis", {"code": "completed"}),
                 ("target", "foreign"), ("createRequest", "foreign")]
        for field, value in cases:
            self.api.tasks[0] = {**good, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(m.Stop):
                self.ack()
        self.assertNotIn("acknowledgement", m.current_event(self.repo))
        self.assertEqual(len(self.api.posts), 2)

    def test_ack_requires_live_host_and_worker_idle_not_offline_or_absent(self):
        self.complete()
        self.api.tasks[0]["workers"] = {"worker": {"state": "idle", "turnId": None}}
        state = self.api.state()
        for status in ("running", "approval", "input", "offline", "error", "unknown"):
            changed = copy.deepcopy(state)
            changed["threads"][1]["status"] = status
            with self.subTest(status=status), patch.object(self.api, "state", return_value=changed), self.assertRaises(m.Stop):
                self.ack()
        state["threads"] = []
        with patch.object(self.api, "state", return_value=state), self.assertRaises(m.Stop):
            self.ack()
        self.assertEqual(self.ack()["result"], "acknowledged")

    def test_stopped_can_ack_without_asserting_success(self):
        self.complete()
        self.api.tasks[0]["status"] = "stopped"
        result = m.acknowledge(self.repo, "独立审查：此次未修好，保留实际失败说明；停止自动维护，后续需人工判断。", self.api)
        self.assertEqual(result["acknowledgement"]["status"], "stopped")

    def test_incomplete_check_reports_never_become_repair_tasks(self):
        for updates in ({"error": "missing executable"}, {"counts": {"total": 0}},
                        {"counts": {"total": 3, "skipped": 3}}, {"exit_code": 0}):
            report = copy.deepcopy(FAIL_REPORT)
            report["checks"][0].update(updates)
            with self.subTest(updates=updates):
                event = self.capture((1, FAIL[1], report))
                self.assertEqual(event["evidence"]["result"], "invalid")
                with self.assertRaises(m.Stop):
                    self.start()

    def test_real_controller_contract_with_fake_hub_including_hidden_outbox(self):
        # The real do_create/do_confirm/publish/diagnosis code, no actor thread,
        # HTTP listener, daemon or model. Hub methods are in-memory fixtures.
        from controllers import Controllers
        from test_controllers import Hub
        hub = Hub()
        controller = Controllers(hub, self.repo / ".ma4" / "controller-fixture", clock=lambda: 1000)
        class ControllerAPI:
            def state(inner):
                return {"daemon": {"connected": True}, "controllers": controller.snapshot(),
                        "threads": [{"id": tid, "status": "idle"} for tid in hub.sessions]}

            def post(inner, path, body):
                if path == "/api/tasks/create":
                    return controller.do_create(**body)
                if path == "/api/tasks/confirm":
                    return controller.do_confirm(**body)
                raise AssertionError(path)
        self.api = ControllerAPI()
        self.capture()
        result = self.start()
        self.assertEqual(result["result"], "started")
        self.assertEqual(len(hub.sessions), 1)
        self.assertEqual(len(hub.sent), 1)
        task = controller.tasks[result["task_id"]]
        task.update(status="completed", hostBusy=False, hostTurn=None)
        task["outbox"] = {"id": "pending-send"}
        controller.publish()
        self.assertNotIn("outbox", self.api.state()["controllers"]["tasks"][0])
        with self.assertRaises(m.Stop):
            self.ack()
        task["outbox"] = {}
        controller.publish()
        self.assertEqual(self.ack()["result"], "acknowledged")
        self.assertEqual(len(hub.sent), 1)

    def test_api_is_fixed_loopback_no_proxy_and_uses_request_header(self):
        from unittest.mock import Mock
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"taskId":"fixture"}'
        with patch.object(m.http.client, "HTTPConnection", return_value=connection) as factory:
            value = m.API().post("/api/tasks/create", {"request_id": "fixture"})
        factory.assert_called_once_with("127.0.0.1", 8764, timeout=15)
        self.assertEqual(value, {"taskId": "fixture"})
        request = connection.request.call_args
        self.assertEqual(request.args, ("POST", "/api/tasks/create"))
        self.assertEqual(request.kwargs["headers"]["X-MA4-Request"], "1")
        connection.close.assert_called_once()

    def test_api_redirect_error_malformed_or_oversized_response_stops(self):
        from unittest.mock import Mock
        for status, body in ((302, b'{}'), (500, b'{}'), (200, b'[]'),
                             (200, b'x' * (m.MAX_API + 1)), (200, b'bad')):
            connection = Mock()
            response = connection.getresponse.return_value
            response.status, response.read.return_value = status, body
            with self.subTest(status=status, size=len(body)), \
                    patch.object(m.http.client, "HTTPConnection", return_value=connection), \
                    self.assertRaises((m.Stop, ValueError)):
                m.API().state()
            connection.close.assert_called_once()

    def test_unknown_local_phase_stops_without_post(self):
        self.capture()
        self.start()
        store = m.Store(self.repo)
        event = store.read()
        event["intent"]["phase"] = "alien"
        store.save(event)
        with self.assertRaises(m.Stop):
            self.start()
        self.assertEqual(len(self.api.posts), 2)

    def test_paused_uncertain_host_send_still_reserves_write_scope(self):
        self.capture()
        old = self.foreign_task("paused")
        old["outbox"] = {"id": "uncertain-send"}
        self.api.tasks = [old]
        with self.assertRaisesRegex(m.Stop, "重叠"):
            self.start()
        self.assertEqual(self.api.posts, [])


if __name__ == "__main__":
    unittest.main()
