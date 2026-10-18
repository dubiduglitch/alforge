"""Checksum verification against release assets.

Supply-chain reality check: alforge installs packages as root from arbitrary
repositories.  Whenever the release publishes a checksum manifest we verify the
downloaded ``.deb`` against it.  With ``require_checksum = true`` (or
``--require-checksum``) a missing manifest is a hard failure instead of a
warning.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .errors import ChecksumError

MANIFEST_PATTERN = re.compile(
    r"(?i)^(?:"
    r"sha256sums?(?:\.txt)?|"
    r"sha256(?:sums)?\.txt|"
    r"checksums?(?:\.sha256|\.txt)?|"
    r"sha256|"
    r".*\.sha256(?:sum|sums)?(?:\.txt)?"
    r")$"
)


def is_manifest_name(name: str) -> bool:
    return bool(MANIFEST_PATTERN.match(name.strip()))


def parse_manifest(text: str) -> dict[str, str]:
    """Parse GNU coreutils ``sha256sum`` output, tolerating extra fields.

    Both ``<hash>  <name>`` and ``<hash> *<name>`` are accepted, as well as
    BSD style ``SHA256 (<name>) = <hash>``.
    """
    digests: dict[str, str] = {}
    bsd = re.compile(r"^SHA256\s*\((?P<name>[^)]+)\)\s*=\s*(?P<hash>[0-9a-fA-F]{64})$")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = bsd.match(line)
        if match:
            digests[match.group("name").strip()] = match.group("hash").lower()
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip().lower(), parts[1].strip()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            continue
        if name.startswith("*"):
            name = name[1:]
        digests[name.lstrip("./")] = digest
    return digests


def lookup(digests: dict[str, str], filename: str) -> str | None:
    """Find a digest for *filename*, tolerating path prefixes in the manifest."""
    if filename in digests:
        return digests[filename]
    base = Path(filename).name
    for name, digest in digests.items():
        if Path(name).name == base:
            return digest
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, expected: str) -> str:
    """Verify *path* against *expected*. Raises ChecksumError on mismatch."""
    actual = sha256_file(path)
    if actual.lower() != expected.lower():
        raise ChecksumError(
            f"checksum mismatch for {path.name}",
            hint=f"expected {expected.lower()}, got {actual}",
        )
    return actual
