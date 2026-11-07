"""Cheap named-runner checks; native execution remains a separate opt-in CLI."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import smoke_test
from tools import task_scenarios as scenarios


class ModelTests(unittest.TestCase):
    def test_script_emits_one_registered_tool_then_text(self):
        model = scenarios.ControlledTaskModel()
        instruction = model.worker_instruction()
        marker = model.arm("ma4_dispatch", {"instruction": instruction, "access": "read", "write_scope": []})
        payload = {"input": [{"role": "user", "content": [{"text": marker}]}],
                   "tools": [{"name": "ma4_dispatch"}]}
        item, gate = model.response(payload)
        self.assertEqual(item["type"], "function_call")
        self.assertIsNone(gate)
        self.assertEqual(json.loads(item["arguments"])["instruction"], instruction)
        self.assertEqual(model.response(payload)[0]["type"], "message")
        self.assertEqual(len(model.calls), 1)

    def test_arbitrary_tools_and_commands_refused(self):
        model = scenarios.ControlledTaskModel()
        for tool, args in [("exec_command", {"cmd": "bad"}), ("ma4_control", {"action": "finish"}),
                           ("ma4_dispatch", {"instruction": "arbitrary", "access": "read", "write_scope": []})]:
            with self.subTest(tool=tool), self.assertRaises(AssertionError):
                model.arm(tool, args)

    def test_held_worker_and_release_are_explicit(self):
        model = scenarios.ControlledTaskModel()
        instruction = model.worker_instruction(hold=True)
        item, gate = model.response({"input": [{"role": "user", "content": "本次执行任务：" + instruction}]})
        self.assertFalse(gate.is_set())
        self.assertIn("TASK-FLOW-REPORT", item["content"][0]["text"])
        model.release_all()
        self.assertTrue(gate.is_set())

    def test_default_smoke_response_unchanged(self):
        handler = smoke_test.MockModel.__new__(smoke_test.MockModel)
        handler.rfile = io.BytesIO(b"{}")
        handler.wfile = io.BytesIO()
        handler.headers = {"Content-Length": "2"}
        handler.server = SimpleNamespace(script=None, request_count=0, delay=0,
                                        request_started=Mock(), release_response=Mock(wait=lambda _: True))
        handler.send_response = handler.send_header = handler.end_headers = Mock()
        handler.do_POST()
        events = [json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines()
                  if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "response.completed")
        self.assertEqual(events[-1]["response"]["output"][0]["content"][0]["text"],
                         "本机模拟回复：Windows 共享会话连接成功。")
        self.assertEqual(sum(e["type"] == "response.output_text.delta" for e in events), 3)


class RunnerTests(unittest.TestCase):
    def test_list_starts_nothing(self):
        with patch.object(scenarios, "fixture") as fixture, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(scenarios.main(["list"]), 0)
        fixture.assert_not_called()
        self.assertIn("pause-resume", out.getvalue())
        self.assertIn("failure-cleanup", out.getvalue())

    def test_invalid_cli_fails_before_fixture(self):
        for argv in [["run", "exec(code)"], ["run", "all", "--scratch-root", str(scenarios.ROOT)],
                     ["run", "all", "--scratch-root", str(scenarios.ROOT / ".agent-tmp"), "--timeout", "nan"],
                     ["run", "all", "--url", "http://127.0.0.1:8764"]]:
            with (self.subTest(argv=argv), patch.object(scenarios, "fixture") as fixture,
                    contextlib.redirect_stderr(io.StringIO())):
                with self.assertRaises(SystemExit) as cm:
                    scenarios.main(argv)
                self.assertEqual(cm.exception.code, 2)
                fixture.assert_not_called()

    def test_environment_restored_even_on_failure(self):
        original = {key: os.environ.get(key) for key in ("TEMP", "TMP", "TMPDIR", "MA4_TEST_SCRATCH")}
        with self.assertRaises(RuntimeError):
            with scenarios.local_environment(scenarios.ROOT / ".agent-tmp" / "fake"):
                self.assertEqual(os.environ["TEMP"], str(scenarios.ROOT / ".agent-tmp" / "fake"))
                raise RuntimeError("expected")
        self.assertEqual({key: os.environ.get(key) for key in original}, original)

    def test_failed_journey_still_exits_fixture(self):
        closed = []
        f = {"model": SimpleNamespace(request_count=0), "process": SimpleNamespace(poll=lambda: 0),
             "web": SimpleNamespace(fileno=lambda: -1), "root": scenarios.ROOT / ".agent-tmp" / "absent-task-test"}
        @contextlib.contextmanager
        def fixture(**kwargs):
            try:
                yield f
            finally:
                closed.append(True)
        action = SimpleNamespace(identity={}, steps=[], create=lambda: None, record=lambda *a, **k: None)
        with patch.object(scenarios, "fixture", fixture), patch.object(scenarios, "TaskActions", return_value=action):
            result = scenarios.run_scenario("failure-cleanup", f["root"], 1)
        self.assertEqual(result["result"], "failed")
        self.assertIn("intentional failure", result["error"])
        self.assertEqual(closed, [True])
        self.assertTrue(all(result["cleanup"].values()))

    def test_failed_run_nonzero_and_stops_following_scenarios(self):
        scratch = Path(os.environ.get("MA4_TEST_SCRATCH", scenarios.ROOT / ".agent-tmp")) / "task-unit"
        with (patch.object(Path, "mkdir"), patch.object(scenarios, "run_scenario",
                return_value={"result": "failed", "error": "expected"}) as run,
                contextlib.redirect_stdout(io.StringIO()) as out):
            code = scenarios.main(["run", "confirmation", "handoff", "--scratch-root", str(scratch)])
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(json.loads(out.getvalue())["notRun"], ["handoff"])

    def test_fixture_startup_failure_closes_mock_socket_and_temp(self):
        parent = Path(os.environ.get("MA4_TEST_SCRATCH", scenarios.ROOT / ".agent-tmp"))
        parent.mkdir(parents=True, exist_ok=True)
        before = set(parent.iterdir())
        server = Mock(server_port=4321)
        with (patch.object(smoke_test, "ThreadingHTTPServer", return_value=server),
                patch.object(smoke_test.threading, "Thread"),
                patch.object(smoke_test, "find_codex", side_effect=ValueError("missing installed Codex")),
                patch.object(smoke_test.subprocess, "Popen") as process):
            with self.assertRaises(ValueError), smoke_test.fixture(model_script=scenarios.ControlledTaskModel()):
                pass
        server.shutdown.assert_called_once()
        server.server_close.assert_called_once()
        process.assert_not_called()
        self.assertEqual(set(parent.iterdir()), before)

    def test_owned_process_cleanup_has_bounded_terminate_and_kill(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("owned", 10), 0]
        smoke_test.stop_owned_process(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual([c.kwargs["timeout"] for c in process.wait.call_args_list], [10, 5])


if __name__ == "__main__":
    unittest.main()
