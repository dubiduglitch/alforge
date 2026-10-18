"""Parsing of ``alforge://`` URIs, the bridge a web page can use.

A browser cannot execute a program: it can only ask the desktop to open a URI.
We register ``x-scheme-handler/alforge`` with a ``.desktop`` file, so a page (or
a small extension adding an "install" button to a forge project page) can do::

    alforge://install/github/owner/repo

and the desktop launches ``alforge handle-uri <that uri>``.

Only forge *targets* are accepted, never a direct ``.deb`` URL: a random web
page must not be able to make you install an arbitrary package.  Everything
after parsing goes through the normal pipeline, which verifies the checksum,
validates the package name from the control archive, and asks the human once.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from .config import SUPPORTED_FORGES
from .errors import UsageError

SCHEME = "alforge"

#: Actions a URI may ask for.  ``track`` follows without installing.
VERBS = ("install", "track")

#: ``forgejo`` is accepted here too because ``parse_target`` canonicalises it.
URI_FORGES = frozenset(SUPPORTED_FORGES) | {"forgejo"}


@dataclass(frozen=True)
class Request:
    """What a URI asked for."""

    verb: str
    spec: str | None = None


def parse(uri: str) -> Request:
    """Turn ``alforge://install/github/owner/repo`` into a :class:`Request`."""
    parts = urlsplit(uri.strip())
    if parts.scheme.lower() != SCHEME:
        raise UsageError(
            f"not an {SCHEME}: URI",
            hint=f"expected {SCHEME}://<action>/<forge>/<owner>/<repo>",
        )

    verb = parts.netloc.strip().lower()
    if verb not in VERBS:
        raise UsageError(
            f"unsupported alforge action {verb!r}",
            hint=f"supported actions: {', '.join(VERBS)}",
        )

    # A query or fragment would only be a way to smuggle extra instructions in,
    # so they are rejected outright rather than ignored.
    if parts.query or parts.fragment:
        raise UsageError("an alforge URI must not carry a query or a fragment")

    segments = [unquote(segment) for segment in parts.path.split("/") if segment]
    if len(segments) < 3:
        raise UsageError(
            "incomplete target",
            hint=f"expected {SCHEME}://{verb}/<forge>/<owner>/<repo>",
        )

    forge = segments[0].lower()
    if forge not in URI_FORGES:
        raise UsageError(
            f"unsupported forge {forge!r}",
            hint=f"supported forges: {', '.join(sorted(URI_FORGES))}",
        )

    # A repository path never contains a colon, so one means someone tried to
    # pass a URL (or a nested spec) as the target.
    if any(":" in segment for segment in segments[1:]):
        raise UsageError("an alforge URI must not carry a URL as its target")

    return Request(verb=verb, spec=f"{forge}:" + "/".join(segments[1:]))
