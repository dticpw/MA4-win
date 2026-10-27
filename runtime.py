"""Project-local runtime discovery and terminal launch; never changes global config."""
import json
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess

from appserver import tcp_address
from os_adapters import current
from os_adapters.windows import powershell_command

ROOT = Path(__file__).resolve().parent


def load_config(path=None):
    path = Path(path or ROOT / "config.json").resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    system = "windows" if os.name == "nt" else "linux"
    if path == (ROOT / "config.json").resolve():
        override = json.loads((ROOT / ("config." + system + ".json")).read_text(encoding="utf-8"))
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key] = {**config[key], **value}
            else:
                config[key] = value
    for key in ("codex_home", "data_dir", "quota_source", "default_cwd"):
        if config.get(key):
            value = Path(config[key]).expanduser()
            config[key] = str(value if value.is_absolute() else path.parent / value)
    config["data_dir"] = config.get("data_dir") or str(path.parent / ".ma4")
    config["default_cwd"] = config.get("default_cwd") or str(Path.home() / "codex")
    codex_home = Path(config.get("codex_home") or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    control = str(codex_home / "app-server-control/app-server-control.sock")
    endpoint = str(config.get("app_server") or ("proxy://" if os.name == "nt" else "unix://"))
    if endpoint.startswith("ws://"):
        host, port = tcp_address(endpoint)
        endpoint = "ws://%s:%d" % (("[" + host + "]") if ":" in host else host, port)
    elif endpoint.startswith(("unix://", "proxy://")):
        scheme, value = endpoint.split("://", 1)
        endpoint = scheme + "://" + (value or control)
        if not Path(value or control).is_absolute():
            raise ValueError("控制端点需为本机绝对路径")
        if os.name == "nt" and scheme == "unix":
            raise ValueError("Windows 请使用 proxy:// 接入原生后台")
    else:
        raise ValueError("后台地址需为本机 unix://、proxy:// 或 ws://")
    config["app_server"] = endpoint
    return config


def find_app_browser(configured=None):
    """Use an installed Chromium browser in app mode, without another profile."""
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and path.suffix.lower() == ".exe":
            return str(path.resolve())
        raise ValueError("browser_bin 指向的浏览器 exe 不存在")
    roots = [Path(value) for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
             if (value := os.environ.get(name))]
    for relative in ("Google/Chrome/Application/chrome.exe",
                     "Microsoft/Edge/Application/msedge.exe"):
        for base in roots:
            path = base / relative
            if path.is_file():
                return str(path)
    for name in ("chrome.exe", "msedge.exe"):
        path = shutil.which(name)
        if path:
            return path
    raise ValueError("未找到 Chrome 或 Edge；请在项目配置设置 browser_bin")


def runtime_key(config, config_path):
    value = {"path": os.path.normcase(str(Path(config_path).resolve())), "config": config}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def find_codex(configured=None):
    candidate = configured or shutil.which("codex")
    if candidate:
        path = Path(candidate).expanduser()
        if not path.is_file():
            found = shutil.which(str(path))
            path = Path(found) if found else path
        if os.name != "nt" or path.suffix.lower() == ".exe":
            if path.is_file():
                return str(path.absolute())
        # npm's cmd/ps1 wrapper is not an executable; use the same package's binary.
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
        package = path.parent / "node_modules/@openai/codex"
        patterns = [
            "node_modules/@openai/codex-win32-" + arch + "/vendor/*/bin/codex.exe",
            "vendor/*-pc-windows-msvc/codex/codex.exe",
        ]
        for pattern in patterns:
            matches = sorted(package.glob(pattern))
            if matches:
                return str(matches[0].resolve())
    if os.name != "nt" and not configured:
        matches = sorted(Path.home().glob(".nvm/versions/node/*/bin/codex"))
        if matches:
            return str(matches[-1])
    raise ValueError("找不到 Codex 可执行文件；请在项目 config.json 设置 codex_bin")


def child_environment(binary, codex_home=None):
    env = dict(os.environ)
    binary = Path(binary)
    paths = [str(binary.parent)]
    vendor_path = binary.parent.parent / "path"
    if vendor_path.is_dir():
        paths.append(str(vendor_path))
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    if codex_home:
        env["CODEX_HOME"] = str(codex_home)
    return env


def codex_arguments(binary, endpoint, cwd, thread_id=None):
    endpoint = str(endpoint)
    if endpoint.startswith("proxy://"):
        endpoint = "unix://" + endpoint[8:]
    args = [str(binary), "--remote", endpoint]
    if thread_id:
        args.extend(["resume", thread_id])
    args.extend(["-C", str(cwd)])
    return args


def terminal_arguments(binary, endpoint, cwd, thread_id=None, codex_home=None, wt=None):
    args = codex_arguments(binary, endpoint, cwd, thread_id)
    return current().terminal_arguments(args, cwd, codex_home, wt)


def open_terminal(binary, endpoint, cwd, thread_id=None, codex_home=None):
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise ValueError("工作目录不存在：" + str(cwd))
    wt = shutil.which("wt.exe") if os.name == "nt" else None
    args = terminal_arguments(binary, endpoint, cwd, thread_id, codex_home, wt)
    options = {"env": child_environment(binary, codex_home)}
    # A newly created PowerShell console needs its own interactive handles.
    # Terminal launchers (wt / gnome-terminal) create those handles themselves.
    if os.name != "nt" or wt:
        options.update(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    if os.name == "nt":
        options["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP if wt
                                    else subprocess.CREATE_NEW_CONSOLE)
    else:
        options["start_new_session"] = True
    subprocess.Popen(args, **options)
    return {"opened": True}


def ensure_daemon(binary, endpoint, codex_home=None):
    """Start only the native daemon when absent; never restart or stop one."""
    if str(endpoint).startswith("ws://"):
        return
    env = child_environment(binary, codex_home)
    options = current().process_options() if os.name == "nt" else {}
    version = subprocess.run([binary, "app-server", "daemon", "version"],
                             capture_output=True, timeout=10, env=env, **options)
    try:
        running = json.loads(version.stdout).get("status") == "running"
    except (ValueError, AttributeError):
        running = False
    if running:
        return
    result = subprocess.run([binary, "app-server", "daemon", "start"],
                            capture_output=True, timeout=60, env=env, **options)
    if result.returncode:
        raise OSError("无法启动 Codex 原生后台，请在终端检查 daemon 状态（退出码 %d）" % result.returncode)
