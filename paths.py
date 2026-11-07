"""Filesystem identity and link checks shared by task scheduling and cleanup."""
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit


def file_path_for_platform(value, windows=None):
    """Map file-link spellings only; never use this for workspace identity/scope."""
    windows = os.name == "nt" if windows is None else windows
    value = value.replace("\\", "/")
    if value.startswith("//"):
        raise ValueError("只支持本机文件")
    drive = re.fullmatch(r"/?([a-zA-Z]):/(.*)", value)
    if drive:
        letter, tail = drive.groups()
        return letter.upper() + ":/" + tail if windows else "/mnt/" + letter.lower() + "/" + tail
    if re.match(r"/?[a-zA-Z]:", value):
        raise ValueError("盘符路径必须从根目录开始，如 E:/")
    mount = re.fullmatch(r"/mnt/([c-fC-F])(?:/(.*))?", value)
    if mount:
        letter, tail = mount.groups()
        return letter.upper() + ":/" + (tail or "") if windows else "/mnt/" + letter.lower() + "/" + (tail or "")
    if windows and value.startswith("/"):
        raise ValueError("当前 Windows 无法定位此 Linux 绝对路径；仅支持 /mnt/c 至 /mnt/f 共享盘")
    return value


def resolve_file_reference(reference, cwd):
    """Keep literal filenames before trying citations and one URL decoding pass."""
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 8192:
        raise ValueError("文件路径无效")
    raw = reference.strip()
    is_uri = raw.lower().startswith("file://")
    if any(ord(c) < 32 for c in raw):
        raise ValueError("文件路径含无效字符")
    if is_uri:
        uri = urlsplit(raw)
        if uri.netloc.lower() not in ("", "localhost") or uri.query:
            raise ValueError("只支持本机文件")
        raw = uri.path + ("#" + uri.fragment if uri.fragment else "")
        if not raw.startswith("/"):
            raise ValueError("本机 file URI 需要绝对路径")
    # Strip on the encoded spelling: %23L12 is a filename, not a citation.
    stripped = re.sub(r"(?::\d+(?::\d+)?(?:-\d+)?|#L\d+(?:C\d+)?(?:-L?\d+(?:C\d+)?)?)$", "", raw)
    def spellings():
        if not is_uri:
            yield from dict.fromkeys([raw, stripped])
        if is_uri or "%" in raw:
            for value in dict.fromkeys([raw, stripped]):
                yield unquote(value, errors="strict")

    target = None
    for value in spellings():
        if any(ord(c) < 32 for c in value):
            raise ValueError("文件路径含无效字符")
        if value.replace("\\", "/").startswith("//"):
            raise ValueError("只支持本机文件")
        if (re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value)
                and not re.match(r"^[a-zA-Z]:[\\/]", value)
                and not re.fullmatch(r"[^:]+:\d+(?::\d+)?(?:-\d+)?", value)):
            raise ValueError("只支持本地文件路径")
        # Windows /mnt/... and /E:/... are foreign spellings, not rooted paths
        # on cwd's drive. On POSIX a real backslash/colon in a filename wins.
        native = not (os.name == "nt" and (value.replace("\\", "/").startswith("/")
                     or re.match(r"^[a-zA-Z]:(?![\\/])", value)))
        def candidates():
            if native:
                yield value
            mapped = file_path_for_platform(value)
            if not native or mapped != value:
                yield mapped

        for spelling in candidates():
            candidate = Path(spelling).expanduser()
            if not candidate.is_absolute():
                if not cwd:
                    continue
                candidate = Path(cwd) / candidate
            target = candidate.resolve()
            if target.exists():
                if not (target.is_file() or target.is_dir()):
                    raise ValueError("只能打开普通文件或目录")
                return target
    if target is None:
        raise ValueError("会话没有项目目录，无法解析相对路径")
    raise ValueError("文件不存在，可能已移动或清理：" + str(target))


def path_key(value):
    value = str(value)
    windows = bool(re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("\\\\"))
    if windows or os.name == "nt":
        return value.replace("\\", "/").rstrip("/").casefold()
    return value.rstrip("/")


def overlaps(left, right):
    a, b = path_key(left), path_key(right)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def is_link(path):
    """Include NTFS junctions/reparse points, even with Python 3.10."""
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) &
                                             getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def has_link(path):
    path = Path(path)
    return any(is_link(part) for part in [path, *path.parents])
