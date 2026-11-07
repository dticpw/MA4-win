"""Behavioural checks for the feature-oriented verification entry point."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import verify
from tools.smoke_test import doctor, browser_checks, fixture


class VerifyTest(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("MA4_TEST_SCRATCH", verify.ROOT / ".agent-tmp"))
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="verify-tests-", dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_shared_checks_run_once_and_sensitive_suites_are_opt_in(self):
        plan = verify.make_plan(["core", "sessions", "side", "core"], True, self.root)
        python = plan[0][1]
        self.assertEqual(python.count("test_server"), 1)
        self.assertIn("test_health", python)
        self.assertNotIn("test_model_image_preview", python)
        self.assertNotIn("transport", [name for name, _ in plan])
        self.assertNotIn("live-ui", [name for name, _ in plan])
        self.assertNotIn("task-flows", [name for name, _ in plan])
        self.assertEqual(len([name for name, _ in plan if name.endswith("_check")]), 5)
        self.assertFalse(any("controller_ui_check.mjs" in " ".join(cmd) for _, cmd in plan))
        self.assertEqual([name for name, _ in verify.make_plan(["transport"], False, self.root)], ["transport"])
        live = verify.make_plan(["live-ui"], False, self.root)
        self.assertEqual(len(live), 1)
        self.assertIn("--ui-output", live[0][1])
        self.assertNotIn("--serve", live[0][1])

    def test_plan_creates_no_output_and_does_not_execute(self):
        folder = self.root / "plan-only"
        with patch.object(verify, "execute") as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(verify.main(["plan", "tasks", "--ui", "--output", str(folder)]), 0)
        execute.assert_not_called()
        self.assertFalse(folder.exists())

    def test_ci_uses_logic_checks_and_map_without_native_or_browser_suites(self):
        plan = verify.make_plan(["ci", "map", "tasks"], False, self.root)
        self.assertEqual([name for name, _ in plan], ["python", "node", "map"])
        python = plan[0][1]
        self.assertIn("test_desktop.NativeLauncherTest", python)
        self.assertNotIn("test_desktop", python)
        self.assertNotIn("test_model_image_preview", python)
        self.assertIn("test_platform", python)
        self.assertEqual(python.count("test_controllers"), 1)
        self.assertEqual(python.count("test_task_policy"), 1)
        self.assertEqual(python.count("test_architecture"), 1)
        for module in ("test_task_actions", "test_task_scenarios", "test_maintenance"):
            self.assertEqual(python.count(module), 1)
        self.assertIn("test_session_actions.mjs", plan[1][1])
        self.assertIn("--test-reporter=tap", plan[1][1])
        with patch.object(verify, "execute") as execute, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            verify.main(["run", "ci", "--ui"])
        self.assertEqual(error.exception.code, 2)
        execute.assert_not_called()

    def test_task_flows_require_explicit_selection_and_use_owned_scratch(self):
        plan = verify.make_plan(["task-flows", "task-flows"], False, self.root)
        self.assertEqual(len(plan), 1)
        name, command = plan[0]
        self.assertEqual(name, "task-flows")
        self.assertIn("tools/task_scenarios.py", command)
        self.assertEqual(command[command.index("--scratch-root") + 1], str(self.root / "task-flows"))
        self.assertEqual(command[command.index("--output") + 1], str(self.root / "task-flows/result.json"))
        self.assertNotIn("8764", " ".join(command))
        with patch.object(verify, "execute") as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(verify.main(["plan", "task-flows"]), 0)
        execute.assert_not_called()

    def test_changed_map_fails_ci_without_rewriting_review(self):
        from tools import feature_map
        import hashlib
        (self.root / "validation").mkdir()
        source = self.root / "app.py"
        source.write_text("value = 1\n", encoding="utf-8")
        text = '<a id="sessions"></a>\n## Send\nOpen and send.\n'
        (self.root / "FEATURE-MAP.md").write_text(text, encoding="utf-8")
        (self.root / "proof.json").write_text('{}', encoding="utf-8")
        record = self.root / feature_map.REVIEW
        record.write_text(json.dumps({"version": 1, "features": {"sessions": {
            "recipe_sha256": hashlib.sha256(feature_map.recipe(text, "sessions").encode()).hexdigest(),
            "source_reviewed_at": "2026-11-07", "inputs": {"app.py": feature_map.digest(source)},
            "evidence": [{"path": "proof.json", "sha256": feature_map.digest(self.root / "proof.json")}]}}}),
            encoding="utf-8")
        before = record.read_bytes()
        self.assertEqual(feature_map.inspect(self.root)["result"], "current")
        source.write_text("value = 2\n", encoding="utf-8")
        script = ("from tools import feature_map; from functools import partial; "
                  f"feature_map.inspect = partial(feature_map.inspect, {str(self.root)!r}); "
                  "raise SystemExit(feature_map.main())")
        output = self.root / "stale-map"
        with patch.object(verify, "make_plan", return_value=[("map", [sys.executable, "-B", "-c", script])]), \
                contextlib.redirect_stdout(io.StringIO()):
            code = verify.main(["run", "ci", "--output", str(output)])
        self.assertEqual(code, 1)
        result = json.loads((output / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["checks"][0]["exit_code"], 2)
        self.assertEqual(result["result"], "failed")
        self.assertEqual(record.read_bytes(), before)

    def test_output_refuses_escape_and_existing_material(self):
        for path in (verify.ROOT, verify.ROOT / ".agent-tmp", self.root,
                     verify.ROOT / ".agent-tmp/../outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                verify.checked_output(path)
        self.assertEqual(verify.checked_output(self.root / "new"), self.root / "new")

    def test_failure_exits_nonzero_and_does_not_run_later_checks(self):
        folder = self.root / "failure"
        marker = self.root / "must-not-exist"
        plan = [("bad", [sys.executable, "-c", "print('expected failure'); raise SystemExit(7)"]),
                ("later", [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"])]
        with patch.object(verify, "make_plan", return_value=plan), contextlib.redirect_stdout(io.StringIO()):
            code = verify.main(["run", "tooling", "--output", str(folder)])
        self.assertEqual(code, 1)
        self.assertFalse(marker.exists())
        report = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(report["result"], "failed")
        self.assertEqual(report["checks"][0]["exit_code"], 7)
        self.assertEqual(report["checks"][1]["status"], "not_run")
        self.assertIn("expected failure", (folder / "bad.log").read_text(encoding="utf-8"))

    def test_missing_executable_is_a_failure(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = verify.execute([("missing", [str(self.root / "missing-executable")])], self.root, os.environ.copy())
        self.assertEqual(result[0]["status"], "failed")
        self.assertIn("error", result[0])

    def test_python_skips_are_explicit_and_zero_tests_fail(self):
        for stdout, code, status, skipped in (
                ("Ran 2 tests in 0.01s\nOK (skipped=1)", 0, "passed_with_skips", 1),
                ("Ran 0 tests in 0.01s\nOK", 0, "failed", 0),
                ("Ran 2 tests in 0.01s\nFAILED (failures=1, skipped=1)", 1, "failed", 1),
                ("Ran 2 tests in 0.01s\nFAILED (skipped=1, unexpected successes=1)", 1, "failed", 1)):
            with self.subTest(status=status), contextlib.redirect_stdout(io.StringIO()):
                result = verify.execute([("python", [sys.executable, "-c", f"print({stdout!r}); raise SystemExit({code})"])],
                                        self.root, os.environ.copy())
                self.assertEqual(result[0]["status"], status)
                self.assertEqual(result[0]["counts"]["skipped"], skipped)

    def test_node_runner_reports_skipped_and_todo_checks_honestly(self):
        cases = (
            ("passed", "test('works', () => {});", "passed", 1, 0, 0),
            ("partial_skip", "test('works', () => {}); test.skip('unavailable', () => {});",
             "passed_with_skips", 2, 1, 0),
            ("partial_todo", "test('works', () => {}); test.todo('unfinished');",
             "passed_with_skips", 2, 0, 1),
            ("all_skipped", "test.skip('unavailable', () => {});", "failed", 1, 1, 0),
            ("all_todo", "test.todo('unfinished');", "failed", 1, 0, 1),
            ("failure", "test('broken', () => { throw new Error('expected failure'); });",
             "failed", 1, 0, 0),
        )
        for name, source, expected, total, skipped, todo in cases:
            with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                script = self.root / (name + ".mjs")
                script.write_text("import test from 'node:test';\n" + source, encoding="utf-8")
                result = verify.execute([("node", ["node", "--test", "--test-reporter=tap", str(script)])],
                                        self.root, os.environ.copy())[0]
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["counts"]["total"], total)
                self.assertEqual(result["counts"]["skipped"], skipped)
                self.assertEqual(result["counts"]["todo"], todo)

    def test_missing_or_empty_node_summary_fails_and_stops_later_checks(self):
        for name, output in (("missing", "no test summary"),
                             ("empty", "# tests 0\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0")):
            with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                plan = [("node", [sys.executable, "-c", f"print({output!r})"]),
                        ("later", [str(self.root / "must-not-execute")])]
                results = verify.execute(plan, self.root, os.environ.copy())
                self.assertEqual(results[0]["exit_code"], 0)
                self.assertEqual(results[0]["status"], "failed")
                self.assertIn("error", results[0])
                self.assertEqual(results[1]["status"], "not_run")

    def test_doctor_refuses_wrong_http_identity_dead_backend_and_live_port(self):
        identity = {"instance": "test", "ownerPid": os.getpid(), "backendPid": 123,
                    "endpoint": "ws://127.0.0.1:1234", "codexHome": str(self.root / "codex-home"),
                    "dataDir": str(self.root / "state")}
        state = {"side": {"runtime": {"verification": identity.copy(), "defaultCwd": str(self.root)}},
                 "daemon": {"connected": True, "version": "test-version"}}
        f = {"root": self.root, "home": self.root / "codex-home", "endpoint": identity["endpoint"],
             "api": lambda path: state, "web": SimpleNamespace(server_port=4321, runtime={"verification": identity}),
             "hub": SimpleNamespace(data_dir=self.root / "state"), "url": "http://127.0.0.1:4321",
             "process": SimpleNamespace(pid=123, poll=lambda: None)}
        self.assertEqual(doctor(f)["backendVersion"], "test-version")
        state["side"]["runtime"]["verification"]["instance"] = "someone-else"
        with self.assertRaises(RuntimeError): doctor(f)
        state["side"]["runtime"]["verification"] = identity.copy()
        f["process"].poll = lambda: 1
        with self.assertRaises(RuntimeError): doctor(f)
        f["process"].poll = lambda: None
        f["web"].server_port = 8764
        with self.assertRaises(RuntimeError): doctor(f)

    def test_browser_zero_exit_without_required_report_is_not_a_pass(self):
        f = {"url": "http://127.0.0.1:4321", "model": SimpleNamespace(request_count=0)}
        with patch("tools.smoke_test.doctor", return_value={}), patch("tools.smoke_test.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            result = browser_checks(f, self.root / "missing-report")
        self.assertEqual(result["result"], "failed")

    def test_fixture_refuses_live_port_before_starting_process(self):
        with patch("tools.smoke_test.subprocess.Popen") as process:
            with self.assertRaises(ValueError), fixture(8764):
                pass
        process.assert_not_called()

    def test_automatic_output_is_removed_and_explicit_output_survives(self):
        with verify.output_directory(None) as auto:
            (auto / "sample").write_text("temporary", encoding="utf-8")
        self.assertFalse(auto.exists())
        with verify.output_directory(self.root / "retained") as retained:
            (retained / "sample").write_text("retained", encoding="utf-8")
        self.assertTrue((retained / "sample").exists())

    def test_child_environment_cannot_select_live_or_partial_ui(self):
        original = {"MA4_URL": "http://127.0.0.1:8764", "MA4_PANEL_LAYOUT": "390-dark", "MA4_PANEL_DEFERRED": "1"}
        with patch.dict(os.environ, original):
            env = verify.check_environment(self.root, "http://127.0.0.1:12345")
        self.assertEqual(env["MA4_URL"], "http://127.0.0.1:12345")
        self.assertNotIn("MA4_PANEL_LAYOUT", env)
        self.assertNotIn("MA4_PANEL_DEFERRED", env)
        self.assertTrue(Path(env["TEMP"]).is_relative_to(self.root))

    def test_static_server_only_exposes_assets_and_closes(self):
        with verify.static_site() as url:
            port = int(url.rsplit(":", 1)[1])
            def request(method, path, headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                try:
                    conn.request(method, path, headers=headers or {})
                    response = conn.getresponse()
                    return response.status, response.read()
                finally:
                    conn.close()
            status, page = request("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(b"/app.js", page)
            for path in ("/api/state", "/api/events", "/config.windows.json", "/../README.md", "/%2e%2e/README.md"):
                self.assertEqual(request("GET", path)[0], 404, path)
            self.assertEqual(request("POST", "/api/send")[0], 501)
            self.assertEqual(request("GET", "/", {"Host": "external.example"})[0], 403)
        with self.assertRaises(OSError):
            request("GET", "/")


if __name__ == "__main__":
    unittest.main()
