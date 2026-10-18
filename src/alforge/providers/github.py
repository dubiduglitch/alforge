"""GitHub backend (api.github.com)."""

from __future__ import annotations

import re

from .base import Asset, Provider, Release, SearchResult

API = "https://api.github.com"
PATH_RE = re.compile(r"^[^/]+/[^/]+$")
URL_RE = re.compile(r"^https?://(?:www\.)?github\.com/(?P<path>[^/]+/[^/]+)")


class GitHubProvider(Provider):
    name = "github"
    domain = "github.com"

    def latest_release(self, path: str) -> Release | None:
        self._validate(path)
        payload = self.client.get_json(
            f"{API}/repos/{path}/releases/latest", forge=self.name, allow_404=True
        )
        if not payload:
            # No stable release (only pre-releases): fall back to the first entry
            # of the release list so we at least have something to report.
            entries = self.client.get_json(
                f"{API}/repos/{path}/releases?per_page=1", forge=self.name, allow_404=True
            )
            if not entries:
                return None
            payload = entries[0]
        return self._to_release(path, payload)

    def releases(self, path: str, *, limit: int = 10) -> list[Release]:
        self._validate(path)
        entries = self.client.get_json(
            f"{API}/repos/{path}/releases?per_page={limit}", forge=self.name, allow_404=True
        )
        return [self._to_release(path, entry) for entry in entries or []]

    def _to_release(self, path: str, payload: dict) -> Release:
        assets = tuple(
            Asset(
                name=asset.get("name", ""),
                url=asset.get("browser_download_url", ""),
                size=asset.get("size"),
                digest=asset.get("digest"),
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
            f"{API}/search/repositories?q={_quote(query)}&sort=stars&order=desc&per_page={limit}",
            forge=self.name,
        )
        items = (payload or {}).get("items", [])
        return [
            SearchResult(
                forge=self.name,
                path=item.get("full_name", ""),
                description=(item.get("description") or "").strip(),
                stars=item.get("stargazers_count", 0),
                updated_at=item.get("pushed_at"),
            )
            for item in items
            if item.get("full_name")
        ]

    def parse_url(self, url: str) -> str | None:
        match = URL_RE.match(url)
        if not match:
            return None
        return match.group("path").removesuffix(".git")

    @staticmethod
    def _validate(path: str) -> None:
        if not PATH_RE.match(path):
            raise ValueError(f"github expects 'owner/repo', got {path!r}")


def _quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)
