"""Provider registry and forge detection."""

from __future__ import annotations

from urllib.parse import urlsplit

from ..errors import UsageError
from .base import Asset, Provider, Release, SearchResult
from .gitea import CodebergProvider, GiteaProvider
from .github import GitHubProvider
from .gitlab import GitLabProvider

__all__ = [
    "Asset",
    "Provider",
    "Release",
    "SearchResult",
    "SUPPORTED",
    "get_provider",
    "detect_url",
]

SUPPORTED = ("github", "gitlab", "codeberg", "gitea")

# Hosts we can recognise in a URL, mapped to a factory.
_HOST_FACTORIES: dict[str, tuple[str, str | None]] = {
    "github.com": ("github", None),
    "gitlab.com": ("gitlab", None),
    "codeberg.org": ("codeberg", None),
}


def _build(name: str, client) -> Provider:  # noqa: ANN001
    if name == "github":
        return GitHubProvider(client)
    if name == "gitlab":
        return GitLabProvider(client)
    if name == "codeberg":
        return CodebergProvider(client)
    if name == "gitea":
        return GiteaProvider(client)
    raise UsageError(
        f"unsupported forge {name!r}",
        hint=f"supported forges: {', '.join(SUPPORTED)}",
    )


def get_provider(name: str, client) -> Provider:  # noqa: ANN001
    """Instantiate a provider, letting a gitea target carry its own host."""
    forge = name
    host = None
    if name.startswith("gitea:"):
        forge, _, host = name.partition(":")
    provider = _build(forge, client)
    if host and hasattr(provider, "host"):
        provider.host = host
    return provider


def detect_url(url: str, client) -> tuple[Provider, str] | None:  # noqa: ANN001
    """Return (provider, repo path) when *url* points at a supported forge."""
    split = urlsplit(url)
    host = (split.netloc or "").lower().removeprefix("www.")
    if not host:
        return None

    factory = _HOST_FACTORIES.get(host)
    if factory:
        provider = _build(factory[0], client)
        path = provider.parse_url(url)
        if path:
            return provider, path

    # Self-hosted GitLab and Gitea instances: probe the two API shapes we know.
    gitlab = GitLabProvider(client, host)
    path = gitlab.parse_url(url)
    if path:
        return gitlab, path
    gitea = GiteaProvider(client, host)
    path = gitea.parse_url(url)
    if path:
        return gitea, path
    return None
