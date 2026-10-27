"""One-click Windows launcher; only manages processes it started."""
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from appserver import AppServer, tcp_address
from runtime import ROOT, child_environment, find_app_browser, find_codex, load_config, runtime_key


# Retain handles for deliberately detached children while this launcher is alive.
_children = []


def reap_children():
    _children[:] = [p for p in _children if p.poll() is None]


def kernel():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, args, result in (
        ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ("GetProcessTimes", [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
        ("GetExitCodeProcess", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        ("TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        ("CreateMutexW", [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        ("ReleaseMutex", [wintypes.HANDLE], wintypes.BOOL),
    ):
        func = getattr(api, name)
        func.argtypes, func.restype = args, result
    return api


def birth_time(api, handle):
    stamps = [wintypes.FILETIME() for _ in range(4)]
    if not api.GetProcessTimes(handle, *(ctypes.byref(t) for t in stamps)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime


def identify(pid):
    api = kernel()
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OSError("无法确认刚启动的进程")
    try:
        return {"pid": pid, "created": birth_time(api, handle)}
    finally:
        api.CloseHandle(handle)


def stop_owned(record):
    """Creation time and handle prevent stale PID records from killing other apps."""
    if not record:
        return False
    api = kernel()
    handle = api.OpenProcess(0x1000 | 0x100000 | 1, False, record["pid"])
    if not handle:
        if ctypes.get_last_error() == 87:  # exited / no such PID
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if birth_time(api, handle) != record["created"]:
            return False
        code = wintypes.DWORD()
        if not api.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value != 259:
            return False
        if not api.TerminateProcess(handle, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if api.WaitForSingleObject(handle, 5000) != 0:
            raise TimeoutError("进程尚未退出，请稍后重试")
        return True
    finally:
        api.CloseHandle(handle)


@contextlib.contextmanager
def launch_lock(config_path):
    if os.name != "nt":
        raise ValueError("一键入口只用于 Windows；其他系统请使用分组件启动")
    api = kernel()
    name = "Local\\MA4-" + hashlib.sha256(str(ROOT).lower().encode()).hexdigest()
    handle = api.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        acquired = api.WaitForSingleObject(handle, 30000) in (0, 0x80)
        if not acquired:
            raise TimeoutError("另一个 MA4 启动操作还在进行，请稍后再试")
        yield
    finally:
        if acquired:
            api.ReleaseMutex(handle)
        api.CloseHandle(handle)


def context(config_path):
    path = Path(config_path).resolve()
    config = load_config(path)
    data = Path(config.get("data_dir") or ROOT / ".ma4")
    key = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()[:16]
    state_file = data / ("launcher-" + key + ".json")
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    return path, config, state_file, state


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")
    temp.replace(path)


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=.5):
            return True
    except (ConnectionRefusedError, TimeoutError):
        return False


def get_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=1) as response:
        return json.load(response)


def web_state(base, key):
    try:
        state = get_json(base + "/api/state")
    except (OSError, ValueError) as exc:
        raise ValueError("网页端口被占用，但不是可复用的 MA4 实例") from exc
    if state.get("side", {}).get("runtime", {}).get("launchKey") != key:
        raise ValueError("网页端口已有其他配置或旧版实例，请先从原启动窗口停止它")
    return state


def backend_ready(endpoint):
    host, port = tcp_address(endpoint)
    url = "http://%s:%d/readyz" % ("[" + host + "]" if ":" in host else host, port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def spawn(args, env=None):
    reap_children()
    process = subprocess.Popen(args, cwd=ROOT, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    _children.append(process)
    return process


def open_app_window(base, browser_bin):
    # Same --app mode as the upstream Linux desktop entry. The installed browser
    # owns the GUI window; closing it never invokes stop() or stops shared services.
    return spawn([browser_bin, "--app=" + base, "--window-size=1280,900"])


def wait_ready(process, predicate, label):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise OSError(label + "启动失败；可运行 run.ps1 对应组件查看具体错误")
        try:
            if predicate():
                return
        except (OSError, ValueError):
            pass
        time.sleep(.15)
    raise TimeoutError(label + "未在 20 秒内就绪")


def start(config_path, browser=True):
    with launch_lock(config_path):
        path, config, state_file, state = context(config_path)
        window_browser = find_app_browser(config.get("browser_bin")) if browser else None
        key = runtime_key(config, path)
        port = int(config.get("port", 8764))
        if not 1 <= port <= 65535:
            raise ValueError("网页端口必须在 1–65535 之间")
        endpoint = config["app_server"]
        host, backend_port = tcp_address(endpoint)
        if port == backend_port:
            raise ValueError("网页和共享后台必须使用不同端口")
        base = "http://127.0.0.1:" + str(port)
        web_exists = port_open("127.0.0.1", port)
        if web_exists:
            web_state(base, key)  # refuse foreign HTTP before starting anything
        created = []
        try:
            if not port_open(host, backend_port):
                binary = find_codex(config.get("codex_bin"))
                proc = spawn([binary, "app-server", "--listen", endpoint],
                             child_environment(binary, config.get("codex_home")))
                created.append(("backend", proc))
                state["backend"] = identify(proc.pid)
                save(state_file, state)
                wait_ready(proc, lambda: backend_ready(endpoint), "共享后台")
            elif not backend_ready(endpoint):
                raise ValueError("后台端口已占用，但不是已就绪的 Codex app-server")
            client = AppServer(endpoint, client_name="ma4_launcher")
            client.close()
            if not web_exists:
                proc = spawn([sys.executable, "-B", "-X", "utf8", str(ROOT / "launch.py"),
                              "web", "--config", str(path)])
                created.append(("web", proc))
                state["web"] = identify(proc.pid)
                save(state_file, state)
                wait_ready(proc, lambda: web_state(base, key).get("daemon", {}).get("connected"),
                           "MA4 网页")
            else:
                deadline = time.monotonic() + 10
                while not web_state(base, key).get("daemon", {}).get("connected"):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("网页尚未连接共享后台")
                    time.sleep(.2)
        except BaseException:
            # Roll back only children created in this attempt; reused services survive.
            for role, proc in reversed(created):
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
                state.pop(role, None)
            if created:
                save(state_file, state)
            raise
    if browser:
        open_app_window(base, window_browser)
    print("MA4 已就绪：" + base, flush=True)
    return base


def stop(config_path, include_backend=False):
    with launch_lock(config_path):
        path, config, state_file, state = context(config_path)
        roles = ["web", "backend"] if include_backend else ["web"]
        stopped = []
        for role in roles:
            if stop_owned(state.get(role)):
                stopped.append(role)
            state.pop(role, None)
        if state_file.exists():
            save(state_file, state)
    reap_children()
    print("已停止本入口启动的：" + ("、".join(stopped) or "无运行实例"), flush=True)
    if not include_backend:
        print("共享后台保持运行；终端会话不受影响。", flush=True)
    return stopped
