"""Terminal output, prompts, and the on-disk audit log.

Every message goes through this module so that ``--quiet``, ``--json`` and
colour handling stay consistent, and so that background runs leave a usable
trail in ``~/.local/state/gitget/gitget.log``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import paths

_QUIET = False
_JSON = False
_COLOR = False
_ASSUME_YES = False
_LOG_PATH: Path | None = None


class Style:
    """ANSI escapes, empty when colour is disabled."""

    def __init__(self, enabled: bool) -> None:
        self.bold = "\033[1m" if enabled else ""
        self.dim = "\033[2m" if enabled else ""
        self.green = "\033[32m" if enabled else ""
        self.yellow = "\033[33m" if enabled else ""
        self.red = "\033[31m" if enabled else ""
        self.cyan = "\033[36m" if enabled else ""
        self.reset = "\033[0m" if enabled else ""


_STYLE = Style(False)


def configure(*, quiet: bool = False, json_output: bool = False, color: bool | None = None) -> None:
    global _QUIET, _JSON, _COLOR, _STYLE
    _QUIET = quiet
    _JSON = json_output
    if color is None:
        color = sys.stdout.isatty() and not _env_no_color()
    _COLOR = bool(color)
    _STYLE = Style(_COLOR)


def _env_no_color() -> bool:
    import os

    return "NO_COLOR" in os.environ


def set_assume_yes(value: bool) -> None:
    global _ASSUME_YES
    _ASSUME_YES = value


def assume_yes() -> bool:
    return _ASSUME_YES


def style() -> Style:
    return _STYLE


def is_tty() -> bool:
    """True only when stdin *and* stdout are a terminal.

    Background units get ``False`` here, which is what keeps prompts from
    hanging a timer forever.
    """
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (ValueError, AttributeError):
        return False


def _log(level: str, message: str) -> None:
    global _LOG_PATH
    try:
        if _LOG_PATH is None:
            paths.state_dir().mkdir(parents=True, exist_ok=True)
            _LOG_PATH = paths.log_file()
        from datetime import datetime

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] [{level}] {message}\n")
    except OSError:
        pass


def _emit(text: str, *, stream: Any = None, plain: str | None = None) -> None:
    stream = stream or sys.stdout
    stream.write(text + "\n")
    _log("INFO", plain if plain is not None else _strip(text))


def _strip(text: str) -> str:
    for code in ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m"):
        text = text.replace(code, "")
    return text


def info(message: str) -> None:
    if _JSON:
        return
    _log("INFO", message)
    if not _QUIET:
        _emit(f"  {message}")


def ok(message: str) -> None:
    _log("OK", message)
    if _JSON:
        return
    if not _QUIET:
        _emit(f"{_STYLE.green}\u2714{_STYLE.reset} {message}", plain=message)


def warn(message: str) -> None:
    _log("WARN", message)
    if not _JSON:
        _emit(f"{_STYLE.yellow}\u26a0{_STYLE.reset} {message}", stream=sys.stderr, plain=message)


def error(message: str) -> None:
    _log("ERROR", message)
    if not _JSON:
        _emit(f"{_STYLE.red}\u2716{_STYLE.reset} {message}", stream=sys.stderr, plain=message)


def detail(message: str) -> None:
    """Indented secondary line, hidden by --quiet."""
    _log("INFO", message)
    if not _QUIET and not _JSON:
        _emit(f"    {_STYLE.dim}{message}{_STYLE.reset}", plain=message)


def heading(message: str) -> None:
    _log("INFO", message)
    if not _QUIET and not _JSON:
        _emit(f"{_STYLE.bold}{message}{_STYLE.reset}", plain=message)


def emit_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def json_mode() -> bool:
    return _JSON


def table(headers: Sequence[str], rows: Iterable[Sequence[str]], *, empty: str = "nothing to show") -> None:
    """Left-aligned plain text table. Never truncates cells."""
    rows = [list(map(str, row)) for row in rows]
    if not rows:
        if not _QUIET:
            _emit(f"  {empty}")
        return
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(headers)).rstrip()]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    if not _QUIET and not _JSON:
        for line in lines:
            _emit(line, plain=line)


def confirm(question: str, *, default: bool = False) -> bool:
    """Ask a yes/no question. Never prompts without a terminal."""
    if _ASSUME_YES:
        return True
    if not is_tty():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    sys.stdout.write(f"{question}{suffix}")
    sys.stdout.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n")
        return False
    if not answer:
        return default
    return answer in ("y", "yes", "o", "oui")


def choose(question: str, options: Sequence[str], *, default: int = 1) -> int | None:
    """Numbered menu. Returns a 0-based index, or None when unavailable."""
    if not is_tty():
        return None
    if len(options) == 1:
        return 0
    sys.stdout.write(f"{question}\n")
    for index, option in enumerate(options, start=1):
        marker = "*" if index == default else " "
        sys.stdout.write(f"  {marker} {index}) {option}\n")
    sys.stdout.write(f"Select [1-{len(options)}] (default {default}, 'q' to abort): ")
    sys.stdout.flush()
    try:
        answer = input().strip()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n")
        return None
    if answer in ("q", "Q"):
        return None
    if not answer:
        return default - 1
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return int(answer) - 1
    return None


def prompt_secret(question: str) -> str:
    """Read a secret without echoing it."""
    import getpass

    try:
        return getpass.getpass(question)
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n")
        return ""
