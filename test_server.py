import http.client
import json
import threading
import unittest

from server import Server


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

    def test_unknown_paths(self):
        self.assertEqual(self.request("GET", "/../config.json")[0], 404)
        self.assertEqual(self.request("POST", "/api/nope", {"X-MA4-Request": "1"}, "{}")[0], 404)


if __name__ == "__main__":
    unittest.main()
