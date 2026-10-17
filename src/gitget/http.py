"""HTTP client with per-forge authentication, retries and rate-limit reporting.

Only the standard library is used, so gitget installs with ``pipx`` and a
single ``.deb`` without pulling dependencies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from . import __version__
from .errors import NetworkError, NotFoundError

USER_AGENT = f"gitget/{__version__} (+https://github.com/rsxn/gitget)"
DEFAULT_TIMEOUT = 30.0
RETRY_STATUSES = {500, 502, 503, 504}


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str]

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NetworkError("the forge returned a malformed JSON payload") from exc


class HttpClient:
    def __init__(
        self,
        tokens: dict[str, str] | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = 2,
    ) -> None:
        self.tokens = tokens or {}
        self.timeout = timeout
        self.retries = retries

    # -- headers ---------------------------------------------------------- #
    def headers_for(self, forge: str | None, accept: str | None = None) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": accept or "application/json"}
        token = (self.tokens.get(forge or "", "") or "").strip()
        if not token:
            return headers
        if forge == "github":
            headers["Authorization"] = f"Bearer {token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            headers["Accept"] = accept or "application/vnd.github+json"
        elif forge == "gitlab":
            headers["PRIVATE-TOKEN"] = token
        elif forge in ("gitea", "codeberg"):
            headers["Authorization"] = f"token {token}"
        else:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    # -- requests --------------------------------------------------------- #
    def request(
        self,
        url: str,
        *,
        forge: str | None = None,
        accept: str | None = None,
        allow_404: bool = False,
    ) -> Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, headers=self.headers_for(forge, accept))
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return Response(
                        status=response.status,
                        body=response.read(),
                        headers={k.lower(): v for k, v in response.headers.items()},
                    )
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and allow_404:
                    return Response(404, b"", {})
                if exc.code == 404:
                    raise NotFoundError(f"not found: {url}") from exc
                if exc.code in (403, 429):
                    raise self._rate_limit_error(exc, url) from exc
                if exc.code in RETRY_STATUSES and attempt < self.retries:
                    last_error = exc
                    time.sleep(1.0 + attempt)
                    continue
                raise NetworkError(
                    f"HTTP {exc.code} for {url}",
                    hint=exc.reason if isinstance(exc.reason, str) else None,
                ) from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.0 + attempt)
                    continue
                raise NetworkError(
                    f"cannot reach {urllib.parse.urlsplit(url).netloc}: {exc.reason}",
                    hint="check your network connection or proxy settings",
                ) from exc
            except TimeoutError as exc:
                last_error = exc
                if attempt < self.retries:
                    continue
                raise NetworkError(f"timed out after {self.timeout:.0f}s: {url}") from exc
        raise NetworkError(f"request failed: {url} ({last_error})")

    def get_json(self, url: str, *, forge: str | None = None, allow_404: bool = False) -> Any:
        response = self.request(url, forge=forge, allow_404=allow_404)
        if response.status == 404:
            return None
        return response.json()

    def download(self, url: str, writer: Callable[[bytes], None], *, forge: str | None = None) -> int:
        """Stream a (possibly large) artifact to ``writer``. Returns byte count."""
        request = urllib.request.Request(url, headers=self.headers_for(forge, accept="application/octet-stream"))
        total = 0
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    writer(chunk)
                    total += len(chunk)
        except urllib.error.HTTPError as exc:
            raise NetworkError(f"HTTP {exc.code} while downloading {url}") from exc
        except urllib.error.URLError as exc:
            raise NetworkError(f"download failed: {url} ({exc.reason})") from exc
        return total

    @staticmethod
    def _rate_limit_error(exc: urllib.error.HTTPError, url: str) -> NetworkError:
        remaining = exc.headers.get("X-RateLimit-Remaining")
        reset = exc.headers.get("X-RateLimit-Reset")
        message = "the forge API refused the request (rate limit or forbidden)"
        hint_parts = []
        if remaining == "0" and reset and reset.isdigit():
            delta = max(0, int(reset) - int(time.time()))
            hint_parts.append(f"rate limit resets in {delta // 60} min")
        hint_parts.append("run 'gitget setup' to add an API token and raise the limit")
        return NetworkError(message, hint="; ".join(hint_parts))
