import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from appserver import RpcError
from hub import Hub, describe, normalize_item, permissions, status_of
from controllers import HOST_INSTRUCTIONS, HOST_TOOL_SETTINGS
from os_adapters import linux as linux_adapter


class FakeClient:
    def __init__(self, threads=None):
        self.closed = False
        self.info = {"userAgent": "fake"}
        self.threads = threads or []
        self.calls = []
        self.responses = []
        self.turns = {}
        self.loaded = []
        self.metadata = {}

    def call(self, method, params, timeout=30):
        self.calls.append((method, params))
        if method == "thread/list":
            return {"data": self.threads}
        if method == "thread/loaded/list":
            return {"data": self.loaded}
        if method == "thread/read":
            return {"thread": self.metadata.get(params["threadId"])
                    or next((t for t in self.threads if t["id"] == params["threadId"]), None)}
        if method == "thread/turns/list":
            if params["threadId"] == "fresh":
                raise RpcError({"code": -32600, "message": "thread fresh is not materialized yet"})
            return {"data": self.turns.get(params["threadId"], []), "nextCursor": None}
        if method == "turn/start":
            return {"turn": {"id": "turn-new"}}
        if method == "thread/start":
            return {"thread": {"id": "fresh"}, "model": "gpt-a", "sandbox": {"type": "readOnly"},
                    "approvalPolicy": "on-request"}
        if method == "thread/resume":
            return {"model": "gpt-a", "reasoningEffort": "high", "sandbox": {"type": "dangerFullAccess"},
                    "approvalPolicy": "never"}
        if method == "skills/list":
            return {"data": [{"cwd": params["cwds"][0], "errors": [], "skills": [
                {"name": "vibehub", "path": "/s/vibehub/SKILL.md", "description": "terms", "enabled": True},
                {"name": "off", "path": "/s/off/SKILL.md", "description": "", "enabled": False}]}]}
        if method == "model/list":
            return {"data": [{"id": "gpt-a", "displayName": "A", "isDefault": True},
                             {"id": "gpt-b", "displayName": "B", "hidden": False,
                              "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}]}]}
        return {}

    def respond(self, rid, result):
        self.responses.append((rid, result))

    def close(self):
        self.closed = True


def thread(tid, status="idle", updated=100, **extra):
    return {"id": tid, "status": {"type": status} if isinstance(status, str) else status,
            "updatedAt": updated, "cwd": "/tmp", "name": tid, "preview": "", **extra}


class HubTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.hub = Hub(self.dir.name, "codex")
        self.client = FakeClient()
        self.hub.client = self.client

    def tearDown(self):
        self.dir.cleanup()

    def names(self):
        return {t["id"]: t for t in self.hub.thread_list()}

    def test_writer_conflict_can_retry_without_switching_threads(self):
        original_call = self.client.call
        writer_active = True

        def call(method, params, timeout=30):
            if method == "thread/resume" and writer_active:
                raise RpcError({"code": -32600,
                                "message": "thread a already has an active writer"})
            return original_call(method, params, timeout)

        with patch.object(self.client, "call", side_effect=call) as rpc:
            for _ in range(2):
                with self.assertRaisesRegex(RpcError, "active writer"):
                    self.hub.send("a", "retry me", "same-request")
                self.assertNotIn("a", self.hub.subscribed)
                self.assertNotIn("same-request", self.hub.sent)
            self.assertEqual([c.args[0] for c in rpc.call_args_list],
                             ["thread/resume", "thread/resume"])
            writer_active = False
            # No open(), refresh(), reconnect, or thread switch between attempts.
            result = self.hub.send("a", "retry me", "same-request")
            self.assertEqual(result, {"mode": "start", "turnId": "turn-new"})
            self.assertEqual(self.hub.send("a", "retry me", "same-request"), result)
            self.assertEqual(sum(m == "turn/start" for m, _ in self.client.calls), 1)


    def test_transient_empty_rollout_is_retried_but_other_errors_are_not(self):
        race = RpcError({"message": "rollout file is empty"})
        denied = RpcError({"message": "access denied"})
        params = {"threadId": "a"}
        with patch.object(self.client, "call", side_effect=[race, {"data": []}]) as call, patch("hub.time.sleep") as sleep:
            self.assertEqual(self.hub.read_turns(params), {"data": []})
            self.assertEqual(call.call_count, 2)
            sleep.assert_called_once_with(.05)
        with patch.object(self.client, "call", side_effect=denied) as call, patch("hub.time.sleep") as sleep:
            with self.assertRaises(RpcError):
                self.hub.read_turns(params)
            self.assertEqual(call.call_count, 1)
            sleep.assert_not_called()
        with patch.object(self.client, "call", side_effect=race) as call, patch("hub.time.sleep"):
            with self.assertRaises(RpcError):
                self.hub.read_turns(params)
            self.assertEqual(call.call_count, 4)


    def test_deadline_steer_never_starts_a_turn_when_the_old_turn_has_ended(self):
        self.hub.steer_only("a", "old-turn", "请收尾", "notice-1")
        self.assertEqual([m for m, p in self.client.calls], ["turn/steer"])
        self.assertEqual(self.client.calls[0][1]["expectedTurnId"], "old-turn")
        with patch.object(self.client, "call", side_effect=RpcError({"message": "no active turn"})):
            with self.assertRaises(RpcError): self.hub.steer_only("a", "old-turn", "请收尾", "notice-2")
        self.assertFalse(any(m == "turn/start" for m, p in self.client.calls))

    def test_open_file_resolves_references_without_a_shell_or_model_call(self):
        root = Path(self.dir.name)
        target = root / "报告 (1) & '文字'.md"
        target.write_text("example")
        plain = root / "README.md"
        plain.write_text("example")
        self.hub.threads["a"] = {"cwd": str(root)}
        with patch("hub.os_adapter", return_value=linux_adapter), patch("hub.subprocess.Popen") as launch:
            launch.return_value.wait.return_value = 0
            for ref, expected in [(str(target), target), (target.name, target),
                                  (str(target) + ":12:3", target), (target.as_uri() + "#L12", target),
                                  ("README.md:12", plain), ("README.md#L3-L9", plain),
                                  (".", root)]:
                with self.subTest(ref=ref):
                    self.assertEqual(self.hub.open_file("a", ref), {"opened": True})
                    self.assertEqual(launch.call_args.args[0], ["/usr/bin/xdg-open", str(expected)])
                    self.assertNotIn("shell", launch.call_args.kwargs)
            # Shell metacharacters are literal filename characters, not commands.
            literal = root / "$(touch SHOULD_NOT_EXIST).html"
            literal.write_text("example")
            self.hub.open_file("a", literal.name)
            self.assertEqual(launch.call_args.args[0][1], str(literal))
        self.assertEqual(self.client.calls, [])

    def test_open_file_rejects_missing_paths_remote_uris_and_launch_errors(self):
        root = Path(self.dir.name)
        self.hub.threads["a"] = {"cwd": str(root)}
        with patch("hub.os_adapter", return_value=linux_adapter), patch("hub.subprocess.Popen") as launch:
            for ref in ["missing.md", "", None, "x\nfile", "https://example.com", "javascript:alert(1)",
                        "file://remote/home/a", "//remote/a", "file:///a?query"]:
                with self.subTest(ref=ref), self.assertRaises(ValueError):
                    self.hub.open_file("a", ref)
            with self.assertRaises(ValueError):
                self.hub.open_file("unknown", str(root))
            shortcut = root / "run.desktop"
            shortcut.write_text("[Desktop Entry]")
            with self.assertRaises(ValueError):
                self.hub.open_file("a", str(shortcut))
            launch.assert_not_called()
            launch.return_value.wait.return_value = 3
            with self.assertRaisesRegex(ValueError, "默认应用"):
                self.hub.open_file("a", str(root))

    def test_status_mapping(self):
        self.assertEqual(status_of(thread("a", {"type": "active", "activeFlags": ["waitingOnApproval"]})), "approval")
        self.assertEqual(status_of(thread("a", {"type": "active", "activeFlags": ["waitingOnUserInput"]})), "input")
        self.assertEqual(status_of(thread("a", {"type": "active", "activeFlags": []})), "running")
        self.assertEqual(status_of(thread("a", "notLoaded")), "offline")
        self.assertEqual(status_of(thread("a", "systemError")), "error")

    def test_refresh_hides_subagents_and_first_sighting_is_quiet(self):
        self.client.threads = [thread("main"), thread("child", parentThreadId="main"), thread("tmp", ephemeral=True)]
        self.hub.refresh()
        self.assertEqual(list(self.names()), ["main"])
        self.assertFalse(self.names()["main"]["unread"])

    def test_later_activity_is_unread_until_opened(self):
        self.client.threads = [thread("a", updated=100)]
        self.hub.refresh()
        self.client.threads = [thread("a", updated=200)]
        self.hub.refresh()
        self.assertTrue(self.names()["a"]["unread"])
        self.hub.open("a")
        self.assertFalse(self.names()["a"]["unread"])
        # The seen mark survives a restart.
        again = Hub(self.dir.name, "codex")
        again.client = FakeClient([thread("a", updated=200)])
        again.refresh()
        self.assertFalse({t["id"]: t for t in again.thread_list()}["a"]["unread"])

    def test_running_thread_is_not_unread(self):
        self.client.threads = [thread("a", updated=100)]
        self.hub.refresh()
        self.client.threads = [thread("a", {"type": "active", "activeFlags": []}, updated=200)]
        self.hub.refresh()
        self.assertFalse(self.names()["a"]["unread"])

    def test_send_starts_or_steers_and_dedupes(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        first = self.hub.send("a", "hi", "req-1")
        self.assertEqual(first, {"mode": "start", "turnId": "turn-new"})
        self.assertEqual(self.hub.send("a", "hi", "req-1"), first)
        self.assertEqual(sum(1 for m, _ in self.client.calls if m == "turn/start"), 1)
        self.hub.on_notification("turn/started", {"threadId": "a", "turn": {"id": "turn-live"}})
        second = self.hub.send("a", "more", "req-2")
        self.assertEqual(second, {"mode": "steer", "turnId": "turn-live"})
        steer = [p for m, p in self.client.calls if m == "turn/steer"][0]
        self.assertEqual(steer["expectedTurnId"], "turn-live")
        with self.assertRaises(ValueError):
            self.hub.send("a", "   ", "req-3")

    def test_host_permissions_apply_on_resume_and_every_new_turn_only_to_current_host(self):
        tasks = {"tasks": [{"host": "host", "formerHosts": ["former"], "status": "paused",
                            "workers": {"reader": {"access": "read"}, "writer": {"access": "write"}}}]}
        with patch.object(self.hub.controllers, "snapshot", return_value=tasks):
            for tid in ("host", "reader", "writer", "former", "ordinary"):
                self.client.calls.clear()
                self.hub.send_raw(tid, "讨论", "first-" + tid)
                resume = next(p for m, p in self.client.calls if m == "thread/resume")
                start = next(p for m, p in self.client.calls if m == "turn/start")
                if tid == "host":
                    self.assertEqual(resume["sandbox"], "danger-full-access")
                    self.assertEqual(resume["approvalPolicy"], "never")
                    self.assertEqual(resume["developerInstructions"], HOST_INSTRUCTIONS)
                    self.assertFalse(resume["config"]["features.multi_agent"])
                    for k, v in HOST_TOOL_SETTINGS.items():
                        self.assertEqual(start[k], v)
                else:
                    for k in ("sandbox", "sandboxPolicy", "approvalPolicy", "developerInstructions", "config"):
                        self.assertNotIn(k, resume)
                        self.assertNotIn(k, start)
                # Already subscribed: later rounds still explicitly set host permissions.
                self.client.calls.clear()
                self.hub.send_raw(tid, "继续讨论", "second-" + tid)
                self.assertFalse(any(m == "thread/resume" for m, p in self.client.calls))
                start = next(p for m, p in self.client.calls if m == "turn/start")
                self.assertEqual(start.get("sandboxPolicy"), HOST_TOOL_SETTINGS["sandboxPolicy"] if tid == "host" else None)
        self.assertEqual(tasks["tasks"][0]["status"], "paused")

    def test_host_reconnect_refreshes_instructions_without_starting_a_turn(self):
        with patch.object(self.hub.controllers, "snapshot", return_value={"tasks": [{"host": "host"}]}):
            self.hub.subscribe("host")
            self.hub.on_disconnect("reconnect")
            self.hub.socket_path = Path(self.dir.name) / "fake.socket"
            self.hub.socket_path.touch()
            self.hub.connect_factory = lambda *args, **kwargs: self.client
            self.hub.try_connect()
        resumes = [p for m, p in self.client.calls if m == "thread/resume"]
        self.assertEqual(len(resumes), 2)
        self.assertTrue(all(p["developerInstructions"] == HOST_INSTRUCTIONS for p in resumes))
        self.assertFalse(any(m == "turn/start" for m, p in self.client.calls))

    def test_host_busy_message_only_steers_the_existing_turn(self):
        self.hub.subscribed.add("host")
        self.hub.live["host"] = {"turn": "live-turn"}
        with patch.object(self.hub.controllers, "snapshot", return_value={"tasks": [{"host": "host"}]}):
            result = self.hub.send_raw("host", "补充", "steer-host")
        self.assertEqual(result, {"mode": "steer", "turnId": "live-turn"})
        self.assertEqual([m for m, p in self.client.calls], ["turn/steer"])
        self.assertNotIn("sandboxPolicy", self.client.calls[0][1])

    def test_loaded_host_ignoring_resume_overrides_gets_explicit_settings_update(self):
        original = self.client.call
        def loaded(method, params, timeout=30):
            result = original(method, params, timeout)
            if method == "thread/resume":
                result.update(sandbox={"type": "readOnly"}, approvalPolicy="on-request")
            return result
        with patch.object(self.hub.controllers, "snapshot", return_value={"tasks": [{"host": "host"}]}), \
                patch.object(self.client, "call", side_effect=loaded):
            self.hub.subscribe("host")
        self.assertIn(("thread/settings/update", {"threadId": "host", **HOST_TOOL_SETTINGS}), self.client.calls)
        self.assertEqual(self.hub.live["host"]["settings"]["sandbox"], "dangerFullAccess")
        self.assertEqual(self.hub.live["host"]["settings"]["approval"], "never")
        self.assertFalse(any(m.startswith("turn/") for m, p in self.client.calls))

    def test_new_thread_passes_explicit_host_settings_without_changing_read_workers(self):
        for sandbox, approval in (("danger-full-access", "never"), ("read-only", None), (None, None)):
            self.client.calls.clear()
            self.hub.new_thread(self.dir.name, sandbox=sandbox, approval_policy=approval)
            start = next(p for m, p in self.client.calls if m == "thread/start")
            self.assertEqual(start.get("sandbox"), sandbox)
            self.assertEqual(start.get("approvalPolicy"), approval)
            self.assertFalse(any(m == "thread/settings/update" for m, p in self.client.calls))

    def test_in_progress_turn_found_from_history(self):
        self.client.turns["a"] = [{"id": "t9", "status": "inProgress"}]
        self.assertEqual(self.hub.current_turn("a"), "t9")
        self.client.turns["b"] = [{"id": "t1", "status": "completed"}]
        self.assertIsNone(self.hub.current_turn("b"))

    def test_fresh_thread_has_no_turns(self):
        self.assertIsNone(self.hub.current_turn("fresh"))
        self.assertEqual(self.hub.history("fresh"), {"turns": [], "older": None})

    def test_approval_lifecycle(self):
        self.hub.on_request(5, "item/commandExecution/requestApproval",
                            {"threadId": "a", "command": "rm -rf build", "cwd": "/tmp"})
        [entry] = self.hub.approval_list()
        self.assertEqual((entry["kind"], entry["command"]), ("command", "rm -rf build"))
        self.hub.decide(entry["key"], "decline")
        self.assertEqual(self.client.responses, [(5, {"decision": "decline"})])
        self.assertEqual(self.hub.approval_list(), [])
        with self.assertRaises(ValueError):
            self.hub.decide(entry["key"], "accept")

    def test_legacy_approval_and_resolved_elsewhere(self):
        self.hub.on_request(6, "execCommandApproval", {"conversationId": "a", "command": ["ls", "-l"]})
        [entry] = self.hub.approval_list()
        self.assertEqual((entry["threadId"], entry["command"]), ("a", "ls -l"))
        self.hub.decide(entry["key"], "acceptForSession")
        self.assertEqual(self.client.responses[-1], (6, {"decision": "approved_for_session"}))
        self.hub.on_request(8, "item/fileChange/requestApproval", {"threadId": "a"})
        self.hub.on_notification("serverRequest/resolved", {"requestId": 8})
        self.assertEqual(self.hub.approval_list(), [])

    def test_unknown_request_cannot_be_decided_here(self):
        self.hub.on_request(9, "item/tool/requestUserInput", {"threadId": "a"})
        [entry] = self.hub.approval_list()
        with self.assertRaises(ValueError):
            self.hub.decide(entry["key"], "accept")

    def test_events_and_resync(self):
        start = self.hub.seq
        self.hub.emit("x")
        events = self.hub.events_after(start, timeout=0.1)
        self.assertEqual([e["kind"] for _, e in events], ["x"])
        for _ in range(600):
            self.hub.emit("y")
        self.assertIsNone(self.hub.events_after(start, timeout=0.1))
        began = time.time()
        self.assertEqual(self.hub.events_after(self.hub.seq, timeout=0.2), [])
        self.assertGreaterEqual(time.time() - began, 0.15)

    def test_new_thread_requires_existing_dir(self):
        with self.assertRaises(ValueError):
            self.hub.new_thread("/definitely/not/here")
        self.assertEqual(self.hub.new_thread(self.dir.name), {"threadId": "fresh"})
        self.assertEqual(self.hub.live["fresh"]["settings"]["sandbox"], "readOnly")

    def test_empty_new_thread_survives_refresh_and_can_rename_and_send(self):
        self.hub.new_thread(self.dir.name)
        for _ in range(3):
            self.hub.refresh()  # neither stored nor loaded listing has caught up
        self.assertEqual(self.names()["fresh"]["cwd"], self.dir.name)
        self.assertEqual(self.hub.open("fresh")["thread"]["id"], "fresh")
        self.hub.command("fresh", "rename", "新会话")
        self.hub.refresh()
        self.assertEqual(self.names()["fresh"]["name"], "新会话")
        self.hub.send("fresh", "hello", "fresh-send")
        self.assertEqual([p["threadId"] for m, p in self.client.calls if m == "turn/start"], ["fresh"])

    def test_refresh_recovers_loaded_empty_thread_without_reading_history(self):
        self.client.loaded = ["fresh", "child", "ephemeral"]
        self.client.metadata = {"fresh": thread("fresh", name=""),
                                "child": thread("child", parentThreadId="fresh"),
                                "ephemeral": thread("ephemeral", ephemeral=True)}
        self.hub.refresh()
        self.hub.refresh()
        self.assertEqual(set(self.names()), {"fresh"})
        reads = [p for m, p in self.client.calls if m == "thread/read"]
        self.assertEqual(len(reads), 3)  # repeated refresh reuses metadata
        self.assertTrue(all(p["includeTurns"] is False for p in reads))
        self.assertFalse(any(m in ("thread/turns/list", "turn/start") for m, p in self.client.calls))

    def test_creation_during_list_refresh_is_not_overwritten(self):
        call = self.client.call
        def create_during_list(method, params, timeout=30):
            result = call(method, params, timeout)
            if method == "thread/list":
                self.hub.new_thread(self.dir.name)
            return result
        with patch.object(self.client, "call", side_effect=create_during_list):
            self.hub.refresh()
        self.assertIn("fresh", self.names())

    def test_reconnected_empty_thread_defers_subscription_until_first_turn_persists(self):
        self.client.loaded = ["fresh"]
        self.client.metadata["fresh"] = thread("fresh")
        call = self.client.call
        materialized = False
        def resume_after_first_turn(method, params, timeout=30):
            if method == "thread/resume" and not materialized:
                raise RpcError({"message": "no rollout found for thread id fresh"})
            return call(method, params, timeout)
        with patch.object(self.client, "call", side_effect=resume_after_first_turn):
            self.hub.refresh()
            self.assertEqual(self.hub.open("fresh")["thread"]["id"], "fresh")
            self.assertNotIn("fresh", self.hub.subscribed)
            result = self.hub.send("fresh", "first real input", "first")
            self.assertEqual(result["turnId"], "turn-new")
            self.assertIn("fresh", self.hub.pending_subscriptions)
            self.hub.refresh()  # rollout still absent: no duplicate turn
            materialized = True
            self.hub.refresh()  # may already be idle; still subscribe and catch up
        self.assertIn("fresh", self.hub.subscribed)
        self.assertNotIn("fresh", self.hub.pending_subscriptions)
        self.assertEqual(sum(m == "turn/start" for m, p in self.client.calls), 1)
        self.assertEqual(sum(e["kind"] == "history" for _, e in self.hub.events), 1)
        self.assertEqual(self.hub.send("fresh", "first real input", "first"), result)

    def test_missing_rollout_does_not_allow_sending_to_an_unloaded_thread(self):
        self.client.metadata["gone"] = thread("gone", "notLoaded")
        call = self.client.call
        def no_rollout(method, params, timeout=30):
            if method == "thread/resume":
                raise RpcError({"message": "no rollout found for thread id gone"})
            return call(method, params, timeout)
        with patch.object(self.client, "call", side_effect=no_rollout):
            with self.assertRaises(RpcError):
                self.hub.send("gone", "hello", "gone-send")
        self.assertFalse(any(m == "turn/start" for m, p in self.client.calls))

    def test_open_older_thread_stays_addressable_after_refresh(self):
        self.client.metadata["old"] = thread("old", "notLoaded")
        opened = self.hub.open("old")
        self.assertEqual(opened["thread"]["id"], "old")
        self.hub.refresh()
        self.assertIn("old", self.names())

    def test_loaded_thread_status_and_external_name_updates_survive_refresh(self):
        self.client.loaded = ["fresh"]
        self.client.metadata["fresh"] = thread("fresh")
        self.hub.refresh()
        self.hub.on_notification("thread/status/changed", {"threadId": "fresh", "status": {"type": "active"}})
        self.hub.subscribed.add("fresh")
        self.hub.refresh()
        self.assertEqual(self.names()["fresh"]["status"], "running")
        self.client.metadata["fresh"] = thread("fresh", name="外部改名")
        self.hub.on_notification("thread/name/updated", {"threadId": "fresh"})
        self.hub.refresh()
        self.assertEqual(self.names()["fresh"]["name"], "外部改名")

    def test_archive_or_delete_during_refresh_cannot_resurrect_cached_thread(self):
        for event in ("thread/archived", "thread/deleted"):
            with self.subTest(event=event):
                self.hub.removed_threads.clear()
                self.hub.new_thread(self.dir.name)
                self.client.loaded = ["fresh"]
                self.client.threads = [thread("fresh")]
                call = self.client.call
                def remove_during_list(method, params, timeout=30):
                    result = call(method, params, timeout)
                    if method == "thread/list":
                        self.hub.on_notification(event, {"threadId": "fresh"})
                    return result
                with patch.object(self.client, "call", side_effect=remove_during_list):
                    self.hub.refresh()
                self.hub.refresh()  # even a stale loaded/list response cannot restore it
                self.assertNotIn("fresh", self.names())
                self.assertNotIn("fresh", self.hub.managed_metadata)
                self.hub.on_notification("thread/unarchived", {"threadId": "fresh"})
                self.hub.refresh()
                self.assertIn("fresh", self.names())

    def test_skill_names_in_text_never_become_attachments(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        message = "用 $vibehub 解释，@vibehub 和 $off 原样发送，价格 $5 也不变"
        self.hub.send("a", message, "req-s")
        start = [p for m, p in self.client.calls if m == "turn/start"][-1]
        self.assertEqual(start["input"], [{"type": "text", "text": message, "text_elements": []}])
        self.assertFalse(any(m == "skills/list" for m, _ in self.client.calls))

    def test_selected_skill_is_attached_once_without_text_trigger_and_not_inherited(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        choice = {"name": "vibehub", "path": "/s/vibehub/SKILL.md"}
        self.hub.send("a", "解释这个概念", "req-s", skills=[choice, choice])
        start = [p for m, p in self.client.calls if m == "turn/start"][-1]
        self.assertEqual(start["input"][1:], [{"type": "skill", "name": "vibehub", "path": "/s/vibehub/SKILL.md"}])
        self.hub.send("a", "文字 $vibehub", "req-t")
        self.assertEqual(len([p for m, p in self.client.calls if m == "turn/start"][-1]["input"]), 1)
        self.assertEqual(sum(1 for m, _ in self.client.calls if m == "skills/list"), 1)  # cached

    def test_invalid_skill_attachments_never_send_a_turn(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        choices = ["$vibehub", {}, [None], [{"name": "vibehub"}],
                   [{"name": "vibehub", "path": "/arbitrary/SKILL.md"}],
                   [{"name": "unknown", "path": "/s/vibehub/SKILL.md"}],
                   [{"name": "off", "path": "/s/off/SKILL.md"}],
                   [{"name": "vibehub", "path": "/s/vibehub/SKILL.md", "type": "skill"}],
                   [{"name": "vibehub", "path": "/s/vibehub/SKILL.md"}] * 21]
        for index, selection in enumerate(choices):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.hub.send("a", "不应该发出", f"bad-{index}", skills=selection)
        self.assertFalse(any(m in ("turn/start", "turn/steer") for m, _ in self.client.calls))

    def test_new_thread_first_text_does_not_attach_skills(self):
        self.hub.new_thread(self.dir.name, "先使用 $vibehub")
        sent = [p for m, p in self.client.calls if m == "turn/start"][-1]
        self.assertEqual(len(sent["input"]), 1)
        self.assertEqual(sent["input"][0]["text"], "先使用 $vibehub")

    def controller_with_skill_context(self):
        c = self.hub.controllers
        created = c.do_create(self.dir.name, "Skill 隔离", target="目标中曾提到 $vibehub")
        t = c.tasks[created["taskId"]]
        c.do_confirm(t["id"], t["draftRevision"], t["name"], t["draft"]["target"], t["budget"], False)
        t["idea"] = "旧想法包含 $vibehub"
        return c, t

    def test_controller_context_does_not_attach_skills_to_start_or_steer(self):
        c, t = self.controller_with_skill_context()
        c.stage_draft(t, "草案也包含 $vibehub", "controller")
        t["handoffPending"] = "交接说明中提到 $vibehub"
        for mode in ("start", "steer"):
            with self.subTest(mode=mode):
                if mode == "steer":
                    self.hub.on_notification("turn/started", {"threadId": t["host"], "turn": {"id": "live"}})
                c.do_send(t["host"], "复制的模板：先用 $vibehub", "plain-" + mode)
                sent = [p for m, p in self.client.calls if m == "turn/" + mode][-1]
                self.assertEqual(len(sent["input"]), 1)
                self.assertIn("$vibehub", sent["input"][0]["text"])
                self.assertTrue(sent["input"][0]["text"].endswith("复制的模板：先用 $vibehub"))
                self.assertNotIn("@vibehub", normalize_item({"type": "userMessage", "content": sent["input"]})["text"])
        self.assertFalse(any(m == "skills/list" for m, _ in self.client.calls))

    def test_controller_user_can_still_explicitly_invoke_skills_and_next_message_is_plain(self):
        c, t = self.controller_with_skill_context()
        for mode in ("start", "steer"):
            with self.subTest(mode=mode):
                if mode == "steer":
                    self.hub.on_notification("turn/started", {"threadId": t["host"], "turn": {"id": "live"}})
                c.do_send(t["host"], "请说明这个术语", "explicit-" + mode,
                          skills=[{"name": "vibehub", "path": "/s/vibehub/SKILL.md"}])
                sent = [p for m, p in self.client.calls if m == "turn/" + mode][-1]
                self.assertEqual(sent["input"][1:], [{"type": "skill", "name": "vibehub", "path": "/s/vibehub/SKILL.md"}])
                normalized = normalize_item({"type": "userMessage", "content": sent["input"]})
                self.assertTrue(normalized["text"].endswith("请说明这个术语"))
                self.assertEqual(normalized["attachments"], sent["input"][1:])
        c.do_send(t["host"], "下一条普通问题", "plain-after-skill")
        self.assertEqual(len([p for m, p in self.client.calls if m == "turn/steer"][-1]["input"]), 1)

    def test_controller_automatic_messages_and_reports_never_attach_skills(self):
        c, t = self.controller_with_skill_context()
        for source in ("automatic", "worker_report"):
            with self.subTest(source=source):
                c.send_host(t, "说明或报告中提到了 $vibehub", source=source,
                            skills=[{"name": "vibehub", "path": "/s/vibehub/SKILL.md"}])
                sent = [p for m, p in self.client.calls if m == "turn/start"][-1]
                self.assertEqual(len(sent["input"]), 1)
                self.assertIn("说明或报告中提到了 $vibehub", sent["input"][0]["text"])
        self.assertFalse(any(m == "skills/list" for m, _ in self.client.calls))

    def test_controller_invalid_selection_does_not_create_uncertain_send(self):
        c, t = self.controller_with_skill_context()
        status = t["status"]
        with self.assertRaises(ValueError):
            c.do_send(t["host"], "讨论", "invalid-skill", skills=[{"name": "off", "path": "/s/off/SKILL.md"}])
        self.assertFalse(t.get("outbox"))
        self.assertEqual(t["status"], status)
        self.assertFalse(any(m in ("turn/start", "turn/steer") for m, _ in self.client.calls))

    def test_controller_initial_idea_is_text_only(self):
        self.hub.controllers.do_create(self.dir.name, "开始讨论", idea="用 $vibehub 解释术语")
        sent = [p for m, p in self.client.calls if m == "turn/start"][-1]
        self.assertEqual(len(sent["input"]), 1)
        self.assertTrue(sent["input"][0]["text"].endswith("用 $vibehub 解释术语"))

    def test_worker_assignment_and_paths_never_generate_skill_attachments(self):
        c, t = self.controller_with_skill_context()
        t["status"] = "running"
        self.hub.threads["worker"] = self.hub.summarize(thread("worker", cwd=self.dir.name))
        with patch.object(self.hub, "new_thread", return_value={"threadId": "worker"}):
            for index, instruction in enumerate(("检查现有文件", "用 $vibehub 解释术语")):
                with self.subTest(instruction=instruction):
                    result = c.dispatch(t, instruction, session_id="worker" if index else None,
                                        write_scope=["$vibehub/reference.md"])
                    worker = t["workers"][result["session_id"]]
                    c.launch(t, "worker", worker)
                    sent = [p for m, p in self.client.calls if m == "turn/start"][-1]
                    self.assertIn("$vibehub/reference.md", sent["input"][0]["text"])
                    self.assertEqual(len(sent["input"]), 1)
                    self.assertIn(instruction, sent["input"][0]["text"])
                    worker["state"] = "idle"

    def test_commands(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        self.hub.command("a", "rename", " 新名字 ")
        self.assertIn(("thread/name/set", {"threadId": "a", "name": "新名字"}), self.client.calls)
        self.hub.command("a", "compact")
        self.assertIn(("thread/compact/start", {"threadId": "a"}), self.client.calls)
        self.hub.command("a", "review", "main")
        review = [p for m, p in self.client.calls if m == "review/start"][-1]
        self.assertEqual(review["target"], {"type": "baseBranch", "branch": "main"})
        self.hub.command("a", "review")
        self.assertEqual([p for m, p in self.client.calls if m == "review/start"][-1]["target"],
                         {"type": "uncommittedChanges"})
        with self.assertRaises(ValueError):
            self.hub.command("a", "model", "gpt-zzz")
        with self.assertRaises(ValueError):
            self.hub.command("a", "model", "gpt-b medium")
        self.hub.command("a", "model", "gpt-b high")
        self.hub.send("a", "hi", "req-m")
        start = [p for m, p in self.client.calls if m == "turn/start"][-1]
        self.assertEqual((start["model"], start["effort"]), ("gpt-b", "high"))
        self.assertEqual(self.hub.open("a")["override"], {"model": "gpt-b", "effort": "high"})
        with self.assertRaises(ValueError):
            self.hub.command("a", "launch-missiles")

    def test_model_and_effort_shown_and_live_settings_win(self):
        self.client.threads = [thread("a", model="gpt-a", reasoningEffort="medium", gitInfo={"branch": "main"})]
        self.hub.refresh()
        row = self.names()["a"]
        self.assertEqual((row["model"], row["effort"], row["branch"]), ("gpt-a", "medium", "main"))
        self.hub.on_notification("thread/settings/updated",
                                 {"threadId": "a", "threadSettings": {"model": "gpt-b", "effort": "high"}})
        row = self.names()["a"]
        self.assertEqual((row["model"], row["effort"]), ("gpt-b", "high"))
        self.hub.on_notification("thread/status/changed", {"threadId": "a", "status": {"type": "idle"}})
        self.assertEqual(self.names()["a"]["branch"], "main")

    def test_permissions_from_resume(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        self.hub.subscribe("a")
        row = self.names()["a"]
        self.assertEqual((row["sandbox"], row["approval"], row["effort"]), ("dangerFullAccess", "never", "high"))
        self.assertEqual(permissions("readOnly", {"granular": {}}), {"sandbox": "readOnly", "approval": "granular"})

    def test_run_tracks_start_and_activity(self):
        self.client.threads = [thread("a", {"type": "active", "activeFlags": []})]
        self.hub.subscribed.add("a")
        self.hub.refresh()
        self.hub.on_notification("turn/started", {"threadId": "a", "turn": {"id": "t1", "startedAt": 1000}})
        self.hub.on_notification("item/started", {"threadId": "a", "turnId": "t1",
                                                  "item": {"type": "commandExecution", "id": "i1", "command": "npm test"}})
        run = self.names()["a"]["run"]
        self.assertEqual((run["startedAt"], run["activity"]), (1000, "执行 npm test"))
        self.hub.on_notification("item/completed", {"threadId": "a", "turnId": "t1",
                                                    "item": {"type": "commandExecution", "id": "i1"}})
        self.assertIsNone(self.names()["a"]["run"]["activity"])
        self.hub.on_notification("turn/completed", {"threadId": "a", "turn": {"id": "t1", "durationMs": 5000}})
        self.assertIsNone(self.names()["a"]["run"])
        done = [e for _, e in self.hub.events if e["kind"] == "turn" and e["state"] != "started"][-1]
        self.assertEqual(done["durationMs"], 5000)

    def test_threads_running_elsewhere_are_followed(self):
        self.client.turns["a"] = [{"id": "t7", "status": "inProgress", "startedAt": 900}]
        self.client.threads = [thread("a", {"type": "active", "activeFlags": []}), thread("b")]
        self.hub.refresh()
        resumed = [p["threadId"] for m, p in self.client.calls if m == "thread/resume"]
        self.assertEqual(resumed, ["a"])
        self.assertEqual(self.names()["a"]["run"]["startedAt"], 900)

    def test_describe(self):
        self.assertEqual(describe({"type": "fileChange", "changes": [{"path": "/x/a.py"}, {"path": "/x/b.py"}]}), "修改 a.py、b.py")
        self.assertEqual(describe({"type": "webSearch", "query": "codex"}), "搜索 codex")
        self.assertIsNone(describe({"type": "userMessage"}))

    def test_busy_thread_refuses_compact(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        self.hub.on_notification("turn/started", {"threadId": "a", "turn": {"id": "t1"}})
        with self.assertRaises(ValueError):
            self.hub.command("a", "compact")

    def test_normalize_items(self):
        user = normalize_item({"type": "userMessage", "id": "1",
                               "content": [{"type": "text", "text": "hi"}, {"type": "localImage", "path": "/x.png"}]})
        self.assertEqual(user["text"], "hi\n[图片]")
        command = normalize_item({"type": "commandExecution", "id": "2", "command": "ls",
                                  "aggregatedOutput": "y" * 10000, "exitCode": 0, "status": "completed"})
        self.assertLess(len(command["output"]), 4100)
        self.assertEqual(normalize_item({"type": "somethingNew", "id": "3"}), {"id": "3", "type": "somethingNew"})

    def test_skill_attachments_are_separate_from_user_words(self):
        content = [{"type": "text", "text": "解释 @godot-tech 和 $godot-tech"},
                   {"type": "skill", "name": "godot-tech", "path": "/skills/godot-tech/SKILL.md"},
                   {"type": "mention", "name": "README", "path": "/project/README.md"}]
        normalized = normalize_item({"type": "userMessage", "content": content})
        self.assertEqual(normalized["text"], content[0]["text"])
        self.assertEqual(normalized["attachments"], content[1:])

    def test_dynamic_tool_details_keep_failures_and_omit_image_bytes(self):
        item = normalize_item({"type": "dynamicToolCall", "id": "tool-1", "tool": "ma4_dispatch",
            "status": "completed", "success": False,
            "arguments": {"instruction": "读取成果 <result>", "write_scope": ["/bad/path"]},
            "contentItems": [{"type": "inputText", "text": '{"error":"必须是项目相对路径"}'},
                             {"type": "inputImage", "imageUrl": "data:image/png;base64," + "x" * 100000}]})
        self.assertIn("读取成果 <result>", item["arguments"])
        self.assertIn("必须是项目相对路径", item["output"])
        self.assertFalse(item["success"])
        self.assertNotIn("base64", item["output"])
        self.assertLess(len(item["output"]), 200)

    def test_dynamic_tool_large_arguments_are_bounded(self):
        item = normalize_item({"type": "dynamicToolCall", "id": "tool-2", "arguments": {"instruction": "a" * 100000}})
        self.assertLess(len(item["arguments"]), 20100)
        self.assertIn("省略", item["arguments"])
        self.assertIsNone(item["output"])


if __name__ == "__main__":
    unittest.main()
