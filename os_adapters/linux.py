"""Linux desktop and process integration. No Windows imports or state."""
import subprocess
import threading


def open_file(target):
    if target.suffix.lower() == ".desktop":
        raise ValueError("不通过文件链接启动 .desktop 应用快捷方式")
    process = subprocess.Popen(["/usr/bin/xdg-open", str(target)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        threading.Thread(target=process.wait, daemon=True).start()
    else:
        if code:
            raise ValueError("系统默认应用未能打开此文件（退出码 %d）" % code)


def terminal_arguments(args, cwd, codex_home=None, terminal=None):
    return [terminal or "/usr/bin/gnome-terminal", "--"] + args


def process_options(console=False):
    return {"start_new_session": True}
