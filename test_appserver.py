import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest

from appserver import AppServer, Disconnected, RpcError


def read_frame(conn, buffer):
    def take(n):
        nonlocal buffer
        while len(buffer) < n:
            chunk = conn.recv(65536)
            if not chunk:
                raise ConnectionError
            buffer += chunk
        out, buffer = buffer[:n], buffer[n:]
        return out
    b0, b1 = take(2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", take(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", take(8))[0]
    mask = take(4)
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(take(n)))
    return b0 & 0x0F, payload, buffer


def server_frame(opcode, payload, fin=True):
    n = len(payload)
    first = (0x80 if fin else 0) | opcode
    if n < 126:
        return struct.pack(">BB", first, n) + payload
    if n < 1 << 16:
        return struct.pack(">BBH", first, 126, n) + payload
    return struct.pack(">BBQ", first, 127, n) + payload


class FakeDaemon:
    """Unix-socket WebSocket peer that answers JSON-RPC calls with a script."""

    def __init__(self, handler):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "sock"
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(str(self.path))
        self.listener.listen(1)
        self.handler = handler
        self.conn = None
        self.received = []
        threading.Thread(target=self.serve, daemon=True).start()

    def send(self, obj, split=False):
        data = json.dumps(obj).encode()
        if split:
            half = len(data) // 2
            self.conn.sendall(server_frame(0x1, data[:half], fin=False) + server_frame(0x0, data[half:]))
        else:
            self.conn.sendall(server_frame(0x1, data))

    def serve(self):
        self.conn, _ = self.listener.accept()
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.conn.recv(4096)
        self.conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        buffer = head.split(b"\r\n\r\n", 1)[1]
        try:
            while True:
                opcode, payload, buffer = read_frame(self.conn, buffer)
                if opcode == 0xA:
                    self.received.append({"pong": payload.decode()})
                    continue
                message = json.loads(payload)
                self.received.append(message)
                self.handler(self, message)
        except (ConnectionError, OSError, ValueError):
            pass

    def close(self):
        if self.conn:
            self.conn.close()
        self.listener.close()
        self.dir.cleanup()


def default_handler(daemon, message):
    method, rid = message.get("method"), message.get("id")
    if method == "initialize":
        daemon.send({"id": rid, "result": {"userAgent": "fake/1"}})
    elif method == "echo":
        daemon.send({"id": rid, "result": message["params"]}, split=True)
    elif method == "boom":
        daemon.send({"id": rid, "error": {"code": -1, "message": "bad thing"}})
    elif method == "big":
        daemon.send({"id": rid, "result": {"text": "x" * 70000}})


class AppServerTest(unittest.TestCase):
    def setUp(self):
        self.daemon = FakeDaemon(default_handler)
        self.notes, self.requests, self.drops = [], [], []
        self.client = AppServer(self.daemon.path,
                                on_notification=lambda m, p: self.notes.append((m, p)),
                                on_request=lambda i, m, p: self.requests.append((i, m, p)),
                                on_disconnect=self.drops.append)

    def tearDown(self):
        self.client.close()
        self.daemon.close()

    def wait(self, predicate):
        deadline = time.time() + 3
        while not predicate() and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_initialize_then_initialized(self):
        self.assertEqual(self.client.info, {"userAgent": "fake/1"})
        self.wait(lambda: any(m.get("method") == "initialized" for m in self.daemon.received))

    def test_call_with_fragmented_reply_and_large_payload(self):
        self.assertEqual(self.client.call("echo", {"a": "中文"}), {"a": "中文"})
        self.assertEqual(len(self.client.call("big")["text"]), 70000)

    def test_error_reply_raises(self):
        with self.assertRaises(RpcError) as ctx:
            self.client.call("boom")
        self.assertIn("bad thing", str(ctx.exception))

    def test_notifications_requests_and_ping(self):
        self.daemon.send({"method": "thread/status/changed", "params": {"threadId": "t"}})
        self.daemon.send({"id": 7, "method": "item/fileChange/requestApproval", "params": {"threadId": "t"}})
        self.daemon.conn.sendall(server_frame(0x9, b"hi"))
        self.wait(lambda: self.notes and self.requests)
        self.assertEqual(self.notes[0][0], "thread/status/changed")
        self.assertEqual(self.requests[0][:2], (7, "item/fileChange/requestApproval"))
        self.wait(lambda: {"pong": "hi"} in self.daemon.received)
        self.client.respond(7, {"decision": "accept"})
        self.wait(lambda: any(m.get("id") == 7 and "result" in m for m in self.daemon.received))

    def test_disconnect_fails_pending_calls(self):
        result = {}

        def slow():
            try:
                self.client.call("never-answered", timeout=5)
            except Disconnected as exc:
                result["error"] = exc

        worker = threading.Thread(target=slow)
        worker.start()
        time.sleep(0.2)
        self.daemon.conn.shutdown(socket.SHUT_RDWR)
        worker.join(3)
        self.assertIn("error", result)
        self.wait(lambda: self.drops)
        with self.assertRaises(Disconnected):
            self.client.call("echo")


if __name__ == "__main__":
    unittest.main()
