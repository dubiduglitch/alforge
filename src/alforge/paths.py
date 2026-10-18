"""XDG base directory resolution.

alforge follows the XDG split strictly:

config   -> hand-editable, user intent      (~/.config/alforge)
state    -> learned data, machine managed   (~/.local/state/alforge)
cache    -> disposable downloads            (~/.cache/alforge)

Nothing user-facing is ever written under a ``sudo``-owned path, so the tool
stays usable by an unprivileged user on a shared machine.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "alforge"


def _xdg(env: str, default: str) -> Path:
    value = os.environ.get(env)
    if value:
        return Path(value).expanduser()
    return Path.home() / default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / APP


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def config_file() -> Path:
    return config_dir() / "config.json"


def registry_file() -> Path:
    return config_dir() / "repos.txt"


def state_file() -> Path:
    return state_dir() / "state.json"


def log_file() -> Path:
    return state_dir() / "alforge.log"


def download_dir() -> Path:
    return cache_dir() / "downloads"


def all_dirs() -> tuple[Path, ...]:
    return (config_dir(), state_dir(), cache_dir(), download_dir())


def ensure_dirs() -> None:
    """Create every directory alforge needs, with restrictive permissions."""
    for directory in all_dirs():
        directory.mkdir(parents=True, exist_ok=True)
        if directory in (config_dir(), state_dir()):
            directory.chmod(0o700)
