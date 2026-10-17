"""Error hierarchy and exit codes.

Exit codes are part of the public interface: scripts and systemd units rely on
them.  They are documented in ``docs/exit-codes.md`` and in ``gitget help``.
"""

from __future__ import annotations


class GitgetError(Exception):
    """Base class for every expected, user-facing failure."""

    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(GitgetError):
    """Bad command line usage."""

    exit_code = 2


class NetworkError(GitgetError):
    """Network failure, or a forge API answered with an unexpected status."""

    exit_code = 3


class NotFoundError(GitgetError):
    """A repository, release or asset could not be found."""

    exit_code = 4


class AmbiguousError(GitgetError):
    """Several candidates match and we cannot ask the user (headless mode)."""

    exit_code = 5
    candidates: list[str]

    def __init__(self, message: str, candidates: list[str], *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.candidates = candidates


class ChecksumError(GitgetError):
    """A downloaded artifact does not match its published checksum."""

    exit_code = 6


class PrivilegeError(GitgetError):
    """We need root and cannot obtain it non-interactively."""

    exit_code = 7


class ConfigError(GitgetError):
    """Configuration or registry file is malformed."""

    exit_code = 8
