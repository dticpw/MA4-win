"""Operating-system integration; shared application code selects one adapter."""
import os


def current():
    if os.name == "nt":
        from . import windows
        return windows
    from . import linux
    return linux
