"""JSON-RPC client for the shared Codex app-server daemon.

The shared server uses loopback TCP on Windows or a Unix socket on Linux,
with WebSocket text frames carrying JSON-RPC. This module uses only the standard library: a small WebSocket
client, a reader thread, and request/response matching.
"""
import base64
import hashlib
import itertools
import json
import os
from pathlib import Path
import socket
import struct
import threading
from urllib.parse import urlsplit

DEFAULT_SOCKET = Path.home() / ".codex/app-server-control/app-server-control.sock"
DEFAULT_ENDPOINT = "ws://127.0.0.1:8765" if os.name == "nt" else DEFAULT_SOCKET


def tcp_address(endpoint):
    """Validate a loopback-only WebSocket URL, without proxy or DNS lookup."""
    u = urlsplit(str(endpoint))
    if (u.scheme != "ws" or u.hostname not in ("127.0.0.1", "localhost", "::1")
            or not u.port or u.username or u.password or u.query or u.fragment
            or u.path not in ("", "/")):
        raise ValueError("后台地址必须是本机 ws://127.0.0.1:端口（或 localhost / [::1]）")
    return ("127.0.0.1" if u.hostname == "localhost" else u.hostname, u.port)


class RpcError(Exception):
    def __init__(self, error):
        self.code = error.get("code")
        super().__init__(error.get("message") or str(error))


class Disconnected(Exception):
    pass


class WebSocket:
    """Minimal WebSocket client over local TCP or a Unix socket (text only)."""

    def __init__(self, path, timeout=10):
        endpoint = str(path)
        if endpoint.startswith("ws://"):
            host, port = tcp_address(endpoint)
            self.sock = socket.create_connection((host, port), timeout=timeout)
            authority = ("[" + host + "]" if ":" in host else host) + ":" + str(port)
        else:
            if "://" in endpoint and not endpoint.startswith("unix://"):
                raise ValueError("只支持本机 ws:// 或 unix:// 控制端点")
            if not hasattr(socket, "AF_UNIX"):
                raise OSError("当前 Python 不支持 Unix socket，请使用本机 TCP 后台")
            if endpoint.startswith("unix://"):
                endpoint = endpoint[7:] or str(DEFAULT_SOCKET)
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            try:
                self.sock.connect(endpoint)
            except Exception:
                self.sock.close()
                raise
            authority = "localhost"
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((
                "GET / HTTP/1.1\r\nHost: " + authority + "\r\nUpgrade: websocket\r\n"
                "Connection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            self.buffer = b""
            while b"\r\n\r\n" not in self.buffer:
                if len(self.buffer) > 65536:
                    raise Disconnected("websocket response headers too large")
                self.buffer += self._recv()
            head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
            lines = head.split(b"\r\n")
            headers = dict(line.lower().split(b":", 1) for line in lines[1:] if b":" in line)
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            # Header names are case-insensitive; the Accept value itself is not.
            actual = next((line.split(b":", 1)[1].strip() for line in lines[1:]
                           if line.lower().startswith(b"sec-websocket-accept:")), b"")
            if (b" 101 " not in lines[0] or actual != accept
                    or headers.get(b"upgrade", b"").strip() != b"websocket"):
                raise Disconnected("websocket upgrade refused or invalid")
            self.sock.settimeout(None)
            self.send_lock = threading.Lock()
        except Exception:
            self.sock.close()
            raise

    def _recv(self):
        data = self.sock.recv(1 << 16)
        if not data:
            raise Disconnected("socket closed")
        return data

    def _take(self, n):
        while len(self.buffer) < n:
            self.buffer += self._recv()
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def _frame(self, opcode, payload):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            head = struct.pack(">BB", 0x80 | opcode, 0x80 | n)
        elif n < 1 << 16:
            head = struct.pack(">BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | opcode, 0x80 | 127, n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self.send_lock:
            self.sock.sendall(head + mask + masked)

    def send_text(self, text):
        self._frame(0x1, text.encode())

    def recv_text(self):
        """Return the next complete text message; answers pings on the way."""
        parts = []
        while True:
            b0, b1 = self._take(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._take(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._take(8))[0]
            mask = self._take(4) if b1 & 0x80 else None
            payload = self._take(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise Disconnected("server closed websocket")
            if opcode == 0x9:
                self._frame(0xA, payload)
                continue
            if opcode in (0x1, 0x2, 0x0):
                parts.append(payload)
                if b0 & 0x80:
                    return b"".join(parts).decode()

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class AppServer:
    """One connection to the daemon.

    on_notification(method, params) and on_request(id, method, params) run on
    the reader thread; keep them short. on_disconnect(reason) runs once when
    the connection drops.
    """

    def __init__(self, path=DEFAULT_ENDPOINT, on_notification=None, on_request=None,
                 on_disconnect=None, client_name="ma4", version="0.1"):
        self.on_notification = on_notification or (lambda method, params: None)
        self.on_request = on_request or (lambda rid, method, params: None)
        self.on_disconnect = on_disconnect or (lambda reason: None)
        self.ids = itertools.count(1)
        self.pending = {}
        self.lock = threading.Lock()
        self.closed = False
        self.ws = WebSocket(path)
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        try:
            self.info = self.call("initialize", {
                "clientInfo": {"name": client_name, "version": version},
                "capabilities": {"experimentalApi": True}})
            self.notify("initialized")
        except Exception:
            self.close()
            raise

    def _read_loop(self):
        reason = "closed"
        try:
            while True:
                message = json.loads(self.ws.recv_text())
                if "method" in message and "id" in message:
                    self.on_request(message["id"], message["method"], message.get("params") or {})
                elif "method" in message:
                    self.on_notification(message["method"], message.get("params") or {})
                elif "id" in message:
                    with self.lock:
                        slot = self.pending.pop(message["id"], None)
                    if slot:
                        slot["message"] = message
                        slot["event"].set()
        except (Disconnected, OSError, ValueError) as exc:
            reason = str(exc)
        finally:
            self.closed = True
            with self.lock:
                slots, self.pending = list(self.pending.values()), {}
            for slot in slots:
                slot["event"].set()
            self.on_disconnect(reason)

    def call(self, method, params=None, timeout=30):
        if self.closed:
            raise Disconnected("not connected")
        rid = next(self.ids)
        slot = {"event": threading.Event(), "message": None}
        with self.lock:
            self.pending[rid] = slot
        try:
            self.ws.send_text(json.dumps({"id": rid, "method": method, "params": params or {}}))
        except (OSError, Disconnected):
            with self.lock:
                self.pending.pop(rid, None)
            raise
        if not slot["event"].wait(timeout):
            with self.lock:
                self.pending.pop(rid, None)
            raise TimeoutError(method + " timed out")
        message = slot["message"]
        if message is None:
            raise Disconnected("connection lost during " + method)
        if "error" in message:
            raise RpcError(message["error"])
        return message.get("result")

    def notify(self, method, params=None):
        body = {"method": method}
        if params is not None:
            body["params"] = params
        self.ws.send_text(json.dumps(body))

    def respond(self, rid, result):
        self.ws.send_text(json.dumps({"id": rid, "result": result}))

    def close(self):
        self.closed = True
        self.ws.close()
