"""GitLab backend (gitlab.com and self-hosted instances).

Two asset locations are supported, because GitLab projects use both:

1. release asset links (``assets.links``) - the "linked assets" section,
2. the generic package registry, which is where most GitLab projects actually
   publish ``.deb`` files.

Nested groups (``group/subgroup/project``) are supported: the whole path is
percent-encoded for the API.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit

from .base import Asset, Provider, Release, SearchResult

DEFAULT_HOST = "gitlab.com"
URL_RE = re.compile(r"^https?://(?P<host>[^/]+)/(?P<path>.+?)(?:\.git)?(?:/-/.*)?$")
SKIP_SEGMENTS = {"-", "releases", "tags", "tree", "blob", "commits", "issues", "merge_requests"}


class GitLabProvider(Provider):
    name = "gitlab"
    domain = DEFAULT_HOST

    def __init__(self, client, host: str = DEFAULT_HOST) -> None:
        super().__init__(client)
        self.host = host

    # -- api -------------------------------------------------------------- #
    def _api(self, path: str, suffix: str) -> str:
        return f"https://{self.host}/api/v4/projects/{quote(path, safe='')}{suffix}"

    def latest_release(self, path: str) -> Release | None:
        releases = self.client.get_json(
            self._api(path, "/releases?per_page=5"), forge=self.name, allow_404=True
        )
        release = None
        for candidate in releases or []:
            if candidate.get("upcoming_release"):
                continue
            release = candidate
            break
        if release is None:
            return self._from_packages(path)
        assets = self._assets_from_release(path, release)
        if not any(asset.name.endswith(".deb") for asset in assets):
            assets += self._assets_from_packages(path)
        return Release(
            forge=self.name,
            repo=path,
            tag=release.get("tag_name", ""),
            name=release.get("name"),
            prerelease=bool(release.get("upcoming_release")),
            published_at=release.get("released_at"),
            html_url=release.get("_links", {}).get("self"),
            assets=tuple(assets),
        )

    def _assets_from_release(self, path: str, release: dict) -> list[Asset]:
        assets: list[Asset] = []
        for link in (release.get("assets") or {}).get("links", []):
            url = link.get("direct_asset_url") or link.get("url") or ""
            if not url:
                continue
            assets.append(
                Asset(
                    name=link.get("name") or url.rsplit("/", 1)[-1],
                    url=url,
                )
            )
        for source in (release.get("assets") or {}).get("sources", []):
            url = source.get("url")
            if url:
                assets.append(Asset(name=url.rsplit("/", 1)[-1], url=url))
        return assets

    def _from_packages(self, path: str) -> Release | None:
        """Build a pseudo-release out of the newest generic package."""
        assets = self._assets_from_packages(path)
        if not assets:
            return None
        newest = assets[-1]
        tag = newest.name
        return Release(
            forge=self.name,
            repo=path,
            tag=tag,
            name="generic package registry",
            published_at=None,
            html_url=self.target_url(path),
            assets=tuple(assets),
        )

    def _assets_from_packages(self, path: str) -> list[Asset]:
        packages = self.client.get_json(
            self._api(path, "/packages?package_type=generic&order_by=created_at&sort=desc&per_page=20"),
            forge=self.name,
            allow_404=True,
        )
        assets: list[Asset] = []
        for package in packages or []:
            package_name = package.get("name")
            version = package.get("version")
            package_id = package.get("id")
            if not (package_name and version and package_id is not None):
                continue
            files = self.client.get_json(
                self._api(path, f"/packages/{package_id}/package_files?per_page=100"),
                forge=self.name,
                allow_404=True,
            )
            for entry in files or []:
                filename = entry.get("file_name")
                if not filename:
                    continue
                url = (
                    f"https://{self.host}/api/v4/projects/{quote(path, safe='')}"
                    f"/packages/generic/{quote(package_name, safe='')}/{quote(str(version), safe='')}"
                    f"/{quote(filename, safe='')}"
                )
                assets.append(Asset(name=filename, url=url, size=entry.get("size")))
        return assets

    # -- search ----------------------------------------------------------- #
    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        payload = self.client.get_json(
            f"https://{self.host}/api/v4/projects?search={quote(query)}&order_by=star_count"
            f"&sort=desc&per_page={limit}",
            forge=self.name,
        )
        results: list[SearchResult] = []
        for item in payload or []:
            results.append(
                SearchResult(
                    forge=self.name,
                    path=item.get("path_with_namespace", ""),
                    description=(item.get("description") or "").strip(),
                    stars=item.get("star_count", 0),
                    updated_at=item.get("last_activity_at"),
                )
            )
        return [result for result in results if result.path]

    def parse_url(self, url: str) -> str | None:
        split = urlsplit(url)
        if not split.netloc or (self.host not in split.netloc and not split.netloc.endswith("gitlab.com")):
            return None
        match = URL_RE.match(url)
        if not match:
            return None
        segments = [unquote(segment) for segment in match.group("path").split("/") if segment]
        while segments and segments[-1] in SKIP_SEGMENTS:
            segments.pop()
        if len(segments) < 2:
            return None
        return "/".join(segments)
