"""HTTP client with per-forge authentication, retries and rate-limit reporting.

Only the standard library is used, so alforge installs with ``pipx`` and a
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

USER_AGENT = f"alforge/{__version__} (+https://github.com/dubiduglitch/alforge)"
DEFAULT_TIMEOUT = 30.0
RETRY_STATUSES = {500, 502, 503, 504}

#: Request headers that must never follow a redirect to another host.
_SECRET_HEADERS = ("authorization", "private-token")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects without leaking forge credentials to other hosts.

    ``urllib`` copies *every* request header onto the redirected request, so a
    release download that bounces to a CDN (as GitHub does) would hand the API
    token to the CDN — or to any host a compromised forge pointed us at.  We
    drop the auth headers whenever the redirect leaves the original host.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        old_host = urllib.parse.urlsplit(req.full_url).hostname
        new_host = urllib.parse.urlsplit(newurl).hostname
        if old_host != new_host:
            for store in (new.headers, new.unredirected_hdrs):
                for key in list(store):
                    if key.lower() in _SECRET_HEADERS:
                        del store[key]
        return new


def _check_download_url(url: str) -> None:
    """Only plain HTTP(S) artifact URLs are ever fetched."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise NetworkError(f"refusing to download from a {scheme or 'relative'} URL")


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
        self._opener = urllib.request.build_opener(_SafeRedirectHandler)

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
        # Try with token first, then without (if 401)
        token_attempts = 2 if forge and self.tokens.get(forge) else 1
        for token_attempt in range(token_attempts):
            # On second attempt, temporarily remove token
            if token_attempt == 1:
                saved_token = self.tokens.pop(forge)
            try:
                for attempt in range(self.retries + 1):
                    headers = self.headers_for(forge, accept) if token_attempt == 0 else self.headers_for(None, accept)
                    request = urllib.request.Request(url, headers=headers)
                    try:
                        with self._opener.open(request, timeout=self.timeout) as response:
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
                        # If 401 on first attempt (with token), break to try without token
                        if exc.code == 401 and token_attempt == 0:
                            last_error = exc
                            break
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
            finally:
                if token_attempt == 1:
                    # Restore token
                    self.tokens[forge] = saved_token
            # If we got 401 on first attempt, continue to second attempt (without token)
            if token_attempt == 0 and isinstance(last_error, urllib.error.HTTPError) and last_error.code == 401:
                continue
            break
        raise NetworkError(f"request failed: {url} ({last_error})")

    def get_json(self, url: str, *, forge: str | None = None, allow_404: bool = False) -> Any:
        response = self.request(url, forge=forge, allow_404=allow_404)
        if response.status == 404:
            return None
        return response.json()

    def download(self, url: str, writer: Callable[[bytes], None], *, forge: str | None = None) -> int:
        """Stream a (possibly large) artifact to ``writer``. Returns byte count."""
        _check_download_url(url)
        request = urllib.request.Request(url, headers=self.headers_for(forge, accept="application/octet-stream"))
        total = 0
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
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
        hint_parts.append("run 'alforge setup' to add an API token and raise the limit")
        return NetworkError(message, hint="; ".join(hint_parts))
