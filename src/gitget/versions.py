"""Version handling.

gitget never guesses a version from a git tag: the authoritative version is the
``Version`` field inside the ``.deb`` control archive.  Tags are only used to
decide whether a release *changed*.

Two comparison engines are provided:

* :func:`compare` - uses ``dpkg --compare-versions`` when available, because
  that is the same engine APT itself uses.
* :func:`compare_pure` - a faithful port of dpkg's ``verrevcmp`` algorithm,
  used as a fallback and as the unit-tested reference implementation.
"""

from __future__ import annotations

import re
import shutil
import subprocess

_DEB_VERSION_RE = re.compile(
    r"^(?:(?P<epoch>\d+):)?(?P<upstream>[^:-]+)(?:-(?P<revision>[^:]+))?$"
)


def parse(version: str) -> tuple[int, str, str]:
    """Split a Debian version into (epoch, upstream, revision)."""
    match = _DEB_VERSION_RE.match(version.strip())
    if not match:
        return (0, version.strip(), "")
    epoch = int(match.group("epoch") or 0)
    return (epoch, match.group("upstream"), match.group("revision") or "")


def _order(char: str) -> int:
    """Character weight used by dpkg: '~' sorts before end-of-string."""
    if char == "~":
        return -1
    if char.isalpha():
        return ord(char)
    return ord(char) + 256


def _verrevcmp(left: str, right: str) -> int:
    """Port of dpkg's ``verrevcmp``; compares upstream or revision halves."""
    i = j = 0
    while i < len(left) or j < len(right):
        first_diff = 0
        while (i < len(left) and not left[i].isdigit()) or (
            j < len(right) and not right[j].isdigit()
        ):
            left_char = left[i] if i < len(left) and not left[i].isdigit() else ""
            right_char = right[j] if j < len(right) and not right[j].isdigit() else ""
            left_order = _order(left_char) if left_char else 0
            right_order = _order(right_char) if right_char else 0
            if left_order != right_order:
                return -1 if left_order < right_order else 1
            i += 1
            j += 1
        while i < len(left) and left[i] == "0":
            i += 1
        while j < len(right) and right[j] == "0":
            j += 1
        while i < len(left) and j < len(right) and left[i].isdigit() and right[j].isdigit():
            if not first_diff:
                first_diff = (ord(left[i]) - ord(right[j]))
            i += 1
            j += 1
        if i < len(left) and left[i].isdigit():
            return 1
        if j < len(right) and right[j].isdigit():
            return -1
        if first_diff:
            return -1 if first_diff < 0 else 1
    return 0


def compare_pure(left: str, right: str) -> int:
    """Pure-python Debian version comparison. Returns -1, 0 or 1."""
    left_epoch, left_upstream, left_revision = parse(left)
    right_epoch, right_upstream, right_revision = parse(right)
    if left_epoch != right_epoch:
        return -1 if left_epoch < right_epoch else 1
    result = _verrevcmp(left_upstream, right_upstream)
    if result:
        return result
    return _verrevcmp(left_revision, right_revision)


def _dpkg_available() -> bool:
    return shutil.which("dpkg") is not None


def compare(left: str, right: str) -> int:
    """Compare two Debian versions, preferring dpkg's implementation."""
    if _dpkg_available():
        relation = _dpkg_relation(left, right)
        if relation is not None:
            return relation
    return compare_pure(left, right)


def _dpkg_relation(left: str, right: str) -> int | None:
    for operator, value in (("gt", 1), ("eq", 0), ("lt", -1)):
        try:
            result = subprocess.run(
                ["dpkg", "--compare-versions", left, operator, right],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode == 0:
            return value
    return None


def is_newer(candidate: str, current: str | None) -> bool:
    """True when *candidate* is strictly newer than *current*."""
    if not candidate:
        return False
    if not current:
        return True
    return compare(candidate, current) > 0


def normalise_tag(tag: str) -> str:
    """Cosmetic tag cleanup used for display and state keys only."""
    cleaned = tag.strip()
    if cleaned.lower().startswith("v") and len(cleaned) > 1 and cleaned[1].isdigit():
        cleaned = cleaned[1:]
    return cleaned


def looks_like_version(value: str) -> bool:
    return bool(re.match(r"^\d", value.strip()))
