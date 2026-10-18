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


def data_dir() -> Path:
    """Where installed AppImages live, next to the desktop entries they own."""
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def appimage_dir() -> Path:
    return data_dir() / "AppImages"


def bin_dir() -> Path:
    """Directory holding the stable launch links for AppImages.

    ``~/.local/bin`` (or ``$XDG_BIN_HOME``) is a shared namespace, so nothing
    here is ever created eagerly: only :func:`install` touches it, and it
    refuses to overwrite a file it does not own.
    """
    value = os.environ.get("XDG_BIN_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".local/bin"


def applications_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "applications"


def icons_dir(size: str) -> Path:
    """A directory inside the ``hicolor`` icon theme (``256x256``, ``scalable``)."""
    return _xdg("XDG_DATA_HOME", ".local/share") / "icons" / "hicolor" / size / "apps"


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
    return (config_dir(), state_dir(), cache_dir(), download_dir(), appimage_dir())


def ensure_dirs() -> None:
    """Create every directory alforge needs, with restrictive permissions."""
    for directory in all_dirs():
        directory.mkdir(parents=True, exist_ok=True)
        if directory in (config_dir(), state_dir()):
            directory.chmod(0o700)
