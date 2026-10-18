"""Gitea / Forgejo backend, used for Codeberg and self-hosted instances.

Target syntax carries the host: ``gitea:git.example.org/owner/repo``.
``codeberg:owner/repo`` is a convenience alias that implies ``codeberg.org``.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from .base import Asset, Provider, Release, SearchResult

DEFAULT_HOST = "codeberg.org"
URL_RE = re.compile(r"^https?://(?P<host>[^/]+)/(?P<path>[^/]+/[^/]+?)(?:\.git)?(?:/.*)?$")


class GiteaProvider(Provider):
    name = "gitea"
    domain = DEFAULT_HOST

    def __init__(self, client, host: str = DEFAULT_HOST, *, forge: str = "gitea") -> None:
        super().__init__(client)
        self.host = host
        self.name = forge

    # -- api -------------------------------------------------------------- #
    def _split(self, path: str) -> tuple[str, str]:
        """``host/owner/repo`` -> (host, owner/repo)."""
        segments = path.split("/")
        if len(segments) < 3:
            raise ValueError(
                f"{self.name} expects 'host/owner/repo', got {path!r}"
            )
        return segments[0], "/".join(segments[1:])

    def latest_release(self, path: str) -> Release | None:
        host, repo = self._split(path)
        base = f"https://{host}/api/v1/repos/{repo}"
        payload = self.client.get_json(f"{base}/releases/latest", forge="codeberg", allow_404=True)
        if not payload:
            entries = self.client.get_json(
                f"{base}/releases?limit=1&draft=false&pre-release=false",
                forge="codeberg",
                allow_404=True,
            )
            if not entries:
                return None
            payload = entries[0]
        return self._to_release(path, payload)

    def releases(self, path: str, *, limit: int = 10) -> list[Release]:
        host, repo = self._split(path)
        entries = self.client.get_json(
            f"https://{host}/api/v1/repos/{repo}/releases?limit={limit}&draft=false",
            forge="codeberg",
            allow_404=True,
        )
        return [self._to_release(path, entry) for entry in entries or []]

    def _to_release(self, path: str, payload: dict) -> Release:
        assets = tuple(
            Asset(
                name=asset.get("name", ""),
                url=asset.get("browser_download_url", ""),
                size=asset.get("size"),
                id=str(asset.get("id")) if asset.get("id") is not None else None,
            )
            for asset in payload.get("assets", [])
            if asset.get("browser_download_url")
        )
        return Release(
            forge=self.name,
            repo=path,
            tag=payload.get("tag_name", ""),
            name=payload.get("name"),
            prerelease=bool(payload.get("prerelease")),
            published_at=payload.get("published_at"),
            html_url=payload.get("html_url"),
            assets=assets,
        )

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        payload = self.client.get_json(
            f"https://{self.host}/api/v1/repos/search?q={quote(query)}&limit={limit}",
            forge="codeberg",
        )
        items = (payload or {}).get("data", [])
        return [
            SearchResult(
                forge=self.name,
                path=f"{self.host}/{item.get('full_name', '')}",
                description=(item.get("description") or "").strip(),
                stars=item.get("stars_count", 0),
                updated_at=item.get("updated_at"),
            )
            for item in items
            if item.get("full_name")
        ]

    def parse_url(self, url: str) -> str | None:
        split = urlsplit(url)
        if not split.netloc:
            return None
        match = URL_RE.match(url)
        if not match:
            return None
        host = match.group("host")
        path = match.group("path").removesuffix(".git")
        if host != self.host:
            return None
        return f"{host}/{path}"


class CodebergProvider(GiteaProvider):
    """Codeberg is a Gitea instance; only the defaults differ."""

    name = "codeberg"

    def __init__(self, client, host: str = DEFAULT_HOST) -> None:
        super().__init__(client, host, forge="codeberg")

    def parse_url(self, url: str) -> str | None:
        split = urlsplit(url)
        if not split.netloc or "codeberg.org" not in split.netloc:
            return None
        match = URL_RE.match(url)
        if not match:
            return None
        return match.group("path").removesuffix(".git")
