"""Windows desktop integration and a byte stream to an existing Codex daemon."""
import base64
import os
import queue
import subprocess
import threading


def open_file(target):
    if target.suffix.lower() in {".desktop", ".lnk", ".url", ".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr", ".py", ".pyw", ".psm1", ".vbe", ".jse",
                                 ".wsf", ".wsh", ".hta", ".cpl", ".msc", ".reg", ".msp", ".msix", ".appx"}:
        raise ValueError("不通过文件链接执行程序、脚本或快捷方式")
    os.startfile(str(target))


def powershell_command(args, cwd, codex_home=None):
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    statements = ["Set-Location -LiteralPath " + literal(cwd)]
    if codex_home:
        statements.append("$env:CODEX_HOME = " + literal(codex_home))
    statements.append("& " + " ".join(literal(arg) for arg in args))
    return "; ".join(statements)


def terminal_arguments(args, cwd, codex_home=None, terminal=None):
    script = powershell_command(args, cwd, codex_home)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    shell = ["powershell.exe", "-NoProfile", "-NoExit", "-EncodedCommand", encoded]
    return [terminal, "-w", "new", "new-tab", "--title", "MA4"] + shell if terminal else shell


def process_options(console=False):
    # This helper is also imported by Linux tests; constants are Windows-only.
    return {"creationflags": subprocess.CREATE_NEW_CONSOLE if console else
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}


class ProxyStream:
    """Socket-like bytes over `app-server proxy`, NOT app-server stdio JSONL.

    Only this short-lived proxy belongs to us. Closing it never stops the daemon.
    A reader queue provides handshake timeouts on both Windows pipes and Linux.
    """
    def __init__(self, binary, socket_path, timeout=10, env=None):
        options = process_options() if os.name == "nt" else {}
        self.process = subprocess.Popen([str(binary), "app-server", "proxy", "--sock", str(socket_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, env=env, **options)
        self.timeout = timeout
        self.closed = threading.Event()
        self.chunks = queue.Queue(maxsize=256)
        self.buffer = b""
        self.reader = threading.Thread(target=self._read, name="ma4-proxy-reader", daemon=True)
        self.reader.start()

    def _put(self, chunk):
        while not self.closed.is_set():
            try:
                self.chunks.put(chunk, timeout=.1)
                return
            except queue.Full:
                pass

    def _read(self):
        try:
            while not self.closed.is_set():
                chunk = self.process.stdout.read(65536)
                if not chunk:
                    break
                self._put(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self._put(None)

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, size):
        if not self.buffer:
            if self.closed.is_set():
                return b""
            try:
                chunk = self.chunks.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise TimeoutError("Codex proxy 连接超时") from exc
            if chunk is None:
                return b""
            self.buffer = chunk
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def sendall(self, value):
        if self.closed.is_set():
            raise OSError("Codex proxy 已关闭")
        remaining = memoryview(value)
        while remaining:
            count = self.process.stdin.write(remaining)
            if not count:
                raise OSError("Codex proxy 写入失败")
            remaining = remaining[count:]

    def shutdown(self, how=None):
        self.close()

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.chunks.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            self.process.terminate()  # only the proxy we created, never daemon stop
            self.process.wait(timeout=3)
        self.process.stdout.close()
        if self.reader is not threading.current_thread():
            self.reader.join(timeout=1)
