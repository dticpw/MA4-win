import http.client
import json
import threading
import unittest
from unittest.mock import Mock, patch

from appserver import RpcError

from server import Handler, Server


class FakeHub:
    seq = 0

    def state(self):
        return {"threads": [], "approvals": [], "daemon": {}, "seq": 0}

    def pin(self, tid, pinned):
        return {"pinned": pinned}


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

    def test_unknown_paths(self):
        self.assertEqual(self.request("GET", "/../config.json")[0], 404)
        self.assertEqual(self.request("POST", "/api/nope", {"X-MA4-Request": "1"}, "{}")[0], 404)


if __name__ == "__main__":
    unittest.main()
