import tempfile
import time
import unittest

from appserver import RpcError
from hub import Hub, normalize_item, status_of


class FakeClient:
    def __init__(self, threads=None):
        self.closed = False
        self.info = {"userAgent": "fake"}
        self.threads = threads or []
        self.calls = []
        self.responses = []
        self.turns = {}

    def call(self, method, params, timeout=30):
        self.calls.append((method, params))
        if method == "thread/list":
            return {"data": self.threads}
        if method == "thread/turns/list":
            if params["threadId"] == "fresh":
                raise RpcError({"code": -32600, "message": "thread fresh is not materialized yet"})
            return {"data": self.turns.get(params["threadId"], []), "nextCursor": None}
        if method == "turn/start":
            return {"turn": {"id": "turn-new"}}
        if method == "thread/start":
            return {"thread": {"id": "fresh"}}
        if method == "skills/list":
            return {"data": [{"cwd": params["cwds"][0], "errors": [], "skills": [
                {"name": "vibehub", "path": "/s/vibehub/SKILL.md", "description": "terms", "enabled": True},
                {"name": "off", "path": "/s/off/SKILL.md", "description": "", "enabled": False}]}]}
        if method == "model/list":
            return {"data": [{"id": "gpt-a", "displayName": "A", "isDefault": True},
                             {"id": "gpt-b", "displayName": "B", "hidden": False}]}
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

    def test_skill_mentions_become_skill_inputs(self):
        self.client.threads = [thread("a")]
        self.hub.refresh()
        self.hub.send("a", "用 $vibehub 解释，$off 和 a$vibehub 不算，价格 $5 也不算", "req-s")
        start = [p for m, p in self.client.calls if m == "turn/start"][-1]
        self.assertEqual(start["input"][1:], [{"type": "skill", "name": "vibehub", "path": "/s/vibehub/SKILL.md"}])
        self.hub.send("a", "no skills here", "req-t")
        self.assertEqual(len([p for m, p in self.client.calls if m == "turn/start"][-1]["input"]), 1)
        self.assertEqual(sum(1 for m, _ in self.client.calls if m == "skills/list"), 1)  # cached

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
        self.hub.command("a", "model", "gpt-b")
        self.hub.send("a", "hi", "req-m")
        self.assertEqual([p for m, p in self.client.calls if m == "turn/start"][-1]["model"], "gpt-b")
        self.assertEqual(self.hub.open("a")["model"], "gpt-b")
        with self.assertRaises(ValueError):
            self.hub.command("a", "launch-missiles")

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


if __name__ == "__main__":
    unittest.main()
