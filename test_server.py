import http.client
import json
import threading
import unittest
from unittest.mock import Mock, patch

from server import Server, Handler
from appserver import RpcError


class FakeHub:
    seq = 0

    def state(self):
        return {"threads": [], "approvals": [], "daemon": {}, "seq": 0}

    def pin(self, tid, pinned):
        return {"pinned": pinned}

    def open_file(self, tid, path):
        return {"id": tid, "path": path}


class Stub:
    def snapshot(self):
        return {}


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), FakeHub(), Stub(), Stub(), [])
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        base = {"Host": "127.0.0.1:%d" % self.port}
        base.update(headers or {})
        conn.request(method, path, body=body, headers=base)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_windows_sse_disconnect_is_normal(self):
        handler = object.__new__(Handler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.server = Mock()
        handler.server.hub.events_after.return_value = []
        handler.wfile = Mock()
        handler.wfile.write.side_effect = ConnectionAbortedError(10053, "browser closed")
        handler.stream(0)
        self.assertTrue(handler.close_connection)
        handler.wfile.write.assert_called_once_with(b": keep-alive\n\n")


    def test_writer_conflict_is_actionable_and_other_rpc_errors_are_preserved(self):
        cases = [
            ("thread a already has an active writer", 409, "thread_in_use"),
            ("model unavailable", 502, None),
        ]
        for message, expected_status, code in cases:
            with self.subTest(message=message), patch.object(
                    self.server.hub, "send", create=True,
                    side_effect=RpcError({"code": -32600, "message": message})):
                status, body = self.request(
                    "POST", "/api/send", {"X-MA4-Request": "1"},
                    json.dumps({"id": "a", "text": "hello", "request_id": "one"}))
            data = json.loads(body)
            self.assertEqual(status, expected_status)
            self.assertEqual(data.get("code"), code)
            if code:
                self.assertIn("占用", data["error"])
                self.assertIn("等待释放后重试", data["error"])
                self.assertIn("在终端打开", data["error"])
            else:
                self.assertEqual(data["error"], "Codex：" + message)


    def test_page_and_state(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"MA4", body)
        status, body = self.request("GET", "/api/state")
        self.assertEqual(json.loads(body)["seq"], 0)

    def test_foreign_host_origin_and_cross_site_refused(self):
        self.assertEqual(self.request("GET", "/api/state", {"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", {"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_write_needs_local_header(self):
        body = json.dumps({"id": "a", "pinned": True})
        headers = {"Content-Type": "application/json"}
        self.assertEqual(self.request("POST", "/api/pin", headers, body)[0], 403)
        status, data = self.request("POST", "/api/pin", dict(headers, **{"X-MA4-Request": "1"}), body)
        self.assertEqual((status, json.loads(data)), (200, {"pinned": True}))

    def test_unknown_paths(self):
        self.assertEqual(self.request("GET", "/../config.json")[0], 404)
        self.assertEqual(self.request("POST", "/api/nope", {"X-MA4-Request": "1"}, "{}")[0], 404)

    def test_send_forwards_only_separate_skill_selection(self):
        body = {"id": "a", "text": "复制的 $godot-tech", "request_id": "req"}
        for skills in (None, [], [{"name": "godot-tech", "path": "/s/godot-tech/SKILL.md"}]):
            payload = dict(body, skills=skills) if skills is not None else body
            with self.subTest(skills=skills), patch.object(self.server.hub, "send", return_value={}, create=True) as send:
                status, _ = self.request("POST", "/api/send", {"X-MA4-Request": "1"}, json.dumps(payload))
                self.assertEqual(status, 200)
                send.assert_called_once_with("a", body["text"], "req", skills=skills)

    def test_service_activity_uses_the_same_local_only_boundary(self):
        activity = Mock()
        activity.snapshot.return_value = [{"key": "chat", "count": 0, "visitors": []}]
        with patch.object(self.server, "activity", activity):
            status, data = self.request("GET", "/api/side")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)["activity"], activity.snapshot.return_value)
            activity.snapshot.reset_mock()
            self.assertEqual(self.request("GET", "/api/side", {"Origin": "https://elsewhere.test"})[0], 403)
            activity.snapshot.assert_not_called()

    def test_file_open_requires_local_post_and_preserves_path(self):
        body = json.dumps({"id": "a", "path": "目录/a & b.html:12"})
        headers = {"X-MA4-Request": "1", "Content-Type": "application/json"}
        self.assertEqual(self.request("GET", "/api/file/open")[0], 404)
        self.assertEqual(self.request("POST", "/api/file/open", {}, body)[0], 403)
        self.assertEqual(self.request("POST", "/api/file/open", dict(headers, Origin="https://evil.example"), body)[0], 403)
        status, data = self.request("POST", "/api/file/open", headers, body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), json.loads(body))

    def test_goal_confirmation_is_an_explicit_local_post(self):
        body = {"task_id": "task", "draft_revision": 3, "name": "任务", "target": "目标、范围和验收", "budget": {"durationMinutes": 120}, "start": True}
        controller = Mock()
        controller.invoke.return_value = {"resumed": True}
        with patch.object(self.server.hub, "controllers", controller, create=True):
            self.assertEqual(self.request("POST", "/api/tasks/confirm", {}, json.dumps(body))[0], 403)
            controller.invoke.assert_not_called()
            status, response = self.request("POST", "/api/tasks/confirm", {"X-MA4-Request": "1"}, json.dumps(body))
            self.assertEqual((status, json.loads(response)), (200, {"resumed": True}))
            controller.invoke.assert_called_once_with("confirm", **body)


if __name__ == "__main__":
    unittest.main()
