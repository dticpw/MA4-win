import socket
import threading
import unittest
import urllib.error
from unittest.mock import Mock, patch

from health import HealthPoller, INTERVAL, TCP_TIMEOUT, probe, probe_tcp


class HealthTest(unittest.TestCase):
    def test_tcp_connects_then_closes_without_sending_bytes(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(3)
            received = []
            def accept():
                with listener.accept()[0] as connection:
                    connection.settimeout(3)
                    received.append(connection.recv(1))
            worker = threading.Thread(target=accept)
            worker.start()
            result = probe_tcp("127.0.0.1", listener.getsockname()[1])
            worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(received, [b""])
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["ms"], 0)

    def test_tcp_short_timeout_and_fixed_errors(self):
        for error in (TimeoutError("private details"), ConnectionRefusedError("private details")):
            with self.subTest(error=type(error).__name__), patch("health.socket.create_connection", side_effect=error) as connect:
                result = probe_tcp("192.0.2.1", 22)
                connect.assert_called_once_with(("192.0.2.1", 22), timeout=3)
                self.assertFalse(result["ok"])
                self.assertIsNone(result["ms"])
                self.assertNotIn("private", result["error"])
        self.assertEqual(TCP_TIMEOUT, 3)

    def test_mixed_checks_keep_legacy_http_and_explicit_types(self):
        checks = [{"name": "VPS", "type": "tcp", "host": "192.0.2.1", "port": 22},
                  {"name": "site", "url": "https://example.test"}]
        http = Mock(return_value={"ok": True, "code": 200, "ms": 12})
        tcp = Mock(side_effect=TimeoutError())
        poller = HealthPoller(checks, check=http, tcp_check=tcp, start=False)
        self.assertEqual([r["type"] for r in poller.snapshot()], ["tcp", "http"])
        with patch("health.time.time", return_value=1000):
            poller.tick()
            rows = poller.snapshot()
        tcp.assert_called_once_with("192.0.2.1", 22)
        http.assert_called_once_with("https://example.test")
        self.assertFalse(rows[0]["ok"])
        self.assertTrue(rows[1]["ok"])
        self.assertEqual(rows[0]["at"], 1000)
        self.assertNotIn("url", rows[0])
        with patch("health.time.time", return_value=1616):
            self.assertTrue(all(row["stale"] for row in poller.snapshot()))

    def test_existing_health_loop_waits_300_seconds(self):
        poller = HealthPoller([], start=False)
        poller.stop = Mock()
        poller.stop.is_set.side_effect = [False, True]
        poller.loop()
        self.assertEqual(INTERVAL, 300)
        poller.stop.wait.assert_called_once_with(300)

    def test_existing_http_success_http_failure_and_network_failure(self):
        with patch("health.urllib.request.urlopen") as fetch:
            fetch.return_value.__enter__.return_value.status = 200
            self.assertTrue(probe("https://example.test")["ok"])
            fetch.side_effect = urllib.error.HTTPError("https://example.test", 503, "offline", {}, None)
            self.assertEqual(probe("https://example.test")["code"], 503)
            fetch.side_effect = urllib.error.URLError("offline")
            self.assertFalse(probe("https://example.test")["ok"])


if __name__ == "__main__":
    unittest.main()
