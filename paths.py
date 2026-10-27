"""Filesystem identity and link checks shared by task scheduling and cleanup."""
import os
from pathlib import Path
import re
import stat


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
