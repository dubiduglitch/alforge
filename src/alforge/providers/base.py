"""Provider interface shared by every supported forge.

A provider knows three things and nothing else:

* how to fetch the latest *release* of a repository, normalised into
  :class:`Release` / :class:`Asset`,
* how to search for repositories,
* how to recognise one of its own URLs.

Everything above (asset scoring, version comparison, installation, state) is
forge agnostic.  Adding a new forge means adding one module here.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int | None = None
    digest: str | None = None
    id: str | None = None


@dataclass(frozen=True)
class Release:
    forge: str
    repo: str
    tag: str
    name: str | None = None
    prerelease: bool = False
    published_at: str | None = None
    html_url: str | None = None
    assets: tuple[Asset, ...] = field(default_factory=tuple)

    def asset(self, name: str) -> Asset | None:
        for candidate in self.assets:
            if candidate.name == name:
                return candidate
        return None


@dataclass(frozen=True)
class SearchResult:
    forge: str
    path: str
    description: str = ""
    stars: int = 0
    updated_at: str | None = None

    @property
    def target(self) -> str:
        return f"{self.forge}:{self.path}"


class Provider(abc.ABC):
    """Base class for forge backends."""

    name: str = ""
    domain: str = ""

    def __init__(self, client) -> None:  # noqa: ANN001 - HttpClient, avoids a cycle
        self.client = client

    # -- required --------------------------------------------------------- #
    @abc.abstractmethod
    def latest_release(self, path: str) -> Release | None:
        """Latest stable release of ``path``, or None when there is none."""

    def releases(self, path: str, *, limit: int = 10) -> list[Release]:
        """Recent releases, newest first.

        Only needed to skip a pre-release and fall back to the newest stable
        one, so the default of "just the latest" is enough for a forge that
        cannot list releases cheaply.
        """
        latest = self.latest_release(path)
        return [latest] if latest is not None else []

    def latest_stable_release(self, path: str, *, limit: int = 20) -> Release | None:
        """Newest release that is not flagged as a pre-release."""
        for release in self.releases(path, limit=limit):
            if not release.prerelease:
                return release
        return None

    @abc.abstractmethod
    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        """Search repositories by free text."""

    @abc.abstractmethod
    def parse_url(self, url: str) -> str | None:
        """Extract the repository path from one of this forge's URLs."""

    # -- helpers ---------------------------------------------------------- #
    def target_url(self, path: str) -> str:
        if self.name == "gitea":
            host, _, rest = path.partition("/")
            return f"https://{host}/{rest}"
        return f"https://{self.domain}/{path}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Provider {self.name}>"
