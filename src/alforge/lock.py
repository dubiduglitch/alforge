"""Single-writer lock shared by every command that writes state.

``state.json`` and ``repos.txt`` are updated with a read-modify-write cycle that
spans a whole command, so a timer firing while a manual ``alforge upgrade`` runs
could otherwise lose one side's changes.  We take one advisory lock (``flock``)
for the duration of any writing command.

The lock is only advisory and per-user, which is exactly the scope of the files
it protects: everything alforge keeps lives under ``$XDG_*`` of one user.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from . import paths, ui


class LockBusy(Exception):
    """Another alforge process holds the lock and the caller must not wait."""


@contextmanager
def exclusive(*, wait: bool) -> Iterator[None]:
    """Hold the write lock for the duration of the ``with`` block.

    When the lock is already held:
    * ``wait=True`` (interactive) blocks until it frees up, with a note,
    * ``wait=False`` (headless, e.g. the timer) raises :class:`LockBusy` so the
      caller can skip this run instead of piling up behind the other one.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX: locking is best effort
        yield
        return

    paths.ensure_dirs()
    target = paths.state_dir() / "alforge.lock"
    stream = target.open("w", encoding="utf-8")
    try:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if not wait:
                raise LockBusy() from None
            ui.detail("another alforge run is in progress, waiting for it to finish")
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        stream.close()
