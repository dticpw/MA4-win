"""Manual MA4 launcher. Backend and web have separate lifetimes."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from appserver import Disconnected, RpcError, tcp_address
from runtime import ROOT, child_environment, find_codex, load_config, open_terminal, ensure_daemon


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("start", "stop", "backend", "web", "terminal"), nargs="?", default="start")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--thread-id")
    parser.add_argument("--cwd", default=str(ROOT))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--include-backend", action="store_true")
    args = parser.parse_args()
    if args.component in ("start", "stop"):
        import desktop
        if args.component == "start":
            desktop.start(args.config, browser=not args.no_browser)
        else:
            desktop.stop(args.config, include_backend=args.include_backend)
        return 0
    config = load_config(args.config)
    if args.component == "web":
        import server
        return server.main(["--config", args.config])
    binary = find_codex(config.get("codex_bin"))
    endpoint = config["app_server"]
    if args.component == "terminal":
        open_terminal(binary, endpoint, Path(args.cwd).resolve(),
                      args.thread_id, config.get("codex_home"))
        return 0

    if not endpoint.startswith("ws://"):
        ensure_daemon(binary, endpoint, config.get("codex_home"))
        print("Codex 原生后台已就绪；关闭此窗口不会停止后台。", flush=True)
        return 0

    host, port = tcp_address(endpoint)
    # Fail before spawning on an occupied port; never stop an existing process.
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as check:
        if os.name == "nt":
            check.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        check.bind((host, port))
    print("MA4 共享后台：" + endpoint, flush=True)
    print("保持此窗口运行；Ctrl+C 停止后台会断开网页与终端。", flush=True)
    options = {"env": child_environment(binary, config.get("codex_home")),
               "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen([binary, "app-server", "--listen", endpoint], **options)
    try:
        # Poll so Windows Python can dispatch Ctrl+C while the child stays isolated.
        while proc.poll() is None:
            time.sleep(.2)
        return proc.returncode
    except KeyboardInterrupt:
        # Only the child created above. Never daemon stop or taskkill /T.
        proc.terminate()
        proc.wait(timeout=10)
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, Disconnected, RpcError, subprocess.SubprocessError) as exc:
        print("启动失败：" + str(exc), file=sys.stderr)
        sys.exit(1)
